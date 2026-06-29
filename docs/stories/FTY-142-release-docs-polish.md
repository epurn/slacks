---
id: FTY-142
state: ready
primary_lane: governance
touched_lanes: []
review_focus:
  - readyz-documented-in-readme
  - claude-login-after-bring-up
  - contracts-index-table-complete
  - overview-lists-new-endpoints-and-providers
  - docs-match-shipped-behaviour
risk: low
tags:
  - docs
  - release
  - diagnostics
approved_dependencies: []
requires_context:
  - docs/architecture/system-overview.md
  - docs/contracts/README.md
  - docs/operations/local-dev-stack.md
autonomous: true
---

# FTY-142: Release Docs Polish — `/readyz`, Login Ordering, Contracts Index, Overview Endpoints

## State

ready

## Lane

governance

## Dependencies

- None to schedule. Every item documents **already-merged** behaviour. Authors
  in parallel with FTY-128 (`CHANGELOG.md`), FTY-129 (`target-calculator.md`),
  and FTY-130 (`threat-model.md`) — **no file overlap**: this story owns
  **`README.md`, `docs/contracts/README.md`, and
  `docs/architecture/system-overview.md`**, none of which the other three
  touch. (FTY-129 owns `target-calculator.md` and FTY-130 owns `threat-model.md`
  — different files from the `contracts/README.md` and `system-overview.md` this
  story edits.)

## Outcome

Four small, independent docs gaps from the v1 release audit are closed so the
public docs match the shipped product:

1. **`/readyz` is undocumented in the README's health check.** The DB-readiness
   probe ships (`backend/app/routers/health.py:26`) and is already in
   `docs/operations/local-dev-stack.md` (the service table + the smoke-test
   block), but the README's **"7. Confirm health"** step (~lines 139–151) only
   curls `/healthz` and `/healthz/sources`. A self-hoster following the README
   never learns about readiness.
2. **The README's Claude Code login step is ordered before the stack is up.**
   Step **5a** (`docker compose exec api claude login`, ~lines 107–127) appears
   **before** step **6** ("Start the stack: `docker compose up`", ~line 129) —
   but `docker compose exec` needs a **running** container, so the steps are in
   an impossible order for a first-time reader.
3. **`docs/contracts/README.md` has zero links to the ~17 contract files.** It
   is a template + principles doc with no index, so the individual contracts
   (including the newer `goals-target-reveal.md` and `daily-summary.md`) are
   undiscoverable from the contracts entry point.
4. **`system-overview.md` omits shipped endpoints and provider paths.** The
   Runtime Shape / Source Hierarchy sections don't mention the
   goals/target-reveal route (FTY-106) or the daily-summary **range** read
   (FTY-123); line ~26 still describes LLM providers only as "Pi-inspired
   provider configuration", omitting the shipped `claude_code` (subscription)
   and keyless `openai_compatible` (local-model) paths.

## Scope

Each item is small and independent:

1. **README `/readyz` line.** In the **"7. Confirm health"** block, add a
   `/readyz` curl alongside the existing `/healthz` and `/healthz/sources`
   examples, with a one-line note that it reports DB readiness (`200` ready /
   `503` not ready) — matching the wording already in
   `docs/operations/local-dev-stack.md` (`{"status":"ready"}`). Documentation
   only; do not change the endpoint.
2. **README login ordering.** Reorder so the one-time `claude login` step
   (currently 5a) **follows** the stack bring-up (`docker compose up`). The
   cleanest fix is to move the login section to after the "Start the stack" step
   (it already says "After starting the stack for the first time" — so it
   belongs there), renumbering the surrounding steps so the sequence reads:
   configure providers → start the stack → (if using `claude_code`) one-time
   login → confirm health. Keep all the login content (the `exec` command, the
   verify-with-`/healthz/sources` snippet, and the **security note** about the
   `claude-config` host secret) intact — only its position and step numbers
   change.
