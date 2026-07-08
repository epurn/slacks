"""Codex CLI text provider adapter.

Runs a locally installed, first-party Codex CLI in non-interactive
``codex exec`` mode and reads one JSON object from stdout. Authentication is
owned by Codex CLI saved state unless the operator supplies
``FATTY_LLM_API_KEY``; when supplied, the key is exposed only to this child
process as ``CODEX_API_KEY``.

Security-critical: the prompt is sent over stdin, never argv; the command runs
without a shell; the child runs from a dedicated empty temp workdir; user/project
rules, config, approvals, and web search are disabled; and the child receives an
explicit environment allowlist. Like every provider, this adapter returns only a
raw ``dict`` for the base class to validate against the caller's Pydantic schema.
It never logs prompts, raw stdout/stderr, keys, tokens, or temp paths.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.llm.base import ImageInput, Provider, json_schema_for
from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
)

#: Default Codex executable name; resolved on ``PATH`` by the OS.
DEFAULT_BINARY = "codex"

#: Cap on stdout captured from the child process. This mirrors the other
#: provider transport caps: a runaway or hostile subprocess response must not
#: balloon worker memory or exception processing.
MAX_STDOUT_BYTES = 1_000_000

#: Environment variables forwarded from the parent process to Codex. Every key
#: absent from this set is withheld by construction, so FATTY_AUTH_SECRET,
#: POSTGRES_PASSWORD, OPENAI_API_KEY, FDC/search keys, and arbitrary process
#: secrets are not visible to the subprocess.
_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "CODEX_HOME",
        "CODEX_SQLITE_HOME",
        "CODEX_CA_CERTIFICATE",
        "SSL_CERT_FILE",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "LC_COLLATE",
        "LC_MONETARY",
        "LC_NUMERIC",
        "LC_TIME",
        "TMPDIR",
        "TEMP",
        "TMP",
    }
)

#: Substrings that mark a non-zero exit as a Codex auth/config credential
#: problem. Matched case-insensitively against stderr/stdout for classification
#: only; the matched text is never logged or surfaced.
_AUTH_FAILURE_MARKERS = (
    "not logged in",
    "please run codex login",
    "please log in",
    "login required",
    "authenticat",
    "authentication failed",
    "unauthorized",
    "invalid api key",
    "invalid api_key",
    "credential",
    "access token",
    "session expired",
    "no api key",
)

#: Substrings that mark a non-zero exit as retryable. Kept small and specific to
#: common provider-pressure failures.
_TRANSIENT_FAILURE_MARKERS = (
    "rate limited",
    "rate limit",
    "429",
    "overloaded",
    "overload",
    "temporarily unavailable",
    "service unavailable",
)

#: Codex CLI image attachment formats that are part of the public Slacks
#: contract. ``ImageInput`` also accepts WebP/GIF for other providers, but Codex
#: support for those formats has not been established and therefore fails closed.
_CODEX_IMAGE_EXTENSIONS: Mapping[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


@dataclass(frozen=True)
class Invocation:
    """A fully formed Codex invocation, ready for the runner seam.

    ``argv`` is the command line (binary + fixed flags) and never contains the
    prompt. ``stdin`` carries the prompt. ``cwd`` is a dedicated empty temp
    workdir, and ``env`` is the explicit allowlist supplied to the child.
    """

    argv: tuple[str, ...]
    stdin: str
    cwd: str
    env: Mapping[str, str]


@dataclass(frozen=True)
class CodexResult:
    """The raw outcome of one Codex CLI invocation."""

    returncode: int
    stdout: str
    stderr: str


#: The subprocess seam: tests inject a runner so they never spawn a real Codex
#: CLI. The default implementation shells out with fixed argv and no shell.
CodexRunner = Callable[..., CodexResult]


def run_codex(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
    """Default runner: execute the local Codex CLI and capture output.

    OS-level failures are deliberately propagated for :class:`CodexProvider` to
    map onto the shared LLM error taxonomy. The prompt is supplied through
    stdin, and the child receives only ``invocation.env``.
    """

    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        list(invocation.argv),
        input=invocation.stdin,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        cwd=invocation.cwd,
        env=dict(invocation.env),
    )
    return CodexResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


class CodexProvider(Provider):
    """Adapter wrapping a local first-party Codex CLI installation."""

    name = "codex"

    def __init__(
        self,
        *,
        model: str = "",
        api_key: str | None = None,
        timeout_seconds: float,
        max_retries: int,
        supports_vision: bool = False,
        binary: str = DEFAULT_BINARY,
        runner: CodexRunner = run_codex,
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            supports_vision=supports_vision,
        )
        self._model = model
        self._api_key = api_key
        self._binary = binary
        self._runner = runner

    def build_invocation(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        schema_path: Path,
        workdir: Path,
        image_paths: Sequence[Path] | None = None,
    ) -> Invocation:
        """Construct the isolated ``codex exec`` invocation for ``prompt``."""

        _write_schema(schema_path, schema)

        argv: list[str] = [
            self._binary,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "--ignore-user-config",
            "--ignore-rules",
            "-c",
            'web_search="disabled"',
            "--output-schema",
            str(schema_path),
        ]
        if self._model:
            argv += ["--model", self._model]
        for image_path in image_paths or ():
            argv += ["--image", str(image_path)]
        argv.append("-")

        return Invocation(
            argv=tuple(argv),
            stdin=prompt,
            cwd=str(workdir),
            env=_build_child_env(api_key=self._api_key),
        )

    def _complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="fatty-codex-") as temp_root_name:
            temp_root = Path(temp_root_name)
            workdir = temp_root / "work"
            workdir.mkdir(mode=0o700)
            schema_path = temp_root / "output_schema.json"
            image_paths = _write_image_files(temp_root, images)
            invocation = self.build_invocation(
                prompt,
                schema,
                schema_path=schema_path,
                workdir=workdir,
                image_paths=image_paths,
            )

            try:
                result = self._runner(invocation, timeout_seconds=timeout_seconds)
            except FileNotFoundError:
                raise LLMConfigurationError(
                    "codex binary not found; install Codex CLI and configure auth"
                ) from None
            except subprocess.TimeoutExpired:
                raise LLMTransientError("codex call timed out") from None
            except OSError:
                raise LLMTransientError("codex invocation failed") from None

            if len(result.stdout) > MAX_STDOUT_BYTES:
                raise LLMResponseError("codex returned an oversized body")

            if result.returncode != 0:
                if _looks_like_auth_failure(result):
                    raise LLMConfigurationError("codex is not authenticated; configure Codex auth")
                if _looks_like_transient_failure(result):
                    raise LLMTransientError("codex is temporarily unavailable")
                raise LLMResponseError("codex exited with an error")

            return _parse_object(result.stdout)


def _write_schema(schema_path: Path, schema: type[BaseModel]) -> None:
    """Write the caller's JSON Schema to a temporary file without user data."""

    schema_json = json.dumps(json_schema_for(schema), separators=(",", ":"), sort_keys=True)
    schema_path.write_text(schema_json, encoding="utf-8")


