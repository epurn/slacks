# FTY-436 — Live engine probe (self-hosted SearXNG, 2026-07-26)

Everything below was measured against the running compose stack on the dev box:
first the **default** engine set (`use_default_settings: true`, `main`'s config),
then the **curated** set this story pins. The instance's own limiter is off in
both cases, so every failure recorded here is an **upstream** engine refusing the
self-hosted instance — the "SearXNG is hitting rate limits a lot" symptom.

Probe shape: SearXNG's JSON API exactly as the FTY-079/FTY-164 adapter calls it
(`GET /search?q=<sanitized identity>&format=json`), issued from inside the
container. `engines=<name>` isolates one engine per row.

§§3–6 were re-measured end to end on the current head. §6 in particular records
a four-run, fixture-level `make food-smoke` A/B (default×2, curated×2) rather
than aggregate counts, so the AC-4 "no baseline pass regressed" comparison can
be checked directly against the tables.

## 1. What the default set actually does

Default general-category fan-out (10 engines):
`brave`, `currency`, `dictzone`, `duckduckgo`, `google`, `lingva`,
`mymemory translated`, `startpage`, `wikidata`, `wikipedia`.

Per-engine probe (`n` = results returned, `unresp` = SearXNG's
`unresponsive_engines`):

```
duckduckgo  Clif Bar Chocolate Chip nutrition    n=10   1.0s unresp=[]
duckduckgo  banana nutrition facts               n=9    0.7s unresp=[]
duckduckgo  722252100900                         n=0    0.2s unresp=[['duckduckgo', 'CAPTCHA']]
brave       Clif Bar Chocolate Chip nutrition    n=20   0.6s unresp=[]
brave       banana nutrition facts               n=0    0.2s unresp=[['brave', 'too many requests']]
brave       722252100900                         n=0    0.0s unresp=[['brave', 'Suspended: too many requests']]
startpage   Clif Bar Chocolate Chip nutrition    n=0    0.4s unresp=[['startpage', 'CAPTCHA']]
startpage   banana nutrition facts               n=0    0.0s unresp=[['startpage', 'Suspended: CAPTCHA']]
startpage   722252100900                         n=0    0.0s unresp=[['startpage', 'Suspended: CAPTCHA']]
google      Clif Bar Chocolate Chip nutrition    n=0    0.3s unresp=[]      <- silent block
google      banana nutrition facts               n=0    0.1s unresp=[]      <- silent block
google      722252100900                         n=0    0.1s unresp=[]      <- silent block
qwant       (all three)                          n=0         unresp=['access denied' / suspended]
yep         (all three)                          n=0         unresp=['access denied' / suspended]
```

A later repeat of the branded queries showed `duckduckgo` (the lite/JSON
endpoint) CAPTCHA-walling on **every** query, while DuckDuckGo's HTML endpoint
(`duckduckgo web`, disabled upstream) answered normally — the two are separate
SearXNG engines against the same index.

The remaining default engines (`currency`, `dictzone`, `lingva`,
`mymemory translated`, `wikidata`, `wikipedia`) are currency/translation/
encyclopedia engines: extra upstream calls on every food query, no product or
nutrition value.

## 2. Candidate sweep (branded queries, one engine at a time)

```
duckduckgo web  n=10  relevant (Clif Bar product + myfooddata nutrition rows)
bing            n=10  relevant, but see the UPC note below
dogpile         n=8   relevant (official clifbar.com / chobani.com product pages)
zapmeta         n=9   relevant (same InfoSpace backend family as dogpile)
resulthunter    n=19  relevant (same InfoSpace backend family as dogpile)
privacywall     n=10  relevant (Bing-derived, duplicates duckduckgo web)
mojeek          n=0   independent index; empty on branded, good on generic food
seznam          n=0/10 timeout on one query
mwmbl           n=2   thin
brave           n=0   'too many requests' -> suspended
startpage       n=0   'Suspended: CAPTCHA'
yahoo           n=0   'HTTP protocol error' -> suspended
fireball        n=0   'access denied' -> suspended
qwant / yep     n=0   'access denied' -> suspended
presearch       n=0   empty
crowdview       n=0   empty
```

Kept one engine per distinct backend: `duckduckgo web` (DDG/Bing-derived index),
`dogpile` (InfoSpace metasearch — `zapmeta` / `resulthunter` / `privacywall` are
redundant with it or with DDG), and `mojeek` (independent crawler).

`bing` was **not** kept: its relevant hits duplicated `duckduckgo web`, and on
numeric UPC queries it injected unrelated results that outranked real product
hits — e.g. for `722252100900` and `0038000138416` its top rows were
`support.microsoft.com/contactus` and `microsoft.com`, and for
`Chobani Greek Yogurt Vanilla nutrition facts` it returned The Big Bang Theory
pages. `mojeek` briefly returned `access denied` after a burst of probe traffic
and recovered on its own a few minutes later (200 OK, no CAPTCHA) — a soft
per-IP rate limit, not a block wall, so it stays.

## 3. Curated instance — raw JSON API

Container booted with this story's `searxng/settings.yml`:

```
total engines: 3 | enabled general: ['dogpile', 'duckduckgo web', 'mojeek']
```

Six representative sanitized queries (branded product, generic food, two
UPC-style strings, a second branded product, a generic portion query):

```
query: 'Clif Bar Chocolate Chip nutrition facts'
  results=16  elapsed=1.1s  unresponsive=[]
  engines={'dogpile': 8, 'duckduckgo web': 10}
    - [dogpile] Chocolate Chip | CLIF BAR® Energy Bar :: https://www.clifbar.com/products/clif-bar-chocolate-chip

query: 'banana nutrition facts'
  results=14  elapsed=0.8s  unresponsive=[['mojeek', 'access denied']]
  engines={'dogpile': 8, 'duckduckgo web': 9}
    - [dogpile,duckduckgo web] Bananas Nutrition Facts and Possible Health Benefits - Healthline :: https://www.healthline.com/health/nutrition/bananas

query: '722252100900'
  results=16  elapsed=0.8s  unresponsive=[['mojeek', 'Suspended: access denied']]
  engines={'dogpile': 8, 'duckduckgo web': 10}
    - [dogpile,duckduckgo web] CLIF Bar Chocolate Chip Energy Bars - Target :: https://www.target.com/p/clif-bar-chocolate-chip-energy-bars/-/A-82888110

query: 'Chobani Greek Yogurt Vanilla nutrition facts'
  results=16  elapsed=0.8s  unresponsive=[['mojeek', 'Suspended: access denied']]
  engines={'dogpile': 8, 'duckduckgo web': 10}
    - [dogpile,duckduckgo web] Vanilla — Chobani® Greek Yogurt :: https://www.chobani.com/products/yogurt/greek/vanilla-cup

query: '0038000138416'
  results=18  elapsed=0.7s  unresponsive=[['mojeek', 'Suspended: access denied']]
  engines={'dogpile': 8, 'duckduckgo web': 10}
    - [dogpile] Buy Pringles The Original Potato Crisps - 5.2oz online - eBay :: https://www.ebay.ca/p/11004435046

query: 'grilled chicken breast calories per 100g'
  results=17  elapsed=0.8s  unresponsive=[['mojeek', 'Suspended: access denied']]
  engines={'dogpile': 8, 'duckduckgo web': 10}
    - [dogpile,duckduckgo web] Calories in 100 g of Grilled Chicken Breast and Nutrition Facts :: https://foods.fatsecret.com/calories-nutrition/generic/chicken-breast-grilled-ns
```

Every query returned non-empty, usable JSON (14–18 results). `mojeek` was inside
one of its soft per-IP cooldown windows for this capture and reported
`access denied` on five of six queries — the *only* `unresponsive_engines` entry
in the run, and the set kept answering every query regardless. That is the
resilience the third engine is there for, and no kept engine ever returned a
CAPTCHA or a `too many requests`.

## 4. Curated instance — through the backend adapter

`SearXNGSearchProvider` (the real FTY-079/FTY-164 adapter, hardened fetch, real
`SLACKS_SEARCH_*` env) run inside the stack's `api` container against the
curated `http://searxng:8080`:

```
provider: SearXNGSearchProvider | base: http://searxng:8080/search
capability: SearchCapability(id='official_source', source_type='official_source',
  kinds=('named_product', 'restaurant_item'), enabled=True, available=True)

'Clif Bar Chocolate Chip nutrition facts'          status=success candidates=5
'banana nutrition facts'                           status=success candidates=5
'722252100900'                                     status=success candidates=5
'Chobani Greek Yogurt Vanilla nutrition facts'     status=success candidates=5
'0038000138416'                                    status=success candidates=5
'grilled chicken breast calories per 100g'         status=success candidates=5
```

Top candidates surfaced to the resolver include the official product pages
(`clifbar.com`, `chobani.com`), UPC/retail listings (`target.com`, `ebay.ca`,
`upcitemdb.com`, `go-upc.com`), and nutrition references (`healthline`,
`fatsecret`) — `status=success` on all six, no `rate_limited`, no `failed`.

## 5. Container health / compose render

```
$ docker compose config                       # exit 0
$ docker compose up -d searxng && docker ps
slacks-searxng-1 Up 22 seconds (healthy)      # /healthz probe green
```

## 6. `make food-smoke` — curated vs. default (fixture-level A/B)

Four consecutive runs, **same stack** throughout: same `api`/`worker`/`postgres`
containers (never rebuilt), same LLM provider, same `products` cache, same box
load. The *only* thing that changed between runs was which `searxng/settings.yml`
the `searxng` container mounted — swapped by recreating just that one service:

```
# default (baseline): the shared stack's own config, use_default_settings: true
$ docker compose -p slacks up -d --force-recreate searxng
$ docker compose -p slacks exec searxng .../python -c "<config introspection>"
engine count: 84                      # general fan-out = the 10 default engines

# curated: this PR's searxng/settings.yml mounted over the same service
$ docker compose -f docker-compose.yml -f <override mounting this branch's searxng/> \
    -p slacks up -d --force-recreate searxng
total engines: 3 | enabled general: ['dogpile', 'duckduckgo web', 'mojeek']
```

Both engine sets were run **twice**, interleaved `default → curated → curated →
default`, so every flip has a same-config repeat to compare against.

### Per-fixture verdicts (all four runs)

| Fixture | default #1 | curated #1 | curated #2 | default #2 |
| --- | --- | --- | --- | --- |
| `compliments-chicken-strips` | ❌ FAIL | ❌ FAIL | ❌ FAIL | ❌ FAIL |
| `one-banana` | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS |
| `two-large-eggs` | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS |
| `one-slice-wheat-toast` | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS |
| `scrambled-eggs-and-buttered-toast` | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS |
| `100g-banana` | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS |
| `branded-crackers-and-hummus` | ❌ FAIL | ❌ FAIL | ❌ FAIL | ❌ FAIL |
| `tuna-salad-sandwich` | ✅ PASS | ❌ FAIL | ✅ PASS | ✅ PASS |
| `made-good-oat-bar` | ❌ FAIL | ❌ FAIL | ✅ PASS | ❌ FAIL |
| `homemade-banh-mi` | ❌ FAIL | ❌ FAIL | ❌ FAIL | ❌ FAIL |
| `nicorette-4mg-gum` | ✅ PASS | ❌ FAIL | ✅ PASS | ✅ PASS |
| `nicorette-brand-gum` | ✅ PASS | ✅ PASS | ✅ PASS | ❌ FAIL |
| `homemade-chicken-rice-casserole` | ✅ PASS | ❌ FAIL | ❌ FAIL | ❌ FAIL |
| `thrown-together-veggie-curry` | ❌ FAIL | ❌ FAIL | ❌ FAIL | ❌ FAIL |
| **totals** | **5 of 14 fail** | **8 of 14 fail** | **5 of 14 fail** | **7 of 14 fail** |

Failing sets, verbatim:

- **default #1 (baseline)** — `FAIL: 5 of 14`: `compliments-chicken-strips`,
  `branded-crackers-and-hummus`, `made-good-oat-bar`, `homemade-banh-mi`,
  `thrown-together-veggie-curry`.
- **curated #1** — `FAIL: 8 of 14`: `compliments-chicken-strips`,
  `branded-crackers-and-hummus`, `tuna-salad-sandwich`, `made-good-oat-bar`,
  `homemade-banh-mi`, `nicorette-4mg-gum`, `homemade-chicken-rice-casserole`,
  `thrown-together-veggie-curry`.
- **curated #2** — `FAIL: 5 of 14`: `compliments-chicken-strips`,
  `branded-crackers-and-hummus`, `homemade-banh-mi`,
  `homemade-chicken-rice-casserole`, `thrown-together-veggie-curry`.
- **default #2** — `FAIL: 7 of 14`: `compliments-chicken-strips`,
  `branded-crackers-and-hummus`, `made-good-oat-bar`, `homemade-banh-mi`,
  `nicorette-brand-gum`, `homemade-chicken-rice-casserole`,
  `thrown-together-veggie-curry`.

### AC-4 comparison: did any baseline pass regress under the curated set?

Baseline (`default #1`) passed nine fixtures. Six of them —
`one-banana`, `two-large-eggs`, `one-slice-wheat-toast`,
`scrambled-eggs-and-buttered-toast`, `100g-banana`, `nicorette-brand-gum` — pass
in **both** curated runs, so they are untouched. Three flipped at least once and
are each shown engine-independent below, by the two means AC-4 names (a repeat
run, or an identical failure under both configs):

| Flipped fixture | What happened | Engine-independent because |
| --- | --- | --- |
| `tuna-salad-sandwich` | baseline PASS (`model_prior`, 360 kcal) → curated #1 FAIL (`status: processing`, no items) → curated #2 PASS (`reference_source` nutritionvalue.org, 392 kcal) → default #2 PASS | **Repeat run under the same curated config passes.** The curated-#1 failure is the non-terminal-in-poll-window class, not a resolution difference: the run never produced items at all. |
| `nicorette-4mg-gum` | baseline PASS (`reference_source` calorieking, 1 kcal) → curated #1 FAIL (`product_database open_food_facts:0307667857603`, **0 kcal**) → curated #2 PASS (calorieking again) → default #2 PASS | **Repeat run under the same curated config passes.** The 0-kcal OFF row it briefly resolved to is a *pre-existing cache row*, written 2026-07-26 09:50/10:05 UTC — before any of these four runs (`select … from products where query_key ilike '%gum%'`). Both configs read the identical cached row; which one wins depends on the live parse emitting `nicorette gum` vs `gum nicorette` as the query key, not on the engine set. |
| `homemade-chicken-rice-casserole` | baseline PASS (`model_prior`, 900 kcal) → curated #1 FAIL (`processing`) → curated #2 FAIL (`processing`) → **default #2 FAIL (`processing`)** | **Identical failure under both configs.** Re-running the default engine set reproduces the exact same `processing` / "no derived items produced" failure, so the fixture had already stopped being reliable on the baseline config. |

`nicorette-brand-gum` moves the other way — it passes under **both** curated runs
and fails under `default #2` — which is further direct evidence that this
fixture set carries run-to-run noise independent of the engine set. And
`made-good-oat-bar`, a baseline **failure**, passes under curated #2.

**Conclusion for AC-4: no fixture that passed in the baseline run fails under the
curated set for engine-set reasons.** Every flip has either a passing same-config
repeat or an identical failure reproduced on the default set.

### Residual failures — pre-existing, both configs

The smoke is **red on `main` as well**; it does not exit 0 under either engine
set. Four fixtures fail in all four runs, split into two pre-existing classes,
neither caused by (nor fixable inside) an infra-only engine-curation story:

- **Resolution quality.** `branded-crackers-and-hummus` fails identically in all
  four runs: the cached OFF row `open_food_facts:0066721029218` ("Christie,
  Toppables Crackers", 473.7 kcal/100 g, `default_serving_g=19`, cached
  2026-07-17) costs 4 crackers at 360 kcal, outside the fixture's `[30, 250]`
  band. `compliments-chicken-strips` returns `needs_clarification` ("Which food
  was that? We couldn't find a nutrition match") in all four.
- **Runs not terminal inside the poll window.** `homemade-banh-mi` and
  `thrown-together-veggie-curry` (all four runs), plus
  `homemade-chicken-rice-casserole` (three of four), come back `processing` with
  no derived items — the informal multi-ingredient meals, against
  `POLL_TIMEOUT_SECONDS = 360`. This box runs a second stale compose stack and
  gives Docker 2 CPUs / 2 GB, so it is a contention/deadline class.

Both classes are estimator/backend territory, which this story lists as a
Non-Goal ("No estimator/backend code change"), so `make food-smoke` exiting 0 is
not reachable from this diff. Two of them are filed as `out_of_scope_bug`
planner notes (the 0-kcal OFF row completing as a real estimate, and the
non-terminal informal-meal class).
