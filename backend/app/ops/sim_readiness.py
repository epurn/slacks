"""Local v1 simulator-readiness smoke (FTY-250).

Operator command run **before** testing Fatty in an iOS simulator. It verifies
the local Docker Compose stack is *coherent* — backend images built from one
checkout, Alembic at the code head, API / worker / source health green — and
prints the exact simulator connect URL derived from ``.env`` ``API_PORT``, so a
fresh install connects to the actually-published API instead of failing later
with a confusing in-app error.

The smoke that motivated this story found a stack that served ``/healthz`` but was
*not* ready: the API, worker, and migrate images were built from different
checkouts, Postgres was at Alembic ``0016`` while the code required ``0017``, and
the mobile fallback URL (``localhost:8000``) did not match the published
``API_PORT=18000``. This command fails loudly on exactly those drifts.

Design constraints (see ``docs/operations/local-dev-stack.md``):

- **Read-only.** It detects drift and prints the coherent fix path; it never
  mutates the stack (no rebuild, migrate, or restart is performed for you).
- **No secrets.** It reads ``.env`` and config only to derive non-secret facts
  (the API port, the active provider names). Secret values — the auth secret,
  the database password, provider API keys, tokens, session material — are never
  printed. The ``/healthz/sources`` payload it summarizes is booleans only.

Run it from the repo root once the stack is up::

    make sim-smoke
    # or, directly:
    cd backend && uv run python -m app.ops.sim_readiness
"""

from __future__ import annotations

import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from json import JSONDecodeError, loads
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

#: The compose default published API port when ``API_PORT`` is unset in ``.env``.
DEFAULT_API_PORT = 8000

#: Inclusive TCP port bounds for a valid ``API_PORT``.
_MIN_PORT = 1
_MAX_PORT = 65535

#: HTTP status a healthy probe returns.
_HTTP_OK = 200

#: ``docker compose`` backend services that all build from ``./backend``. When the
#: stack is coherent they resolve to the same image id; divergent ids mean one was
#: rebuilt from a different checkout than the others.
BACKEND_IMAGE_SERVICES: tuple[str, ...] = ("api", "worker", "migrate")

#: Substrings that mark an env var *key* as carrying a secret value. Matched
#: case-insensitively; a key that matches is never printed with its value.
_SECRET_KEY_MARKERS: tuple[str, ...] = (
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "TOKEN",
    "API_KEY",
    "APIKEY",
    "_KEY",
    "SESSION",
    "CREDENTIAL",
)

#: Non-secret env vars the report surfaces (each still passed through redaction as
#: a defensive backstop). Deliberately excludes DSNs, which embed a password.
_REPORTED_ENV_KEYS: tuple[str, ...] = (
    "FATTY_ENVIRONMENT",
    "FATTY_LLM_PROVIDER",
    "FATTY_SEARCH_PROVIDER",
    "FATTY_OFF_ENABLED",
)

_REDACTED = "«redacted»"

#: ``app/ops/sim_readiness.py`` → ``backend/`` is three parents up; the repo root
#: (where ``.env`` and ``docker-compose.yml`` live) is one further.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_ROOT.parent


# --------------------------------------------------------------------------- #
# Pure logic (unit-tested): env parsing, URL derivation, redaction, drift.
# --------------------------------------------------------------------------- #


def parse_env(env_text: str) -> dict[str, str]:
    """Parse ``.env`` text into a mapping, mirroring compose ``env_file`` rules.

    Blank lines and ``#`` comment lines are skipped; each remaining ``KEY=VALUE``
    is split on the first ``=``. Values are kept verbatim apart from surrounding
    whitespace (compose does not honour inline ``#`` comments after a value, so
    neither do we).
    """

    env: dict[str, str] = {}
    for raw in env_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            env[key] = value.strip()
    return env


def parse_api_port(env: Mapping[str, str]) -> int:
    """Resolve the published host API port from parsed ``.env`` values.

    Absent ``API_PORT`` falls back to the compose default (:data:`DEFAULT_API_PORT`).
    A present-but-malformed value is an operator error and raises ``ValueError``
    rather than silently printing a wrong connect URL.
    """

    raw = env.get("API_PORT", "").strip()
    if not raw:
        return DEFAULT_API_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(f"API_PORT is not an integer: {raw!r}") from None
    if not _MIN_PORT <= port <= _MAX_PORT:
        raise ValueError(f"API_PORT out of range {_MIN_PORT}-{_MAX_PORT}: {port}")
    return port


