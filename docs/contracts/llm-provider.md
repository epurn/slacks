# Contract: LLM Provider Adapter

## Purpose

Give the estimator pipeline one config-driven, provider-agnostic capability:
turn a prompt plus an output schema into a schema-validated object. A
self-hoster points Slacks at OpenAI, Anthropic, OpenAI-compatible endpoints,
Claude Code, or Codex through environment variables; consuming code (FTY-042)
depends only on this interface, never on a concrete provider or SDK. This is the
transport contract, not the estimator's parse logic.

## Owner

estimator lane (`backend/app/llm/`).

## Version

6 (Codex CLI subprocess provider contract added in FTY-293; OpenRouter
structured-output routing guard added in FTY-291; keyless `openai_compatible`
path added in FTY-089; `claude_code` subscription provider added in FTY-087;
image input added in FTY-076; v1 introduced in FTY-041). v6 is
**backward-compatible**: `codex` is a new opt-in provider selector that uses the
first-party Codex CLI in non-interactive mode. The existing `openai`,
`anthropic`, `openai_compatible`, `claude_code`, and `fake` selectors are
unchanged. Keyed OpenRouter remains supported through the existing
`openai_compatible` selector and env vars. When the configured base URL is
`https://openrouter.ai/api/v1`, structured-output requests include OpenRouter's
non-secret `provider.require_parameters=true` routing preference so OpenRouter
routes only to endpoints that support the requested `response_format`.

## Inputs

```
structured_completion(
    prompt: str,
    schema: type[BaseModel],
    *,
    images: Sequence[ImageInput] | None = None,
) -> BaseModel
```

- `prompt` — the instruction text. Treated as carrying personal context: never
  logged, never placed in error messages.
- `schema` — a Pydantic model type. It carries the JSON Schema sent to the
  provider's structured-output mechanism (`schema.model_json_schema()`) and
  validates the response. Expressing the schema as a Pydantic model keeps "the
  JSON schema" and "the validator" the same artifact.
- `images` *(v2, optional)* — zero or more `ImageInput` values sent alongside
  the prompt so a vision-capable model can extract structured output from an
  image. Defaults to `None`; **the text-only call is byte-for-byte unchanged**
  (no image content is added to the request when `images` is `None` or empty).
  Each `ImageInput` carries raw image `data: bytes` and an `media_type` (one of
  `image/jpeg`, `image/png`, `image/webp`, `image/gif`); an unsupported media
  type or empty data fails fast with `LLMConfigurationError`. Images are
  **untrusted input** — data, not instructions: any output a model derives from
  an image is trusted only after it validates against `schema`, exactly as for
  text. Images are never logged.

Supplying `images` requires a **vision-capable configured model**
(`FATTY_LLM_SUPPORTS_VISION=true`). If an image is supplied to a non-vision
model the call fails fast with `LLMConfigurationError` **before any provider
call**, so an image is never sent to a model that cannot read it. Per-provider
multimodal mechanics (OpenAI `image_url` data-URL content parts vs. Anthropic
base64 `image` blocks) are implementation details behind the interface.

Provider configuration is read from `FATTY_LLM_`-prefixed environment variables:

