# System Overview

Fatty is an iOS-first, self-hostable nutrition and exercise tracker.

## Product Decisions

- Natural language is the input; structured timeline entries are the output.
- The app is not a chatbot.
- Food entries are stored as raw log events plus derived food items.
- Exercise can be logged in the same event and becomes derived exercise items.
- Estimation can take time; entries appear immediately as pending and update through polling.
- Calories and macros are v1 nutrition scope.
- Exercise burn uses MET-based active calories in v1.
- Targets use minimal required profile data, Mifflin-St Jeor initial RMR, NIDDK-style dynamic goal planning, and suggested adaptive calibration over time.
- Food photos for plated portion estimation are not v1. Nutrition label photos and barcode scans are v1.
- Food, product, restaurant, and label estimates must use source-backed evidence retrieval when a relevant source lookup is possible. Model prior alone is a last-resort fallback, not the normal path.
- Self-hosted deployments must be able to configure their own nutrition, search, and LLM provider credentials.

## Runtime Shape

- Mobile: Expo / React Native, iOS primary.
- Backend: FastAPI.
- Database: Postgres.
- Jobs: Celery workers with Redis queue.
- Deployment: Docker Compose for self-hosting; hosted service later uses the same service boundaries.
- LLM providers: Pi-inspired provider configuration implemented natively in Python.
- Evidence providers: USDA FoodData Central, Open Food Facts, and a configurable web search plus hardened fetch adapter.

## Estimation Boundary

The estimator is a constrained async engine, not an open-ended user-visible agent.

The LLM may:

- parse messy input,
- extract candidate food or exercise items,
- propose source lookup queries,
- extract facts from labels or fetched pages,
- structure assumptions and follow-up questions.

The backend must:

- validate tool calls,
- sanitize search queries,
- fetch URLs through a hardened fetcher,
- validate model outputs,
- calculate calories, macros, targets, and exercise burn deterministically,
- require source-backed lookup for named products, restaurant items, barcodes, nutrition labels, and generic foods when a configured source is available,
- decide what gets stored,
- enforce memory and privacy rules.

## Core Data Concepts

- `users`
- `auth_identities`
- `user_profiles`
- `goals`
- `daily_targets`
- `log_events`
- `log_attachments`
- `derived_food_items`
- `derived_exercise_items`
- `evidence_sources`
- `estimation_jobs`
- `estimation_runs`
- `clarification_questions`
- `clarification_answers`
- `saved_foods`
- `recipes`
- `food_aliases`
- `portion_memories`
- `corrections`
- `body_weight_entries`
- `products`
- `restaurant_items`
- `daily_summaries`

## Source Hierarchy

Evidence retrieval follows a priority order when a relevant source is available:

1. User-provided nutrition label images (FTY-064) — extracted facts from uploaded photos.
2. Official restaurant or manufacturer pages (FTY-062) — search + fetch + extraction for named restaurant/manufacturer items.
3. Barcode / packaged-product data from Open Food Facts (FTY-060).
4. Generic food facts from USDA FoodData Central (FTY-044).
5. Model-prior estimate with explicit source status (fallback when sources are unavailable/disabled or no confident match is found).
6. Ingredient-based recipe calculation (deferred).
7. Similar-dish reference estimate (deferred).

See `docs/contracts/evidence-retrieval.md` for the full hierarchy and source precedence rules.