def _write_image_files(
    temp_root: Path,
    images: Sequence[ImageInput] | None,
) -> tuple[Path, ...]:
    """Materialize Codex image attachments as restrictive temp files."""

    image_paths: list[Path] = []
    for index, image in enumerate(images or ()):
        extension = _CODEX_IMAGE_EXTENSIONS.get(image.media_type)
        if extension is None:
            raise LLMConfigurationError("codex supports only JPEG and PNG image input")
        image_path = temp_root / f"image-{index}{extension}"
        _write_restrictive_bytes(image_path, image.data)
        image_paths.append(image_path)
    return tuple(image_paths)


def _write_restrictive_bytes(path: Path, data: bytes) -> None:
    """Create ``path`` with owner-only permissions and write ``data``."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(data)
    finally:
        if fd != -1:
            os.close(fd)


def _build_child_env(*, api_key: str | None) -> dict[str, str]:
    """Build the explicit environment allowlist for the Codex child process."""

    child_env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}
    if api_key:
        child_env["CODEX_API_KEY"] = api_key
    return child_env


def _looks_like_auth_failure(result: CodexResult) -> bool:
    """Classify a non-zero exit as an auth/setup failure."""

    haystack = f"{result.stderr}\n{result.stdout}".lower()
    return any(marker in haystack for marker in _AUTH_FAILURE_MARKERS)


def _looks_like_transient_failure(result: CodexResult) -> bool:
    """Classify a non-zero exit as retryable provider pressure."""

    haystack = f"{result.stderr}\n{result.stdout}".lower()
    return any(marker in haystack for marker in _TRANSIENT_FAILURE_MARKERS)


def _parse_object(stdout: str) -> dict[str, Any]:
    """Parse stdout as exactly one JSON object.

    Leading and trailing whitespace are accepted. Any non-whitespace content
    before the object, after the object, non-JSON body, or non-object JSON value
    fails closed as ``LLMResponseError`` without echoing the offending text.
    """

    text = stdout.lstrip()
    if not text:
        raise LLMResponseError("codex returned a non-JSON body") from None
    try:
        parsed, end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        raise LLMResponseError("codex returned a non-JSON body") from None
    if text[end:].strip():
        raise LLMResponseError("codex returned trailing content after JSON object") from None
    if not isinstance(parsed, dict):
        raise LLMResponseError("codex returned a non-object JSON body") from None
    return parsed
