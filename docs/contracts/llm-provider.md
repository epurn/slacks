# Contract: LLM Provider Adapter

## Purpose

Give the estimator pipeline one config-driven, provider-agnostic capability:
turn a prompt plus an output schema into a schema-validated object. A
self-hoster points Fatty at OpenAI, Anthropic, or any OpenAI-compatible endpoint
through environment variables; consuming code (FTY-042) depends only on this
interface, never on a concrete provider or SDK. This is the transport contract,
not the estimator's parse logic.

## Owner

estimator lane (`backend/app/llm/`).

## Version

1 (introduced in FTY-041).

## Inputs

`structured_completion(prompt: str, schema: type[BaseModel]) -> BaseModel`

- `prompt` — the instruction text. Treated as carrying personal context: never
  logged, never placed in error messages.
- `schema` — a Pydantic model type. It carries the JSON Schema sent to the
  provider's structured-output mechanism (`schema.model_json_schema()`) and
  validates the response. Expressing the schema as a Pydantic model keeps "the
  JSON schema" and "the validator" the same artifact.

Provider configuration is read from `FATTY_LLM_`-prefixed environment variables:

| Variable | Default | Notes |
| --- | --- | --- |
| `FATTY_LLM_PROVIDER` | `fake` | One of `openai`, `anthropic`, `openai_compatible`, `fake`. |
| `FATTY_LLM_API_KEY` | _(none)_ | Required for every non-`fake` provider. Secret; env/secret-manager only. |
| `FATTY_LLM_MODEL` | _(empty)_ | Required for every non-`fake` provider (e.g. `gpt-4o-mini`, `claude-3-5-sonnet`). |
| `FATTY_LLM_BASE_URL` | provider default | Required for `openai_compatible`; overrides the default OpenAI/Anthropic base. |
| `FATTY_LLM_TIMEOUT_SECONDS` | `30` | Per-attempt wall-clock timeout (0–600). Tunable. |
| `FATTY_LLM_MAX_RETRIES` | `2` | Additional attempts after the first, on transient failures only (0–10). Tunable. |

Invalid or inconsistent configuration (a real provider with no key/model, or
`openai_compatible` with no base URL) fails fast at load with a `ValidationError`.

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

- Keys, prompts, and raw responses are never logged. Logs carry only the
  provider label, attempt number, outcome, and (on validation failure) an error
  count.
- Transport errors carry content-free messages and suppress the original
  exception chain so request URLs/bodies cannot leak into traces.

## Errors

| Error | Meaning | Retryable |
| --- | --- | --- |
| `LLMConfigurationError` | Misconfiguration (no key, bad base URL scheme). | No |
| `LLMTransientError` | Timeout, connection failure, or provider `5xx`. | Yes (bounded) |
| `LLMResponseError` | `4xx`, non-JSON body, or missing expected fields. | No |
| `StructuredOutputValidationError` | Response failed schema validation. | No |

Transient errors are retried up to `FATTY_LLM_MAX_RETRIES` additional attempts;
once exhausted the last transient error propagates.

## Examples

```python
from pydantic import BaseModel
from app.llm import build_provider, load_llm_settings

class Candidate(BaseModel):
    name: str
    calories: int

provider = build_provider(load_llm_settings())
result = provider.structured_completion("one medium apple", Candidate)
# result is a validated Candidate, or an LLM* error was raised.
```

## Migration / Compatibility

- The `FATTY_LLM_` variable names are a self-host contract (FTY-072 docs).
- The `structured_completion(prompt, schema) -> validated object` signature is
  the estimator contract consumed by FTY-042.
- Adding a provider means adding an adapter behind the same interface; the
  signature and env-var contract stay stable.
- Per-provider structured-output mechanics (OpenAI JSON-schema `response_format`
  vs. Anthropic forced tool use) are implementation details behind the contract.
