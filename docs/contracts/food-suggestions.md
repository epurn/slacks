# Contract: Food Suggestions

## Purpose

Define the read-only contextual quick-add suggestions endpoint (FTY-340). A
signed-in user can ask "what food do I probably mean to log right now?" and get a
small ranked list derived only from their own saved foods and completed food-log
history. The ranking is deterministic, explainable, time-aware, and local to the
process: no LLM call, network fetch, provider request, or cross-user aggregation
is involved.

This contract covers:

1. the `GET /api/food-suggestions` request and response shape;
2. the candidate pool from saved foods, aliases, and completed resolved food
   history;
3. the contextual frecency scoring model and tuning constants;
4. deduplication and deterministic tie-break rules;
5. privacy, authorization, and bounded-work rules.

Out of scope: mobile UI, estimator execution, migrations, feedback loops such as
dismissals or pins, collaborative filtering, and writes of any kind.

## Owner

backend-core / contracts lane:
`backend/app/routers/food_suggestions.py`,
`backend/app/schemas/food_suggestions.py`, and
`backend/app/services/food_suggestions.py`.

## Version

1 (FTY-340).

## Inputs

```
GET /api/food-suggestions?limit=8
Authorization: Bearer <token>
```

The route is scoped by the bearer token's authenticated user; there is no
client-supplied user id.

| Param | Type | Meaning |
| --- | --- | --- |
| `limit` | integer | Optional. Defaults to `8`; minimum `1`; maximum `20`. Values above `20` return `422`. |

The request time is resolved server-side in the user's profile timezone. The
clock is injectable at the route boundary so tests pin exact moments; the scoring
service does not read the wall clock.

## Outputs

Response:

```json
{
  "items": [
    {
      "label": "Greek Yogurt",
      "submit_phrase": "yogurt cup",
      "saved_food_id": "4d0b6c2a-6b2d-4d3e-8e11-86c1d8e8235f",
      "score": 2.4137
    }
  ],
  "limit": 8
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `label` | string | Display label for the suggestion. Saved-food identity wins when present; otherwise the history label is used. |
| `submit_phrase` | string | Phrase the client may submit into the logging flow. Saved foods use their earliest alias when present; history-only candidates use their label. |
| `saved_food_id` | UUID \| null | Present when the suggestion maps to a saved food and the client may use the estimator-skip path. |
| `score` | number | The raw ranking score rounded to 4 decimals for debugging. Clients should treat list order as canonical. |

`items` is sorted by descending unrounded score and capped at the applied
`limit`.

## Candidate Pool

Candidates are loaded from the authenticated user's own rows only:

- `saved_foods` plus their `food_aliases`;
- resolved `derived_food_items` whose owning `log_events` row is `completed`,
  live (`voided_at IS NULL`), and within the history window.

The history window is bounded to the last **120 days** from the request instant in
the user's profile timezone. Older rows are not read for this endpoint.

Saved foods are candidates in their own right using the saved-food `created_at`
as an occurrence. Matching history rows add occurrences to that saved-food
candidate instead of creating duplicates. A history label matches a saved food
when its normalized label equals the saved food's normalized name or any of that
saved food's normalized aliases. The normalization rule is the existing
`normalize_text` function documented by `saved-foods.md`: NFKD, strip
diacritics, casefold, collapse whitespace.

History-only candidates are distinct by normalized label.

## Scoring Model

Each candidate's score is the sum over its occurrences:

```
recency_decay * hour_kernel * day_type_weight
```

The implementation constants are named in
`backend/app/services/food_suggestions.py` and have these v1 defaults:

| Constant | Value | Meaning |
| --- | ---: | --- |
| `HISTORY_WINDOW_DAYS` | `120` | Maximum age of log-history rows read. |
| `RECENCY_HALF_LIFE_DAYS` | `14.0` | Exponential half-life for frecency decay. |
| `HOUR_KERNEL_FULL_WEIGHT_MINUTES` | `90` | Occurrences within ±90 minutes of the request local time get full hour weight. |
| `HOUR_KERNEL_FLOOR_DISTANCE_MINUTES` | `240` | By ±4 hours the hour kernel reaches its floor. |
| `HOUR_KERNEL_FLOOR` | `0.15` | Off-hour occurrence floor so strong all-day favorites can still appear. |
| `DAY_TYPE_SMOOTHING` | `2.0` | Additive smoothing for weekday/weekend affinity. |
| `SCORE_DECIMAL_PLACES` | `4` | Response score rounding only; sorting uses unrounded values. |

`recency_decay` is exponential:

```
0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
```

Future timestamps are treated as age zero.

`hour_kernel` uses circular local-clock distance, so 23:30 and 00:30 are 60
minutes apart. The kernel is `1.0` inside ±90 minutes, linearly decays to
`HOUR_KERNEL_FLOOR` by ±240 minutes, and stays at that floor beyond ±240 minutes.

`day_type_weight` is candidate-level weekday/weekend affinity with Laplace
smoothing. For the request's day type:

```
((matching_occurrences + DAY_TYPE_SMOOTHING)
 / (total_occurrences + 2 * DAY_TYPE_SMOOTHING))
 / 0.5
```

Sparse history therefore trends toward `1.0` (plain frecency); repeated weekday
or weekend evidence can lift or lower a candidate for that request context.

## Tie-Breaks

Ordering is deterministic:

1. unrounded score descending;
2. most recent occurrence descending;
3. normalized label ascending;
4. saved food id string ascending, when present.

## Authorization and Privacy

The endpoint requires bearer authentication (`401` otherwise). All queries are
scoped to `current_user.id`; rows belonging to other users never participate in
the candidate pool, scoring, or response. A user with no saved-food or completed
history candidates receives `200` with an empty `items` list.

The endpoint is read-only and performs no egress: no LLM, provider, search,
fetch, telemetry enrichment, or collaborative filtering. Labels and phrases in
the response are the user's own saved or logged text and are not written to logs.

## Errors

| Condition | Result |
| --- | --- |
| Missing/invalid credentials | `401`. |
| `limit < 1` or `limit > 20` | `422`. |
| No candidates | `200 { "items": [], "limit": <applied> }`. |

## Tests

Covered by `backend/tests/test_food_suggestions.py` (time-shifted ranking,
recency/hour/day-type behavior, saved-food/history deduplication, tie-breaks,
empty result, limit validation, auth, owner scoping, and finalized-row filters)
and `backend/tests/test_food_suggestions_postgres.py` (opt-in Postgres parity
guard for the owner-scoped join and timezone-aware timestamp path).