def simulator_url(api_port: int) -> str:
    """The connect-screen server URL a simulator on this host should use.

    The simulator shares the host loopback, so it reaches the published API at
    ``http://localhost:<API_PORT>`` — not the mobile code's ``localhost:8000``
    fallback, which is only correct when ``API_PORT`` is left at its default.
    """

    return f"http://localhost:{api_port}"


def is_secret_env_key(key: str) -> bool:
    """True when an env var *key* names a secret whose value must not be printed."""

    upper = key.upper()
    return any(marker in upper for marker in _SECRET_KEY_MARKERS)


def redact_env_value(key: str, value: str) -> str:
    """Return ``value`` for a non-secret key, or a redaction marker for a secret.

    An empty value is returned unchanged (there is nothing to leak, and blank is
    a meaningful "unset"). This is the single choke point every surfaced env value
    passes through.
    """

    if value == "":
        return ""
    return _REDACTED if is_secret_env_key(key) else value


def reported_env(env: Mapping[str, str]) -> list[tuple[str, str]]:
    """The curated, redacted (key, value) pairs the report surfaces."""

    return [(key, redact_env_value(key, env[key])) for key in _REPORTED_ENV_KEYS if key in env]


@dataclass(frozen=True)
class AlembicStatus:
    """The DB's applied Alembic revision versus the code's head revision."""

    db_version: str | None
    code_head: str

    @property
    def at_head(self) -> bool:
        """True only when the DB is exactly at the code head."""

        return self.db_version is not None and self.db_version == self.code_head

    @property
    def message(self) -> str:
        """A one-line, operator-facing drift summary."""

        if self.db_version is None:
            return (
                f"database Alembic version could not be read; code head is "
                f"{self.code_head} (is the stack up and migrated?)"
            )
        if self.at_head:
            return f"database at Alembic head {self.code_head}"
        return (
            f"Alembic DRIFT: database at {self.db_version}, code head is "
            f"{self.code_head} — run migrations"
        )


@dataclass(frozen=True)
class ImageCoherence:
    """Whether the backend services share one image built from one checkout."""

    image_ids: Mapping[str, str | None]

    @property
    def coherent(self) -> bool:
        """True when every backend service is built and shares one image id."""

        values = list(self.image_ids.values())
        if not values or any(v is None for v in values):
            return False
        return len(set(values)) == 1

    @property
    def message(self) -> str:
        """A one-line, operator-facing coherence summary."""

        missing = [svc for svc, img in self.image_ids.items() if img is None]
        if missing:
            return f"backend image(s) not built: {', '.join(missing)} — rebuild the stack"
        if self.coherent:
            single = next(iter(self.image_ids.values()))
            short = (single or "")[:19]
            return f"backend images coherent ({short})"
        return (
            "image DRIFT: api/worker/migrate were built from different checkouts "
            "— rebuild the stack"
        )


@dataclass(frozen=True)
class WorkerHealth:
    """Whether the Celery worker is running and answering ``inspect ping``.

    The HTTP probes only cover the API; a stopped or wedged worker serves no
    endpoint yet leaves estimator jobs stuck later. This mirrors the compose
    worker healthcheck (``celery -A app.worker:celery_app inspect ping``).
    """

    responded: bool
    detail: str

    @property
    def healthy(self) -> bool:
        """True only when a worker answered the ping with a pong."""

        return self.responded

    @property
    def message(self) -> str:
        """A one-line, operator-facing worker-health summary."""

        if self.responded:
            return "Celery worker responding to inspect ping"
        return (
            f"worker not responding to inspect ping ({self.detail}) "
            "— is the worker container running and connected to Redis?"
        )


