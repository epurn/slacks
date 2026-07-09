# Estimate-First Representative Corpus

This fixture is synthetic and public. It contains no private dogfood logs, real
provider output, tokens, or nutrition-history data.

`corpus.json` drives the FTY-302 regression harness:

- every case declares expected terminal behavior for `estimate_first`,
  `balanced`, and `strict`;
- provider replies are scripted through the in-memory fake provider;
- external nutrition/search/fetch seams are faked and never open sockets;
- rough nutrition facts are synthetic and deliberately labelled as model-prior
  estimates.

## Optional Live-Provider Smoke

The live smoke is skipped by default and is never required by CI. It sends only
the synthetic cases marked `"smoke": true` through the configured live parse
provider, with network-free nutrition/search/fetch seams.

Example operator command:

```sh
cd backend
FATTY_ESTIMATE_FIRST_LIVE_SMOKE=1 \
FATTY_ESTIMATE_FIRST_LIVE_SMOKE_SUMMARY=/tmp/estimate-first-smoke.json \
FATTY_LLM_PROVIDER=openai \
FATTY_LLM_MODEL=<structured-output-capable-model> \
FATTY_LLM_API_KEY=<provider-key> \
uv run pytest tests/test_estimate_first_live_provider_smoke.py
```

The optional summary contains only case ids, expected statuses, actual statuses,
and pass/fail booleans. It does not record raw provider output, prompts, keys, or
private user data.
