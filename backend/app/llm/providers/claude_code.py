"""Claude Code subscription provider adapter.

Runs a locally installed, first-party Claude Code in headless mode and reads a
schema-constrained JSON object from its stdout. Authentication is owned entirely
by Claude Code (``claude login`` / the active monthly-plan session): Fatty holds
no key and stores no credential. This is the ToS-clean, plan-covered path — it
wraps the first-party binary rather than reusing Claude Code's OAuth tokens in a
homemade API client.

Security-critical: the invocation runs with **every Claude Code tool disabled**
(no bash, no file read/edit, no web/fetch) and no MCP servers, so a
prompt-injection hidden in untrusted food-log text cannot trigger tool use, file
access, or code execution on the host. The only network the invocation performs
is Claude Code's own model call.

Like every other adapter, ``_complete`` returns the raw ``dict`` for the base
class to validate against the caller's Pydantic schema; it never validates or
logs the prompt, the model output, or any credential.
"""

from __future__ import annotations

import json
import subprocess  # noqa: S404 — invocation is fixed argv, tools disabled, no shell
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
_AUTH_FAILURE_MARKERS = (
    "not logged in",
    "log in",
    "login",
    "authenticat",
    "unauthorized",
    "credential",
    "session expired",
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
    the LLM error taxonomy. The command runs without a shell and inherits no
    extra arguments, and the prompt is supplied on stdin (never in ``argv``).
    """

    completed = subprocess.run(  # noqa: S603 — fixed argv, no shell, tools disabled
        list(invocation.argv),
        input=invocation.stdin,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
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
        binary: str = DEFAULT_BINARY,
        runner: ClaudeCodeRunner = run_claude_code,
    ) -> None:
        # ``supports_vision`` is intentionally not threaded through: image input
        # via claude_code is an explicit non-goal, so the base class rejects
        # images before they ever reach this adapter (fail fast, never dropped).
        super().__init__(timeout_seconds=timeout_seconds, max_retries=max_retries)
        self._model = model
        self._binary = binary
        self._runner = runner

    def build_invocation(self, prompt: str, schema: type[BaseModel]) -> Invocation:
        """Construct the headless, all-tools-disabled invocation for ``prompt``.

        Exposed for tests to assert that the invocation enables no tools and
        never carries the prompt in ``argv``.
        """

        argv: list[str] = [
            self._binary,
            "--print",  # headless: print the result and exit, no interactive loop
            "--output-format",
            "text",  # stdout is the model's text (our schema-constrained JSON)
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
        if self._model:
            # Optional: Claude Code defaults to the session/plan model when empty.
            argv += ["--model", self._model]

        return Invocation(argv=tuple(argv), stdin=_build_stdin(prompt, schema))

    def _complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if images:
            # Vision via claude_code is an explicit non-goal: fail fast rather
            # than silently dropping the image. (The base class already blocks
            # images unless a model is declared vision-capable; this is the
            # belt-and-suspenders guard for that case.)
            raise LLMConfigurationError("provider 'claude_code' does not support image input")

        invocation = self.build_invocation(prompt, schema)
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

        if result.returncode != 0:
            if _looks_like_auth_failure(result):
                # Not logged in / unauthenticated. Content-free; point at the fix.
                raise LLMConfigurationError("claude code is not authenticated; run 'claude login'")
            # Any other non-zero exit: the run failed in a way retrying won't fix
            # deterministically. Never echo stderr (it may carry untrusted input).
            raise LLMResponseError("claude code exited with an error")

        return _parse_object(result.stdout)


def _build_stdin(prompt: str, schema: type[BaseModel]) -> str:
    """Build the stdin payload: the prompt plus a schema-constrained JSON instruction.

    The schema is the same artifact every provider uses (``json_schema_for``).
    The prompt is untrusted and is fed on stdin (never argv), and nothing here is
    logged.
    """

    schema_json = json.dumps(json_schema_for(schema), separators=(",", ":"))
    return (
        f"{prompt}\n\n"
        "Respond with a single JSON object and nothing else — no prose, no "
        "markdown, no code fences. The object must conform exactly to this JSON "
        f"Schema:\n{schema_json}"
    )


def _looks_like_auth_failure(result: ClaudeCodeResult) -> bool:
    """Classify a non-zero exit as an auth/login failure (for error mapping only).

    Inspects stderr/stdout for known markers. The inspected text is used solely
    to choose the error type and is never logged or placed in a message.
    """

    haystack = f"{result.stderr}\n{result.stdout}".lower()
    return any(marker in haystack for marker in _AUTH_FAILURE_MARKERS)


def _parse_object(stdout: str) -> dict[str, Any]:
    """Parse Claude Code stdout into the raw structured object.

    Non-JSON or non-object output is unusable and maps to ``LLMResponseError``;
    the offending text is never echoed into the message.
    """

    try:
        parsed: Any = json.loads(stdout)
    except json.JSONDecodeError:
        raise LLMResponseError("claude code returned a non-JSON body") from None
    if not isinstance(parsed, dict):
        raise LLMResponseError("claude code returned a non-object JSON body") from None
    return parsed
