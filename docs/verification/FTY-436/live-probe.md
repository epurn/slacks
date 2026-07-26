# FTY-436 — Live engine probe (self-hosted SearXNG, 2026-07-26)

Everything below was measured against the running compose stack on the dev box:
first the **default** engine set (`use_default_settings: true`, `main`'s config),
then the **curated** set this story pins. The instance's own limiter is off in
both cases, so every failure recorded here is an **upstream** engine refusing the
self-hosted instance — the "SearXNG is hitting rate limits a lot" symptom.

Probe shape: SearXNG's JSON API exactly as the FTY-079/FTY-164 adapter calls it
(`GET /search?q=<sanitized identity>&format=json`), issued from inside the
container. `engines=<name>` isolates one engine per row.

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
  results=17  elapsed=0.9s  unresponsive=[]
  engines={'dogpile': 8, 'duckduckgo web': 10}
    - [dogpile] Chocolate Chip | CLIF BAR® Energy Bar :: https://www.clifbar.com/products/clif-bar-chocolate-chip

query: 'banana nutrition facts'
  results=14  elapsed=0.6s  engines={'dogpile': 8, 'duckduckgo web': 9}
    - [dogpile,duckduckgo web] Bananas Nutrition Facts … :: https://www.healthline.com/health/nutrition/bananas

query: '722252100900'
  results=16  elapsed=0.6s  engines={'dogpile': 8, 'duckduckgo web': 10}
    - [dogpile,duckduckgo web] CLIF Bar Chocolate Chip Energy Bars - Target
    - [dogpile,duckduckgo web] UPC 722252100900 - Clif Bar Energy Bar … :: https://www.upcitemdb.com/upc/722252100900

query: 'Chobani Greek Yogurt Vanilla nutrition facts'
  results=13  elapsed=0.7s  engines={'dogpile': 8, 'duckduckgo web': 10}
    - [dogpile,duckduckgo web] Vanilla — Chobani® Greek Yogurt :: https://www.chobani.com/products/yogurt/greek/vanilla-cup

query: '0038000138416'
  results=18  elapsed=0.5s  engines={'dogpile': 8, 'duckduckgo web': 10}
    - [duckduckgo web] Pringles Original Potato Crisps Chips :: https://go-upc.com/search?q=38000138416

query: 'grilled chicken breast calories per 100g'
  results=17  elapsed=0.7s  engines={'dogpile': 8, 'duckduckgo web': 10}
    - [dogpile,duckduckgo web] Calories in 100 g of Grilled Chicken Breast … :: https://foods.fatsecret.com/…
```

Every query returned non-empty, usable JSON. The only `unresponsive_engines`
entry in the whole run was `mojeek` during its cooldown window (above); no
CAPTCHA and no `too many requests` from any kept engine.

## 4. Curated instance — through the backend adapter

`SearXNGSearchProvider` (the real FTY-079/FTY-164 adapter, hardened fetch, real
`SLACKS_SEARCH_*` env) run inside the stack's `api` container against the
curated `http://searxng:8080`:

```
provider: SearXNGSearchProvider | capability: SearchCapability(id='official_source',
  source_type='official_source', kinds=('named_product', 'restaurant_item'),
  enabled=True, available=True)

'Clif Bar Chocolate Chip nutrition facts'      status=success candidates=5
'banana nutrition facts'                       status=success candidates=5
'722252100900'                                 status=success candidates=5
'Chobani Greek Yogurt Vanilla nutrition facts' status=success candidates=5
'0038000138416'                                status=success candidates=5
'grilled chicken breast calories per 100g'     status=success candidates=5
```

Top candidates surfaced to the resolver include the official product pages
(`clifbar.com`, `chobani.com`), UPC databases (`upcitemdb.com`, `go-upc.com`),
and nutrition references (`myfooddata`, `fatsecret`, `nutritionvalue.org`) —
`status=success` on all six, no `rate_limited`, no `failed`.

## 5. Container health / compose render

```
$ docker compose config                       # exit 0
$ docker compose up -d searxng && docker ps
slacks-searxng-1 Up 20 seconds (healthy)      # /healthz probe green
```

## 6. `make food-smoke` — curated vs. default

Both runs used the same live stack, the same LLM provider, and the same
`products` cache; only the mounted `searxng/settings.yml` differed.

| Run | Engine set | Result |
| --- | --- | --- |
| baseline | default (inherit-all) | `FAIL: 7 of 14 fixtures regressed` |
| curated #1 | this story | `FAIL: 4 of 14 fixtures regressed` |
| curated #2 | this story | `FAIL: 5 of 14 fixtures regressed` |

The smoke is **red on `main` as well** — it does not exit 0 either way — and the
curated set is strictly the better of the two. The failures split into two
pre-existing classes, neither caused by (nor fixable inside) an infra-only
engine-curation story:

- **Resolution quality.** `branded-crackers-and-hummus` fails identically under
  both configs: the cached OFF row `open_food_facts:0066721029218`
  ("Christie, Toppables Crackers", 473.7 kcal/100 g, `default_serving_g=19`,
  cached 2026-07-17) costs 4 crackers at 360 kcal, outside the fixture's
  `[30, 250]` band. `made-good-oat-bar` and `tuna-salad-sandwich` flip between
  `model_prior` and a real product/reference source across runs, and land outside
  their bands when they take the `model_prior` path.
- **Runs not terminal inside the poll window.** `homemade-banh-mi`,
  `homemade-chicken-rice-casserole`, and `thrown-together-veggie-curry` come back
  `processing`/`pending` — the run-deadline/box-contention class (this box runs a
  second stale compose stack and has 2 CPUs / 2 GB for Docker). The curated set
  reduces how often this happens (7 → 4/5 failures) because fewer upstream calls
  time out, but does not eliminate it.

Both classes are estimator/backend territory, which this story lists as a
Non-Goal ("No estimator/backend code change"), so `make food-smoke` exiting 0 is
not reachable from this diff.
