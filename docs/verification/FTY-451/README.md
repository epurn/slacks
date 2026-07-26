# FTY-451 — release-docs truth pass: bring-up walkthrough notes

Evidence for the docs-only truth pass. Two parts: the **facts** each corrected
claim was checked against at head, and a **bring-up walkthrough** of the amended
docs.

## 1. Corrected facts, checked against head

| Claim (as amended) | Checked against |
| --- | --- |
| No release is tagged; status is pre-release | `git tag -l` → 0 tags; `CHANGELOG.md:3` `## Unreleased` populated above `## v1.0.0` |
| Body-weight deletion exists; log-event delete exists (soft void) | `backend/app/routers/weight_entries.py:114` `@router.delete`, `backend/app/routers/log_events.py:288` `@router.delete` |
| Saved-food deletion has **not** merged (named as landing, FTY-452/453) | `grep '\.delete(' backend/app/routers/*.py` → only the two routes above; `backend/app/routers/saved_foods.py` has no `DELETE` |
| Account deletion is safe to defer on a self-host | `AuthIdentity.user_id` is `ForeignKey("users.id", ondelete="CASCADE")` (`backend/app/models/identity.py:73-74`); user-owned tables cascade from the user |
| Expo SDK 57 | `mobile/package.json:18` → `"expo": "~57.0.1"` |
| Auth has shipped; module names | `mobile/api/auth.ts`, `mobile/state/session.tsx` (`SessionProvider`, `signIn`/`createAccount`/`signOut`, `useSession()`), `mobile/state/sessionStore.ts` (expo-secure-store, one atomic record). No `mobile/state/session.ts` exists. |
| A dev build is required (Expo Go insufficient) | `mobile/package.json` native deps are all `expo-*` **except** `@react-native-segmented-control/segmented-control` (used by `components/ui/SegmentedControl.tsx`), which Expo Go does not bundle. `mobile/ios/` is gitignored (`.gitignore:20`); `mobile/verify-e2e.sh:208,238` uses `expo prebuild` + `expo run:ios` as the build path. `mobile/.maestro/README.md:17-18` states the same ("Expo Go cannot faithfully host this"). |
| First-run route order: connect → sign in → onboarding → Today | `mobile/state/authRouting.ts:5-13` (four-state gate), routes `mobile/app/connect.tsx`, `signin.tsx`, `onboarding.tsx` |
| Compose service is `postgres`, not `db` | `docker-compose.yml:52` |
| Named volumes: `postgres-data`, `claude-config`, `codex-config` | `docker-compose.yml:221-237` |
| Trusted-proxy behaviour | `backend/app/settings.py:96` `rate_limit_trusted_proxy: bool = False`; `backend/app/routers/auth.py:43` `_client_ip` reads the **rightmost** XFF hop, with the one-trusted-proxy assumption documented in its docstring |
| Token stance: stateless HMAC-SHA256, 7-day default TTL, no session table | `backend/app/security/tokens.py` module docstring + `mint_token`; `backend/app/settings.py:77` `auth_token_ttl_seconds = 7 * 24 * 3600` |
| `fatty-reviewer` left as-is | `scripts/verify-brand-names.py:90-92` whitelists `\bfatty-reviewer\b` ("external GitHub App slug; rename is an operator action"). The three references (`docs/review-policy.md:39`, `docs/operations/branching-and-prs.md:65`, `docs/operations/github-setup.md:54`) are unchanged in this PR. No in-repo evidence of a rename surfaced. |

## 2. Bring-up walkthrough

Run against a local Compose stack brought up from this repo's `docker-compose.yml`
(the `slacks` project, `API_PORT=8000`), following only the amended README
Self-Hosting section and `docs/operations/local-dev-stack.md`.

**Backend — executed, green:**

```
$ curl -fsS http://localhost:8000/healthz
{"status":"ok"}

$ curl -fsS http://localhost:8000/readyz
{"status":"ready"}

$ docker compose ps
api        Up (healthy)
postgres   Up (healthy)
redis      Up (healthy)
searxng    Up (healthy)
worker     Up (healthy)
```

**Backup command — executed, green.** The new *Backup and Upgrade* section's
`pg_dump` line was run as written and produced a complete dump (3580 lines, 20
`CREATE TABLE` statements), then deleted. The `-T` flag and the
read-the-role-from-the-container form are both load-bearing: the first attempt
used a hardcoded `-U slacks`, which failed on this host with
`role "slacks" does not exist` because the local volume predates the FTY-335
`fatty` → `slacks` rename. The documented command reads `POSTGRES_USER` /
`POSTGRES_DB` from the container instead, so it is correct on a fresh
`.env.example` stack *and* on a renamed one.

**App — not executed here.** Building the iOS dev build was out of scope for this
docs-only story (the assignment does not require running-app evidence), so the
"Run the app" steps are documented from repo evidence rather than a captured
simulator session: the build path is the one `mobile/verify-e2e.sh` itself runs
(`expo prebuild` → `expo run:ios`), the connect-URL rules come from
`make sim-smoke` (`backend/app/ops/sim_readiness.py`, already documented in
`local-dev-stack.md`), and the first-run screen order comes from
`mobile/state/authRouting.ts`. Each is cited in the table above.

## 3. Verification

`make verify` green from the repo root (governance, brand guard, backend,
mobile, contracts).