def worker_health_from_ping(returncode: int, stdout: str, stderr: str) -> WorkerHealth:
    """Interpret ``celery inspect ping`` output; healthy iff a worker ponged.

    Celery exits non-zero and prints an error when no worker replies; a live
    worker exits zero and echoes ``-> <node>: OK / pong``. Kept pure so the
    happy and stopped-worker paths are unit-tested without a live stack.
    """

    if returncode == 0 and "pong" in f"{stdout}\n{stderr}".lower():
        return WorkerHealth(responded=True, detail="pong")
    first_line = next(
        (line.strip() for line in (stderr + "\n" + stdout).splitlines() if line.strip()),
        "no response",
    )
    return WorkerHealth(responded=False, detail=first_line[:80])


def summarize_sources(payload: object) -> list[str]:
    """Format the ``/healthz/sources`` payload as redacted one-liners.

    The payload is booleans-only by contract, but this stays defensive: any field
    whose key looks secret is redacted before formatting. Returns a placeholder
    line when the payload is not the expected shape.
    """

    if not isinstance(payload, Mapping):
        return ["(unexpected /healthz/sources payload)"]
    sources = payload.get("sources")
    if not isinstance(sources, Sequence):
        return ["(no sources in /healthz/sources payload)"]

    lines: list[str] = []
    for entry in sources:
        if not isinstance(entry, Mapping):
            continue
        source_id = str(entry.get("id", "?"))
        source_type = str(entry.get("source_type", "?"))
        enabled = bool(entry.get("enabled", False))
        available = bool(entry.get("available", False))
        # Defensive redaction: the contract carries no secrets, but never echo a
        # value under a secret-looking key even if the shape changes.
        for field_key in entry:
            if is_secret_env_key(str(field_key)):
                source_id = _REDACTED
                break
        lines.append(f"{source_id} [{source_type}] enabled={enabled} available={available}")
    return lines or ["(no evidence sources reported)"]


def code_head_revision() -> str:
    """The Alembic head revision the current backend checkout expects.

    Read from the migration scripts via Alembic's own machinery so it always
    reflects the code, not a hard-coded constant that could rot.
    """

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("no Alembic head revision found in backend/alembic/versions")
    return head


# --------------------------------------------------------------------------- #
# Orchestration (side-effectful): shell out to Docker Compose, probe HTTP.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HttpProbe:
    """The outcome of a single health-endpoint request."""

    url: str
    status: int | None
    body: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.status == _HTTP_OK


