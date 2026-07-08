# Contract: LLM Provider Adapter

## Purpose

Give the estimator pipeline one config-driven, provider-agnostic capability:
turn a prompt plus an output schema into a schema-validated object. A
self-hoster points Slacks at OpenAI, Anthropic, or any OpenAI-compatible endpoint
through environment variables; consuming code (FTY-042) depends only on this
interface, never on a concrete provider or SDK. This is the transport contract,
not the estimator's parse logic.

## Owner

estimator lane (`backend/app/llm/`).

## Version

5 (OpenRouter structured-output routing guard added in FTY-291; keyless
`openai_compatible` path added in FTY-089; `claude_code` subscription provider
added in FTY-087; image input added in FTY-076; v1 introduced in FTY-041). v5 is
**backward-compatible**: keyed OpenRouter is supported through the existing
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
| `FATTY_LLM_PROVIDER` | `fake` | One of `openai`, `anthropic`, `openai_compatible`, `claude_code`, `fake`. |
| `FATTY_LLM_API_KEY` | _(none)_ | Required for `openai`/`anthropic`. **Optional for `openai_compatible`** — omit it for keyless local endpoints (Ollama/LM Studio/vLLM); set it for keyed remote endpoints such as OpenRouter or Together. When absent no `Authorization` header is sent. **Not required (and unused) for `claude_code`** — it authenticates via the local Claude Code session. Secret; env/secret-manager only. |
| `FATTY_LLM_MODEL` | _(empty)_ | Required for `openai`/`anthropic`/`openai_compatible` (e.g. `gpt-4o-mini`, `claude-3-5-sonnet`, `deepseek/deepseek-v4-pro`). **Optional for `claude_code`** — Claude Code picks the model from the session/plan; a supplied value is passed through to the invocation. |
| `FATTY_LLM_BASE_URL` | provider default | Required for `openai_compatible`; overrides the default OpenAI/Anthropic base. Use `https://openrouter.ai/api/v1` for OpenRouter. |
| `FATTY_LLM_TIMEOUT_SECONDS` | `30` | Per-attempt wall-clock timeout (0–600). Tunable. |
| `FATTY_LLM_MAX_RETRIES` | `2` | Additional attempts after the first, on transient failures only (0–10). Tunable. |
| `FATTY_LLM_SUPPORTS_VISION` | `false` | Declares the configured model as vision-capable. Required to be `true` before `images` may be supplied; otherwise image input fails fast. |

Invalid or inconsistent configuration fails fast at load with a `ValidationError`:
`openai`/`anthropic` without a key or model; `openai_compatible` without a base URL
or model (the key is optional for `openai_compatible` — a keyless local endpoint is
the intended use case). `claude_code` requires neither a key nor a model.

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
- Per-provider structured-output mechanics (OpenAI JSON-schema `response_format`
  vs. Anthropic forced tool use) and multimodal mechanics (OpenAI `image_url`
  content parts vs. Anthropic base64 `image` blocks) are implementation details
  behind the contract.
