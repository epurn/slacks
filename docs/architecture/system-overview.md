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

## Runtime Shape

- Mobile: Expo / React Native, iOS primary.
- Backend: FastAPI.
- Database: Postgres.
- Jobs: Celery workers with Redis queue.
- Deployment: Docker Compose for self-hosting; hosted service later uses the same service boundaries.
- LLM providers: Pi-inspired provider configuration implemented natively in Python.

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

1. User-provided nutrition label or barcode/package data.
2. Official restaurant or manufacturer source.
3. Trusted nutrition database.
4. Ingredient-based recipe calculation.
5. Similar-dish reference estimate.

