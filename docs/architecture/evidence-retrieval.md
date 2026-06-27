# Evidence Retrieval

Fatty v1 estimates should be source-backed whenever a relevant source can be
queried. The LLM can help parse user input, choose lookup strategies, and
extract structured facts, but it must not be the source of truth for nutrition
facts or calorie math when external evidence is available.

## Required V1 Sources

- USDA FoodData Central for generic foods and common serving references.
- Open Food Facts for barcoded and packaged food products.
- Configurable web search plus a hardened fetcher for official restaurant,
  manufacturer, and product pages.
- User-provided nutrition label images or manually entered label facts.

Provider credentials belong in backend configuration and server-side secrets.
They must never be exposed to mobile clients or committed to source.

## Lookup Rule

Use evidence retrieval before finalizing estimates for:

- barcodes,
- named packaged products,
- named restaurant items,
- manufacturer products,
- generic foods where USDA-style lookup is available,
- nutrition label images.

Model-prior estimates are allowed only when configured sources fail, no source
is applicable, or the user provided insufficient information and declines a
clarifying question. The entry must retain source status and assumptions so the
user can edit it.

## Security Boundary

The estimator does not get open-ended browser access. Backend tools own all
network access:

- sanitize queries before search,
- avoid sending personal profile or food-history context to search providers,
- fetch allowlisted public HTTP(S) URLs only,
- block private network, localhost, file, and metadata-service targets,
- enforce redirect, size, timeout, and content-type limits,
- strip scripts and active content before extraction,
- store extracted facts, URL, timestamp, and content hash rather than raw pages
  by default.

Fetched pages, search results, OCR text, and LLM output are untrusted until
validated by backend schemas and deterministic calculators.

## Initial Provider Notes

- USDA FoodData Central requires a data.gov API key, has documented search and
  detail endpoints, and publishes data in the public domain/CC0.
- Open Food Facts provides an open API for product data and has documented rate
  limits and data-quality caveats.
- Brave Search API is a reasonable first search adapter for official-source
  lookup because it provides web search and LLM-context-oriented search results.

Self-hosted deployments may disable any optional provider, but v1 must make
provider availability explicit in health/config diagnostics and estimation
source status.

## Contract

The public contracts for source-backed estimation — the evidence-source record,
provider capability/status values, normalized nutrition-fact fields, and the
search/fetch boundaries — are specified in
`docs/contracts/evidence-retrieval.md` (FTY-045). The USDA-only first
implementation is `docs/contracts/food-resolution.md` (FTY-044).

## References

- USDA FoodData Central API Guide: https://fdc.nal.usda.gov/api-guide
- Open Food Facts API documentation: https://openfoodfacts.github.io/openfoodfacts-server/api/
- Brave Search API documentation: https://api-dashboard.search.brave.com/app/documentation