| Variable | Default | Notes |
| --- | --- | --- |
| `FATTY_LLM_PROVIDER` | `fake` | One of `openai`, `anthropic`, `openai_compatible`, `claude_code`, `codex`, `fake`. |
| `FATTY_LLM_API_KEY` | _(none)_ | Required for `openai`/`anthropic`. **Optional for `openai_compatible`** — omit it for keyless local endpoints (Ollama/LM Studio/vLLM); set it for keyed remote endpoints such as OpenRouter or Together. When absent no `Authorization` header is sent. **Not required (and unused) for `claude_code`** — it authenticates via the local Claude Code session. **Optional for `codex`** — when absent, Codex CLI uses saved auth under `CODEX_HOME`; when present, Slacks may pass it to only the `codex exec` child as `CODEX_API_KEY`. Secret; env/secret-manager only. |
| `FATTY_LLM_MODEL` | _(empty)_ | Required for `openai`/`anthropic`/`openai_compatible` (e.g. `gpt-4o-mini`, `claude-3-5-sonnet`, `deepseek/deepseek-v4-pro`). **Optional for `claude_code`** — Claude Code picks the model from the session/plan; a supplied value is passed through to the invocation. **Optional for `codex`** — a supplied value is passed as `--model`; when omitted, Codex uses its configured/default local model. Prefer setting an explicit supported model for reproducible deployments. |
| `FATTY_LLM_BASE_URL` | provider default | Required for `openai_compatible`; overrides the default OpenAI/Anthropic base. Use `https://openrouter.ai/api/v1` for OpenRouter. **Not used by `codex`**; direct OpenAI API base URL overrides, OpenRouter, and local OpenAI-compatible runtimes remain the `openai` / `openai_compatible` paths. |
| `FATTY_LLM_TIMEOUT_SECONDS` | `30` | Per-attempt wall-clock timeout (0–600). Tunable. |
| `FATTY_LLM_MAX_RETRIES` | `2` | Additional attempts after the first, on transient failures only (0–10). Tunable. |
| `FATTY_LLM_SUPPORTS_VISION` | `false` | Declares the configured model as vision-capable. Required to be `true` before `images` may be supplied; otherwise image input fails fast. |

Invalid or inconsistent configuration fails fast at load with a `ValidationError`:
`openai`/`anthropic` without a key or model; `openai_compatible` without a base URL
or model (the key is optional for `openai_compatible` — a keyless local endpoint is
the intended use case). `claude_code` requires neither a key nor a model. `codex`
requires neither a Slacks key nor a Slacks model; unusable Codex auth is detected
by the provider invocation and surfaced as `LLMConfigurationError`.

### `openai_compatible` keyless (local / LAN — zero per-token cost)

`FATTY_LLM_PROVIDER=openai_compatible` with no `FATTY_LLM_API_KEY` is the
intended path for a **local or LAN model runtime** — Ollama, LM Studio, or vLLM.
These runtimes expose the OpenAI Chat Completions wire format locally and require no
authentication. Set `FATTY_LLM_BASE_URL` to your runtime's endpoint (e.g.
`http://localhost:11434/v1` for Ollama) and `FATTY_LLM_MODEL` to the loaded model
name; leave `FATTY_LLM_API_KEY` unset. The adapter sends no `Authorization` header.

The existing base-URL scheme expectations (SSRF/egress posture) are unchanged;
keyless only affects whether an `Authorization` header is emitted — it does not
relax which URLs are reachable.

### `openai_compatible` keyed OpenRouter

OpenRouter is supported as a keyed `openai_compatible` endpoint:

```
FATTY_LLM_PROVIDER=openai_compatible
FATTY_LLM_BASE_URL=https://openrouter.ai/api/v1
FATTY_LLM_MODEL=deepseek/deepseek-v4-pro
FATTY_LLM_API_KEY=<openrouter key>
```

`deepseek/deepseek-v4-pro` is the intended local dogfooding choice at the time
of FTY-291, but the model slug is operator-tunable. The selected OpenRouter
model and routed provider must support JSON-schema structured outputs for the
adapter contract to hold. For OpenRouter only, the adapter adds
`provider: {"require_parameters": true}` whenever it sends the JSON-schema
`response_format`; this is not sent to OpenAI, Ollama, LM Studio, vLLM,
Together, or arbitrary OpenAI-compatible endpoints.

Optional live smoke, skipped without a key:

```
cd backend
FATTY_OPENROUTER_SMOKE_API_KEY=<openrouter key> \
  uv run pytest tests/llm/test_openrouter_smoke.py
```

The smoke uses a neutral synthetic prompt and tiny schema; it never sends diary
text. `FATTY_OPENROUTER_SMOKE_MODEL` may override the default
`deepseek/deepseek-v4-pro`.

### `claude_code` (subscription, no per-token billing)

