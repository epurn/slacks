"""Claude Code subscription provider adapter.

Runs a locally installed, first-party Claude Code in headless mode and reads a
schema-constrained JSON object from its stdout. Authentication is owned entirely
by Claude Code (``claude login`` / the active monthly-plan session): Slacks holds
no key and stores no credential. This is the ToS-clean, plan-covered path — it
wraps the first-party binary rather than reusing Claude Code's OAuth tokens in a
homemade API client.

Security-critical: the invocation runs with **every Claude Code tool disabled**
(no bash, no file read/edit, no web/fetch) and no MCP servers, so a
prompt-injection hidden in untrusted food-log text — or printed on an uploaded
nutrition label — cannot trigger tool use, file access, or code execution on the
host. The only network the invocation performs is Claude Code's own model call.

**Image input (FTY-412).** Vision was previously refused outright here, which
made nutrition-label scanning impossible on every ``claude_code`` deployment: the
label step's one vision call raised ``LLMConfigurationError``, the step failed
closed, and the user's photographed label always came back as a terminal
``failed`` entry they had to re-type as text. Claude Code does accept images —
through its ``stream-json`` input channel, as a base64 ``image`` content block —
so the adapter now sends them that way when the configured model is declared
vision-capable (``SLACKS_LLM_SUPPORTS_VISION=true``).

The image travels on **stdin**, exactly like the prompt: it is never placed in
``argv`` (so it cannot appear in the process table) and, unlike the Codex
adapter's temporary-file approach, it is never written to disk — the bytes live
only in the pipe to the child process. The text-only invocation is deliberately
left byte-for-byte unchanged (``--output-format text``); the streaming shape is
used only when an image is actually supplied.

Like every other adapter, ``_complete`` returns the raw ``dict`` for the base
class to validate against the caller's Pydantic schema; it never validates or
logs the prompt, the model output, or any credential.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.llm.base import ImageInput, Provider, json_schema_for
from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
)

#: Default Claude Code executable name; resolved on ``PATH`` by the OS.
DEFAULT_BINARY = "claude"

#: Cap on stdout captured from the child process — mirrors the transport's
#: MAX_RESPONSE_BYTES intent without importing across layers (the transport
#: documents why it owns its own cap; this story does likewise).
MAX_STDOUT_BYTES = 1_000_000

#: Environment variables forwarded to the claude subprocess. Every key absent
#: from this set is withheld, so SLACKS_AUTH_SECRET, POSTGRES_PASSWORD,
#: SLACKS_FDC_API_KEY, SLACKS_SEARCH_API_KEY, and any other secret the
#: API/worker process holds are excluded by construction.
#:
#: Keys were determined empirically (``env -i`` scrubbing), not by guessing:
#:   PATH             — binary and child-process lookup; the binary cannot be
#:                      found without it.
#:   HOME             — fallback config dir (~/.claude) when CLAUDE_CONFIG_DIR
#:                      is absent; the binary errors on missing config without it.
#:   CLAUDE_CONFIG_DIR — session/credential directory mounted by FTY-088; this
#:                      is the primary auth surface for Slacks's deployment.
#:   LANG/LC_ALL/LC_CTYPE — locale: ensure UTF-8 text encoding so JSON output
#:                      is parseable across all deployment environments.
#:   TMPDIR           — runtime temp directory; the Bun-bundled binary creates
#:                      temp files during execution (macOS default is
#:                      /var/folders/…, not /tmp, so the var is forwarded).
#:   USER/LOGNAME     — let the macOS `claude` CLI resolve the current user and
#:                      read its Keychain-backed login session; absent-safe on
#:                      Linux/Docker (FTY-088), where the vars are not exported
#:                      by the container so nothing is forwarded and the
#:                      mounted-config-file auth path is unaffected.
_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "CLAUDE_CONFIG_DIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "USER",
        "LOGNAME",
    }
)

#: Every built-in Claude Code tool, listed so the invocation can explicitly deny
#: each one. The empty allow-list below already permits nothing, but naming the
#: tools in the deny-list makes the "no tools" intent auditable and survives a
#: tool being added to Claude Code's defaults. Only currently-known tools may be
#: listed: Claude Code rejects the whole invocation with "deny rule '<name>'
#: matches no known tool" if a deny entry names a tool it doesn't recognize, so a
#: removed/renamed tool must be dropped here (the empty allow-list still denies
#: it, and any genuinely new tool, regardless). ``MultiEdit`` was removed from
#: Claude Code (folded into ``Edit``) and so is intentionally absent.
_BUILTIN_TOOLS = (
    "Agent",
    "Bash",
    "Edit",
    "Glob",
    "Grep",
    "NotebookEdit",
    "Read",
    "Task",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Write",
)

#: Substrings that mark a non-zero exit as an authentication/login failure rather
#: than a generic error. Matched case-insensitively against stderr/stdout for
#: classification only — the matched text is never logged or surfaced.
#:
#: "login" and "log in" have been replaced with phrase-anchored forms to prevent
#: false positives from unrelated stderr that merely contains the word "login"
#: (e.g. "logging in to...", "see the changelog", compound words).
_AUTH_FAILURE_MARKERS = (
    "not logged in",  # Primary unauthenticated output: "Not logged in · ...".
    "please run /login",  # CLI instruction Claude Code emits when auth is absent.
    "please log in",  # Alternative login-prompt phrasing.
    "authenticat",  # Prefix: "authentication failed", "unauthenticated".
    "unauthorized",  # HTTP 401 / generic auth denial.
    "credential",  # Credential-related failures.
    "session expired",  # Expired session token.
)

#: Substrings that mark a non-zero exit as a transient/retryable failure rather
#: than a permanent error. Matched case-insensitively for classification only —
#: the matched text is never logged or surfaced. Phrases are derived from how
#: Claude Code reports API rate-limit (HTTP 429) and overload (HTTP 529)
#: conditions, not invented.
_TRANSIENT_FAILURE_MARKERS = (
    "rate limited",  # Claude API rate-limit response (HTTP 429).
    "overloaded",  # Claude API overload response (HTTP 529).
    "temporarily unavailable",  # Service temporarily-unavailable message.
)


@dataclass(frozen=True)
class Invocation:
    """A fully-formed Claude Code invocation, ready for the runner seam.

    ``argv`` is the command line (binary + flags) and never contains the prompt,
    so the prompt — which carries personal context — is not exposed in the
    process table. The prompt and its schema instruction are fed to the process
    on ``stdin`` instead. Tests inspect ``argv`` to assert no tools are enabled.
    """

    argv: tuple[str, ...]
    stdin: str


@dataclass(frozen=True)
class ClaudeCodeResult:
    """The raw outcome of one Claude Code invocation (process-level, unparsed)."""

    returncode: int
    stdout: str
    stderr: str


#: The subprocess seam: runs an :class:`Invocation` and returns its raw result.
#: Mirrors ``app.llm.transport.post_json`` as the injectable boundary so unit
#: tests drive success/failure deterministically with no real subprocess. The
#: default implementation (:func:`run_claude_code`) shells out to the binary.
ClaudeCodeRunner = Callable[..., ClaudeCodeResult]


def run_claude_code(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
    """Default runner: execute the local Claude Code binary and capture output.

    Raises the OS-level exceptions (``FileNotFoundError`` when the binary is
    absent, ``subprocess.TimeoutExpired`` on the per-attempt timeout, other
    ``OSError`` on a spawn failure) for :class:`ClaudeCodeProvider` to map onto
    the LLM error taxonomy. The command runs without a shell, and the prompt is
    supplied on stdin (never in ``argv``).

    The subprocess receives only the variables in :data:`_ENV_ALLOWLIST`,
    copied from the parent environment when present. This ensures that
    ``SLACKS_AUTH_SECRET``, ``POSTGRES_PASSWORD``, and every other secret the
    API/worker process holds are absent from the child's environment by
    construction, making the module's no-credential-leak guarantee enforceable
    rather than merely asserted.
    """

    child_env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}
    completed = subprocess.run(  # noqa: S603 — fixed argv, no shell, tools disabled
        list(invocation.argv),
        input=invocation.stdin,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        env=child_env,
    )
    return ClaudeCodeResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


class ClaudeCodeProvider(Provider):
    """Adapter wrapping a local first-party Claude Code session (subscription)."""

    name = "claude_code"

    def __init__(
        self,
        *,
        model: str = "",
        timeout_seconds: float,
        max_retries: int,
        supports_vision: bool = False,
        binary: str = DEFAULT_BINARY,
        runner: ClaudeCodeRunner = run_claude_code,
    ) -> None:
        # ``supports_vision`` gates image input exactly as it does for every other
        # adapter (FTY-412): declared vision-capable, images are sent through the
        # stream-json channel; otherwise the base class rejects them before any
        # call, so an image is never silently dropped.
        super().__init__(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            supports_vision=supports_vision,
            model=model,
        )
        self._binary = binary
        self._runner = runner

    def build_invocation(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        images: Sequence[ImageInput] | None = None,
    ) -> Invocation:
        """Construct the headless, all-tools-disabled invocation for ``prompt``.

        With no ``images`` this is the unchanged text invocation
        (``--output-format text``, prompt on stdin). With images it switches to
        the ``stream-json`` input/output channel, the only way Claude Code accepts
        image content, and the prompt plus base64 image blocks travel as a single
        user message on stdin.

        Exposed for tests to assert that the invocation enables no tools and
        never carries the prompt or image bytes in ``argv``.
        """

        argv: list[str] = [
            self._binary,
            "--print",  # headless: print the result and exit, no interactive loop
            "--output-format",
            # Images can only be supplied through the streaming JSON channel, and
            # Claude Code requires the output format to match it (and --verbose).
            *(
                ["stream-json", "--input-format", "stream-json", "--verbose"]
                if images
                else ["text"]  # stdout is the model's text (our schema-constrained JSON)
            ),
            # Disable every tool: an empty allow-list permits nothing, and each
            # built-in is named in the deny-list so the intent is auditable. With
            # no tools there is no bash/file/web capability — a prompt-injection
            # in untrusted food-log text cannot act on the host.
            "--allowed-tools",
            "",
            "--disallowed-tools",
            ",".join(_BUILTIN_TOOLS),
            # Never auto-grant a permission prompt; in headless mode an ungranted
            # request is denied rather than waited on. Crucially NOT
            # ``bypassPermissions`` and NOT ``--dangerously-skip-permissions``.
            "--permission-mode",
            "default",
            # Ignore any filesystem MCP config and load no MCP servers, so no
            # external MCP tools can slip in past the built-in deny-list.
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
        ]
        if self.model:
            # Optional: Claude Code defaults to the session/plan model when empty.
            argv += ["--model", self.model]

        return Invocation(argv=tuple(argv), stdin=_build_stdin(prompt, schema, images))

    def _complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if images and not self._supports_vision:
            # Belt-and-suspenders for the base class's gate: never silently drop
            # an image when the configured model was not declared vision-capable.
            raise LLMConfigurationError(
                "image input requires a vision-capable configured model "
                "(set SLACKS_LLM_SUPPORTS_VISION=true for a vision model)"
            )

        invocation = self.build_invocation(prompt, schema, images=images)
        try:
            result = self._runner(invocation, timeout_seconds=timeout_seconds)
        except FileNotFoundError:
            # Binary not installed / not on PATH. Not retryable.
            raise LLMConfigurationError(
                "claude code binary not found; install Claude Code and run 'claude login'"
            ) from None
        except subprocess.TimeoutExpired:
            # Per-attempt timeout: retryable within the configured bound.
            raise LLMTransientError("claude code call timed out") from None
        except OSError:
            # Spawn/transport hiccup (e.g. exec failure): retryable.
            raise LLMTransientError("claude code invocation failed") from None

        # Stdout size guard — a runaway or hostile reply must not balloon worker
        # memory. Checked before returncode so the cap applies to all outcomes.
        # The offending text is never echoed (content-free message, matching the
        # transport's "provider returned an oversized body" pattern).
        if len(result.stdout) > MAX_STDOUT_BYTES:
            raise LLMResponseError("claude code returned an oversized body")

        if result.returncode != 0:
            if _looks_like_auth_failure(result):
                # Not logged in / unauthenticated. Content-free; point at the fix.
                raise LLMConfigurationError("claude code is not authenticated; run 'claude login'")
            if _looks_like_transient_failure(result):
                # Rate-limited or overloaded — retrying may succeed.
                raise LLMTransientError("claude code is temporarily unavailable")
            # Any other non-zero exit: the run failed in a way retrying won't fix
            # deterministically. Never echo stderr (it may carry untrusted input).
            raise LLMResponseError("claude code exited with an error")

        # A vision call streams NDJSON events; the model's text is the final
        # result event's payload. A text call prints that text directly.
        stdout = _stream_json_result_text(result.stdout) if images else result.stdout
        return _parse_object(stdout)


def _instructed_prompt(prompt: str, schema: type[BaseModel]) -> str:
    """The prompt plus the schema-constrained JSON instruction both channels share.

    The schema is the same artifact every provider uses (``json_schema_for``).
    """

    schema_json = json.dumps(json_schema_for(schema), separators=(",", ":"))
    return (
        f"{prompt}\n\n"
        "Respond with a single JSON object and nothing else — no prose, no "
        "markdown, no code fences. The object must conform exactly to this JSON "
        f"Schema:\n{schema_json}"
    )


def _build_stdin(
    prompt: str, schema: type[BaseModel], images: Sequence[ImageInput] | None = None
) -> str:
    """Build the stdin payload for the text or the image (stream-json) channel.

    Text-only output is unchanged: the instructed prompt as plain text. With
    images it becomes one ``stream-json`` user message whose content is the
    instructed prompt followed by a base64 ``image`` block per image — the shape
    Claude Code accepts image input in (FTY-412).

    The prompt and the image bytes are untrusted and are fed on stdin (never
    argv, never a temp file), and nothing here is logged.
    """

    instructed = _instructed_prompt(prompt, schema)
    if not images:
        return instructed

    content: list[dict[str, Any]] = [{"type": "text", "text": instructed}]
    content += [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image.media_type,
                "data": base64.b64encode(image.data).decode("ascii"),
            },
        }
        for image in images
    ]
    message = {"type": "user", "message": {"role": "user", "content": content}}
    # A single NDJSON line: one user turn, then the stream closes and Claude Code
    # answers it (headless --print exits after the turn).
    return json.dumps(message, separators=(",", ":")) + "\n"


def _stream_json_result_text(stdout: str) -> str:
    """Extract the model's final text from a ``stream-json`` NDJSON transcript.

    The transcript interleaves ``system`` / ``assistant`` / ``rate_limit_event``
    events; the terminal ``result`` event carries the completed reply. Anything
    else — no result event, an error result, or unparseable NDJSON — is an
    unusable reply (:class:`LLMResponseError`). The transcript is never echoed:
    it may carry text transcribed from an untrusted image.
    """

    for raw_line in reversed(stdout.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        try:
            event: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "result":
            continue
        if event.get("is_error") or event.get("subtype") != "success":
            # The run completed but reported failure (e.g. a refused turn).
            raise LLMResponseError("claude code reported an unsuccessful result")
        text = event.get("result")
        if not isinstance(text, str):
            raise LLMResponseError("claude code returned no result text")
        return text

    raise LLMResponseError("claude code returned no result event")


def _looks_like_auth_failure(result: ClaudeCodeResult) -> bool:
    """Classify a non-zero exit as an auth/login failure (for error mapping only).

    Inspects stderr/stdout for known markers. The inspected text is used solely
    to choose the error type and is never logged or placed in a message.
    """

    haystack = f"{result.stderr}\n{result.stdout}".lower()
    return any(marker in haystack for marker in _AUTH_FAILURE_MARKERS)


def _looks_like_transient_failure(result: ClaudeCodeResult) -> bool:
    """Classify a non-zero exit as a transient/retryable failure (for error mapping only).

    Inspects stderr/stdout for known markers. The inspected text is used solely
    to choose the error type and is never logged or placed in a message.
    Called only after auth-failure classification has been ruled out.
    """

    haystack = f"{result.stderr}\n{result.stdout}".lower()
    return any(marker in haystack for marker in _TRANSIENT_FAILURE_MARKERS)


#: Matches a leading ```json or ``` fence opener (with optional trailing whitespace/newline).
_FENCE_START_RE = re.compile(r"^```(?:json)?\s*\n?", re.IGNORECASE)
#: Matches a trailing ``` fence closer (with optional preceding newline).
_FENCE_END_RE = re.compile(r"\n?```\s*$")


def _extract_first_json_object(text: str) -> tuple[str, str] | None:  # noqa: C901 — brace/string scanner
    """Find the first balanced top-level ``{...}`` object in ``text``.

    Returns ``(object_text, remainder)`` where ``remainder`` is everything after
    the closing brace, or ``None`` if no balanced object is found. Correctly
    skips ``{`` / ``}`` inside JSON strings (respecting backslash escapes).
    """

    start = -1
    depth = 0
    in_string = False
    escape = False

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                return text[start : i + 1], text[i + 1 :]

    return None


def _parse_object(stdout: str) -> dict[str, Any]:
    """Parse Claude Code stdout into the raw structured object.

    Tolerates a leading/trailing code fence (```json or ```) and a prose line
    preceding the object, then extracts the first balanced top-level ``{...}``
    object.  Trailing non-whitespace after the object is rejected to catch
    garbled/double emissions.  Non-JSON, non-object, or trailing-junk output
    maps to ``LLMResponseError``; the offending text is never echoed.
    """

    text = stdout.strip()

    # Strip code fence wrapper if present before extracting the object.
    if text.startswith("```"):
        text = _FENCE_START_RE.sub("", text, count=1)
        text = _FENCE_END_RE.sub("", text)
        text = text.strip()

    extracted = _extract_first_json_object(text)
    if extracted is None:
        raise LLMResponseError("claude code returned a non-JSON body") from None

    json_text, remainder = extracted

    # Reject trailing non-whitespace — signals a garbled/double emission.
    if remainder.strip():
        raise LLMResponseError("claude code returned trailing content after JSON object") from None

    try:
        parsed: Any = json.loads(json_text)
    except json.JSONDecodeError:
        raise LLMResponseError("claude code returned a non-JSON body") from None
    if not isinstance(parsed, dict):
        raise LLMResponseError("claude code returned a non-object JSON body") from None
    return parsed