def _run_compose(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run ``docker compose <args>`` from the repo root, capturing output."""

    argv = ["docker", "compose", *args]
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        argv,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def read_env_file() -> str | None:
    """Return the repo-root ``.env`` contents, or ``None`` if it is absent."""

    env_path = _REPO_ROOT / ".env"
    if not env_path.is_file():
        return None
    return env_path.read_text(encoding="utf-8")


def query_db_alembic_version(env: Mapping[str, str]) -> str | None:
    """Read ``alembic_version.version_num`` from the running Postgres container.

    Uses ``docker compose exec`` over the internal network, so it works even
    though Postgres publishes no host port. Returns ``None`` on any failure
    (stack down, table missing, psql error).
    """

    user = env.get("POSTGRES_USER", "fatty")
    database = env.get("POSTGRES_DB", "fatty")
    result = _run_compose(
        [
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            user,
            "-d",
            database,
            "-tAc",
            "SELECT version_num FROM alembic_version",
        ]
    )
    if result.returncode != 0:
        return None
    version = result.stdout.strip()
    return version or None


def query_image_ids(services: Sequence[str]) -> dict[str, str | None]:
    """Resolve each backend service's built image id (``None`` if not built)."""

    ids: dict[str, str | None] = {}
    for service in services:
        result = _run_compose(["images", "-q", service])
        image_id = result.stdout.strip().splitlines()
        ids[service] = image_id[0] if result.returncode == 0 and image_id else None
    return ids


def query_worker_health() -> WorkerHealth:
    """Ping the Celery worker over the internal network via ``compose exec``.

    Runs the same ``celery -A app.worker:celery_app inspect ping`` the compose
    healthcheck uses, so a stopped or unhealthy worker is caught here rather than
    surfacing later as stuck estimator jobs. Any failure (container down, no
    reply) resolves to an unhealthy result — the smoke never mutates the stack.
    """

    result = _run_compose(
        [
            "exec",
            "-T",
            "worker",
            ".venv/bin/celery",
            "-A",
            "app.worker:celery_app",
            "inspect",
            "ping",
        ]
    )
    return worker_health_from_ping(result.returncode, result.stdout, result.stderr)


def probe_http(url: str) -> HttpProbe:
    """GET ``url`` and capture status/body without raising on HTTP errors."""

    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 — fixed http URL
            body = resp.read().decode("utf-8", errors="replace")
            return HttpProbe(url, resp.status, body, None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return HttpProbe(url, exc.code, body, None)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return HttpProbe(url, None, None, str(exc))


# --------------------------------------------------------------------------- #
# Report assembly.
# --------------------------------------------------------------------------- #


def _emit(line: str = "") -> None:
    print(line)


def _probe_and_report_health(sim_url: str) -> bool:
    """Probe the API health endpoints, print each result, and return overall ok."""

    ok = True
    _emit("")
    for path in ("/healthz", "/readyz", "/healthz/sources"):
        probe = probe_http(f"{sim_url}{path}")
        status = probe.status if probe.status is not None else (probe.error or "no response")
        _emit(f"[{'OK ' if probe.ok else 'FAIL'}] GET {path} -> {status}")
        ok = ok and probe.ok
        if path == "/healthz/sources" and probe.ok and probe.body is not None:
            try:
                payload = loads(probe.body)
            except JSONDecodeError:
                _emit("     (could not parse sources payload)")
            else:
                for line in summarize_sources(payload):
                    _emit(f"     - {line}")
    return ok


def run() -> int:
    """Assemble and print the readiness report; return a shell exit code."""

    _emit("Fatty local v1 simulator-readiness smoke (FTY-250)")
    _emit("=" * 52)

    env_text = read_env_file()
    if env_text is None:
        _emit("FAIL: no .env at repo root. Run `cp .env.example .env` first.")
        return 1
    env = parse_env(env_text)

    try:
        api_port = parse_api_port(env)
    except ValueError as exc:
        _emit(f"FAIL: {exc}")
        return 1
    sim_url = simulator_url(api_port)

    ok = True

    # 1. Backend image coherence.
    coherence = ImageCoherence(query_image_ids(BACKEND_IMAGE_SERVICES))
    _emit("")
    _emit(f"[{'OK ' if coherence.coherent else 'FAIL'}] images: {coherence.message}")
    ok = ok and coherence.coherent

    # 2. Alembic drift.
    alembic = AlembicStatus(query_db_alembic_version(env), code_head_revision())
    _emit(f"[{'OK ' if alembic.at_head else 'FAIL'}] alembic: {alembic.message}")
    ok = ok and alembic.at_head

    # 3. API health probes.
    ok = _probe_and_report_health(sim_url) and ok

    # 4. Worker health. The HTTP probes only reach the API; a stopped or wedged
    #    worker would leave estimator jobs stuck later, so require a live pong.
    worker = query_worker_health()
    _emit("")
    _emit(f"[{'OK ' if worker.healthy else 'FAIL'}] worker: {worker.message}")
    ok = ok and worker.healthy

    # 5. Non-secret config surface (active providers) and the connect URL.
    _emit("")
    _emit("config (non-secret):")
    for key, value in reported_env(env):
        _emit(f"     {key}={value or '(unset)'}")

    _emit("")
    _emit(f"Simulator connect URL: {sim_url}")
    _emit("  Enter this on the app's connect screen before signing in. A fresh")
    _emit("  simulator install has NO persisted server, so you must connect first.")

    if not ok:
        _emit("")
        _emit("NOT READY. Coherent fix path (run from the repo root):")
        _emit("  docker compose build api worker migrate   # rebuild from this checkout")
        _emit("  docker compose run --rm migrate            # apply Alembic to head")
        _emit("  docker compose up -d api worker            # restart on the new image")
        _emit("Then re-run this smoke.")
        return 1

    _emit("")
    _emit("READY. Stack is coherent — launch the simulator and connect.")
    return 0


def main() -> None:
    """Console entry point (``python -m app.ops.sim_readiness``)."""

    sys.exit(run())


if __name__ == "__main__":
    main()