`FATTY_LLM_PROVIDER=claude_code` runs the estimator through a **locally installed,
first-party Claude Code** session in headless mode. A self-hoster who already pays
for a Claude monthly plan pays nothing per token.

- **No `FATTY_LLM_API_KEY`.** Claude Code owns its own authentication
  (`claude login`); Slacks supplies no key and stores, reads, or logs **no**
  operator credential. A supplied key is ignored.
- **`FATTY_LLM_MODEL` is optional.** Claude Code selects the model from the active
  session/plan when the value is empty; a supplied model is passed through
  (`--model`).
- **All tools disabled / sandboxed.** The invocation runs with every Claude Code
  tool turned off (no bash, file, or web/fetch) and no MCP servers, so a
  prompt-injection in untrusted food-log text cannot trigger tool use, file
  access, or code execution on the host. The only network performed is Claude
  Code's own model call.
- **Trust boundary is identical.** Claude Code output is an untrusted analyst's
  output, returned only after it validates against the caller's schema.
- `FATTY_LLM_TIMEOUT_SECONDS` and `FATTY_LLM_MAX_RETRIES` apply unchanged.
- Operator setup, installation, and health diagnostics are out of scope here
  (tracked separately); image input is **not** supported via `claude_code`.

### `codex` (first-party Codex CLI subprocess)

`FATTY_LLM_PROVIDER=codex` runs the estimator through a **locally installed,
first-party Codex CLI** subprocess using documented `codex exec`
non-interactive mode and JSON Schema structured output. This is not the OpenAI
API provider, not an OpenAI-compatible HTTP endpoint, not OpenRouter, not a
keyless local OpenAI-compatible runtime, not Codex CLI's `--oss` local-provider
mode, and not `claude_code`.

- **Auth is owned by Codex CLI.** `FATTY_LLM_API_KEY` is optional. When it is
  absent, the provider uses Codex CLI's normal saved auth under `CODEX_HOME`
  (for example an operator-run `codex login`, browser/device auth, or
  `codex login --with-access-token`). `CODEX_ACCESS_TOKEN` is an operator setup
  path for seeding Codex auth into `CODEX_HOME`; it is not a new Slacks secret
  field.
- **Child-only API key handling.** When `FATTY_LLM_API_KEY` is configured for
  `codex`, the adapter may expose it only to the `codex exec` child process as
  `CODEX_API_KEY` for that invocation. It must never appear in argv, logs,
  client responses, persisted config, transcripts, or any non-Codex subprocess
  environment.
- **Model selection.** `FATTY_LLM_MODEL` is optional. When set, the adapter
  passes it as `--model`. When omitted, Codex uses the configured/default local
  model available to that Codex installation. Operators should set an explicit
  supported model for reproducible self-hosted deployments. This contract adds no
  Slacks reasoning/config env var; any future reasoning or Codex tuning belongs
  to provider-owned Codex setup and must preserve the safe invocation boundary
  below.
- **No base URL.** `FATTY_LLM_BASE_URL` is ignored by `codex`. Direct OpenAI API
  calls still use `FATTY_LLM_PROVIDER=openai`; OpenRouter, Ollama, LM Studio,
  vLLM, Together, and other OpenAI-compatible HTTP runtimes still use
  `FATTY_LLM_PROVIDER=openai_compatible`.
- **Safe subprocess boundary.** The adapter must run `codex exec` from a
  dedicated empty working directory, not the Slacks repository, and use the
  `--skip-git-repo-check` path when needed for that one-off directory. The prompt
  is supplied over stdin (`codex exec -` style), never argv. The requested schema
  is supplied through a temporary JSON Schema file passed with `--output-schema`.
  Runs are ephemeral (`--ephemeral`) with no persisted prompt/output transcripts.
  Web search is disabled (for example `-c 'web_search="disabled"'`), and the
  invocation must avoid user/project config, rules, profiles, MCP servers, and
  project instructions that could turn untrusted food text into tool use, repo or
  file inspection, web fetches, or approval prompts. Use `--ignore-rules` and
  the strongest current Codex CLI config-isolation flags that still allow the
  selected authentication path. If a CLI version cannot prevent unsafe config,
  MCP, rules, or web-search behavior for this non-interactive use, the adapter
  fails closed with `LLMConfigurationError`.