3. **Contracts index table** in `docs/contracts/README.md`. Add a table that
   links every contract file in `docs/contracts/` with a one-line description
   each — explicitly including `goals-target-reveal.md`, `daily-summary.md`,
   `target-calculator.md`, and the rest (`corrections.md`, `estimation-jobs.md`,
   `evidence-retrieval.md`, `exercise-burn.md`, `food-resolution.md`,
   `identity-and-profile.md`, `label-extraction.md`, `label-upload.md`,
   `llm-provider.md`, `log-attachments.md`, `log-events.md`,
   `parse-candidates.md`, `saved-foods.md`, `weight-entries.md`). The author
   lists the directory to confirm the current set before writing — the index
   must match what's actually there, not this spec's snapshot. Place it as a
   `## Contracts Index` section (above or below the existing template/principles
   content — author's discretion).
4. **`system-overview.md` endpoint + provider lines.** (a) In **Runtime Shape**,
   replace/extend the "Pi-inspired provider configuration" LLM line so it names
   the shipped provider paths: API-key providers (OpenAI / Anthropic), the
   `claude_code` subscription provider, and the keyless `openai_compatible`
   local-model path (Ollama / LM Studio / vLLM). (b) Add a short mention of the
   goals/target-reveal route (FTY-106) and the daily-summary **range** read
   (FTY-123) where the overview enumerates the runtime surface — a line each is
   enough; do not duplicate the contract docs. Keep the Source Hierarchy list as
   is unless a provider-path mention naturally belongs there.

## Non-Goals

- **No version or CHANGELOG change** — that is FTY-128; this story must not touch
  versioning or `CHANGELOG.md` to avoid overlap.
- **No edits to `CHANGELOG.md`, `target-calculator.md`, or `threat-model.md`** —
  those are owned by FTY-128 / FTY-129 / FTY-130 respectively.
- No product code, schema, endpoint, contract behaviour, or `.env.example`
  change — these four items document or reorganise already-shipped behaviour.
- Do not rewrite the contracts template/principles content in
  `contracts/README.md` — only **add** the index.
- Do not add private automation detail, machine paths, tokens, or queue state —
  all three files are in the **public** repo.

## Contracts

- **None.** No request/response or schema change. The contracts-index table in
  `contracts/README.md` links existing contracts; it defines no new boundary.
  `system-overview.md` mentions existing endpoints; it changes no contract.

## Security / Privacy

- Docs-only, **public repo**. Item 2 deliberately **preserves** the existing
  `claude-config` host-secret security note (only its position changes), and the
  reordering removes a footgun (a reader can't run `claude login` against a
  not-yet-running container). No behaviour change, no new surface. The only
  hazard is leaking private automation detail into the public repo — none is
  added. Rated **low**.

## Acceptance Criteria

- The README "Confirm health" step documents `/readyz` (purpose + `200`/`503`
  readiness semantics) alongside `/healthz` and `/healthz/sources`.
- The README's `claude login` step appears **after** the `docker compose up`
  bring-up step, with surrounding steps renumbered into a coherent sequence and
  all login content (incl. the `claude-config` host-secret security note)
  preserved.
- `docs/contracts/README.md` carries an index table linking every contract file
  in `docs/contracts/` (incl. `goals-target-reveal.md` and `daily-summary.md`)
  with a one-line description each, matching the actual directory contents.
- `system-overview.md` names the shipped LLM provider paths (API-key,
  `claude_code` subscription, keyless `openai_compatible` local) and mentions the
  goals/target-reveal route and the daily-summary range read.
- No version string, `CHANGELOG.md`, `target-calculator.md`, `threat-model.md`,
  or product code is touched.
- `make verify` passes (governance boundary + docs/link checks); any links the
  new index adds resolve.

## Verification

- `make verify` (governance boundary + docs/link checks); the public-repo
  boundary check stays green and the new contract-index links resolve.
- Manual read-through diff confirming all four items are addressed, the README
  step sequence is now valid (login after bring-up), and no
  versioning/CHANGELOG/owned-by-other-story content changed.

## Planning Notes

- **Source the contracts index from the directory**, not this spec — the author
  lists `docs/contracts/` to confirm the current file set (17 contracts + the
  README at time of writing) so the table can't drift on day one.
- **Reordering is a move, not a rewrite** — relocate the existing 5a block; keep
  every line of its content (especially the security note), only changing
  position and step numbers.
- **`system-overview.md` stays high-level** — a line per provider path / new
  endpoint; the contracts and README carry the detail, so don't duplicate it.
- **No evidence research warranted** — every item documents shipped behaviour;
  no health/nutrition/behavioural question is at stake.

## Readiness Sanity Pass

- **Product decision gaps:** none — every item documents/reorganises shipped
  behaviour; wording and index placement are author discretion.
- **Cross-lane impact:** governance (docs) only, **no touched lanes**. **Single
  boundary, zero big rocks:** no contract change, no migration/new table, no new
  trust boundary. Owns `README.md` + `contracts/README.md` + `system-overview.md`
  exclusively — no overlap with FTY-128/129/130.
- **Size:** `review_focus` = 5 (at ceiling), `requires_context` = 3 (under 8).
  Three files, four small independent edits — within the guardrail (cf. FTY-084's
  six-item docs polish).
- **Security/privacy risk:** low — public-repo docs; item 2 preserves the
  host-secret note and removes an ordering footgun; the only hazard (leaking
  private detail) is fenced off.
- **Verification path:** `make verify` + a read-through diff validating the new
  step sequence and resolving index links.
- **Assumptions safe for autonomy:** yes — the four items, their file locations
  and line ranges, the move-don't-rewrite constraint, and the
  list-the-directory rule for the index are all explicit; non-goals fence it off
  from FTY-128/129/130.