- **Sandbox and approvals.** The invocation runs with `--sandbox read-only` and
  `--ask-for-approval never` (or exact current equivalents) so model-generated
  command/file/tool attempts cannot modify host state and cannot pause for human
  approval. Do not use `--yolo`, `--full-auto`, workspace-write, full-access, or
  any approval mode that can broaden the trust boundary.
- **Trust boundary is identical.** Codex output is an untrusted analyst result.
  Slacks trusts it only after local JSON parsing and Pydantic validation against
  the caller's requested schema. Codex must not receive user profile, goal, or
  body-metric context beyond the prompt the estimator already sends to every
  provider.
- **Images.** When `FATTY_LLM_SUPPORTS_VISION=true`, `codex` must support the
  existing `images` argument by writing image bytes to temporary files and
  attaching them to the initial prompt through Codex CLI image attachments
  (`--image` / `-i`). Codex support is contracted for `image/jpeg` and
  `image/png` only. Until Codex CLI support for WebP and GIF is explicitly
  established and this contract is updated, `image/webp` and `image/gif` fail
  fast for `codex` with a content-free `LLMConfigurationError` before any child
  process is spawned. Text-only calls remain unchanged.
- **No retained content.** Temporary prompt, schema, output, and image files are
  created only for the invocation, are not placed under the Slacks repository or
  long-lived Codex session storage, and are removed after use. The adapter never
  logs prompt text, image bytes/paths, raw stdout, raw stderr, raw final output,
  keys, auth tokens, or CODEX_HOME contents.

## Outputs

A validated instance of the supplied schema. Output is never returned to callers
unless it validates — the LLM is an untrusted analyst and validation is the
trust boundary.

## Validation

- The provider response is JSON-parsed, then validated with the Pydantic schema.
- Schema-invalid output is rejected with `StructuredOutputValidationError` and
  never returned as trusted. Validation failure is terminal (not retried), so
  the rejection is deterministic.

## Authorization

Provider keys are read from the environment only, never exposed to clients and
never returned in responses. No bundled default key or default hosted provider.

## Privacy and Retention

- Keys, prompts, **images**, and raw responses are never logged. Logs carry only
  the provider label, attempt number, outcome, and (on validation failure) an
  error count. Schema-validation failures suppress the raw Pydantic validation
  details from the raised exception chain because rejected output may echo
  personal context.
- Local subprocess providers also suppress raw stdout, raw stderr, command-line
  prompt content, temporary file paths that may reveal user content, saved-auth
  paths, keys, auth tokens, and provider transcripts from logs, client responses,
  and exception chains.
- Transport errors carry content-free messages and suppress the original
  exception chain so request URLs/bodies (which in v2 may include encoded image
  data) cannot leak into traces.

## Errors

| Error | Meaning | Retryable |
| --- | --- | --- |
| `LLMConfigurationError` | Misconfiguration (no key, bad base URL scheme, image input with a non-vision model, or an unsupported image media type). | No |
| `LLMTransientError` | Timeout, connection failure, provider `5xx`, or rate-limit / retry signals (`429`, `408`, `425`). | Yes (bounded, with jittered exponential backoff) |
| `LLMResponseError` | Other `4xx` (auth, bad-request, not-found), non-JSON body, or missing expected fields. | No |
| `StructuredOutputValidationError` | Response failed schema validation. | No |

For `codex`, missing `codex` binary, missing/unusable saved auth or child
`CODEX_API_KEY`, unsafe CLI/config isolation, and unsupported image media types
map to `LLMConfigurationError`. Timeout, process-spawn hiccups, rate-limit or
overload signals, and other transient CLI/provider failures map to
`LLMTransientError`. A non-zero non-transient exit, non-JSON stdout, or malformed
final output maps to `LLMResponseError`. A JSON object that parses but fails the
requested Pydantic schema maps to `StructuredOutputValidationError`. All
diagnostics remain content-free: no raw prompt, image data, stdout, stderr,
schema-invalid output, key, auth token, or saved-auth material may be included.

Transient errors are retried up to `FATTY_LLM_MAX_RETRIES` additional attempts
with a short jittered exponential backoff between each attempt (base 0.5 s, cap
8 s, full-jitter). Once the retry budget is exhausted the last transient error
propagates.

## Examples

```python
from pydantic import BaseModel
from app.llm import ImageInput, build_provider, load_llm_settings

class Candidate(BaseModel):
    name: str
    calories: int

provider = build_provider(load_llm_settings())

# Text-only (v1, unchanged):
result = provider.structured_completion("one medium apple", Candidate)
# result is a validated Candidate, or an LLM* error was raised.

# With an image (v2 — requires FATTY_LLM_SUPPORTS_VISION=true):
image = ImageInput(data=jpeg_bytes, media_type="image/jpeg")
result = provider.structured_completion(
    "extract the nutrition facts", Candidate, images=[image]
)
# Same trust boundary: the result is validated against Candidate before return.
```

## Migration / Compatibility

- The `FATTY_LLM_` variable names are a self-host contract (FTY-072 docs).
- The `structured_completion(prompt, schema) -> validated object` signature is
  the estimator contract consumed by FTY-042.
- **v2 is backward-compatible.** `images` is a keyword-only argument defaulting
  to `None`; existing text-only callers (FTY-042) are unaffected and their
  requests are byte-for-byte identical. The new `FATTY_LLM_SUPPORTS_VISION`
  variable defaults to `false`, so existing deployments behave exactly as in v1.
- Adding a provider means adding an adapter behind the same interface; the
  signature and env-var contract stay stable.
- **v3 is backward-compatible.** `claude_code` is a new opt-in
  `FATTY_LLM_PROVIDER` value; the existing providers, every `FATTY_LLM_*`
  variable, and the `structured_completion` signature are unchanged. The only
  relaxation is scoped to `claude_code`: it needs no key and its model is
  optional.
- **v4 is backward-compatible.** `FATTY_LLM_API_KEY` becomes optional for
  `openai_compatible` only (keyless local endpoints — Ollama/LM Studio/vLLM).
  `openai` and `anthropic` still require a key; `openai_compatible` still requires
  `FATTY_LLM_BASE_URL` and `FATTY_LLM_MODEL`; all other variables and the
  `structured_completion` signature are unchanged. A keyed `openai_compatible`
  deployment continues to work exactly as in v3.
- **v5 is backward-compatible.** OpenRouter remains an `openai_compatible`
  endpoint using the existing `FATTY_LLM_*` variables. The only wire difference
  is host-scoped: when `FATTY_LLM_BASE_URL` is exactly the OpenRouter API root
  (`https://openrouter.ai/api/v1`, trailing slash ignored), structured-output
  requests include the OpenRouter `provider.require_parameters=true` routing
  preference. Non-OpenRouter endpoints receive the same request shape as v4.
- **v6 is backward-compatible.** `codex` is a new opt-in `FATTY_LLM_PROVIDER`
  value. Existing `openai`, `anthropic`, `openai_compatible`, `claude_code`, and
  `fake` behavior is unchanged. `codex` adds its own optional
  `FATTY_LLM_API_KEY` and optional `FATTY_LLM_MODEL` semantics, and it is the
  only provider that ignores `FATTY_LLM_BASE_URL`. OpenAI API calls, keyed
  OpenRouter, keyless local OpenAI-compatible runtimes, and Claude Code keep
  their existing selectors and setup paths.
- Per-provider structured-output mechanics (OpenAI JSON-schema `response_format`
  vs. Anthropic forced tool use vs. Codex CLI `--output-schema`) and multimodal
  mechanics (OpenAI `image_url` content parts vs. Anthropic base64 `image` blocks
  vs. Codex CLI `--image` attachments) are implementation details behind the
  contract.
