/**
 * FTY-366: mechanical client ↔ server request-contract conformance for the
 * re-match boundary (`docs/contracts/evidence-retrieval.md` → Item Re-match).
 *
 * Captures the request bodies this client actually constructs — via an
 * injected fetch — and validates them against the backend's published OpenAPI
 * snapshot (`backend/tests/snapshots/openapi.json`), the authoritative schema
 * CI regenerates on any route change. Everything is data-driven off that one
 * snapshot: a legitimate contract change updates the fixture and this suite
 * follows automatically; client/server request drift (missing or renamed
 * field, out-of-bound value, forbidden extra key, renamed route) fails here in
 * CI instead of surfacing as a runtime 422 in dogfooding.
 *
 * Test data is opaque refs and padding only — no nutrition values, candidate
 * names, or user queries.
 */

import type { ApiSession } from "@/api/client";
import { listSourceCandidates, reResolveItem } from "@/api/corrections";

// Node built-ins are available under Jest but not in the app tsconfig; the
// e2e runner test uses the same require pattern.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { readFileSync } = require("fs") as {
  readFileSync: (filePath: string, encoding: string) => string;
};
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { join } = require("path") as { join: (...parts: string[]) => string };

declare const __dirname: string;

// ---------------------------------------------------------------------------
// Snapshot loading
// ---------------------------------------------------------------------------

interface JsonSchema {
  $ref?: string;
  type?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
  minLength?: number;
  maxLength?: number;
  anyOf?: JsonSchema[];
  items?: JsonSchema;
}

interface OpenApiDoc {
  paths: Record<
    string,
    Record<string, { requestBody?: { content?: Record<string, { schema?: JsonSchema }> } }>
  >;
  components: { schemas: Record<string, JsonSchema> };
}

const SNAPSHOT_PATH = join(
  __dirname,
  "..",
  "..",
  "backend",
  "tests",
  "snapshots",
  "openapi.json",
);

const openapi = JSON.parse(readFileSync(SNAPSHOT_PATH, "utf8")) as OpenApiDoc;

const RE_RESOLVE_PATH = "/api/users/{user_id}/derived-items/food/{item_id}/re-resolve";
const CANDIDATES_PATH =
  "/api/users/{user_id}/derived-items/food/{item_id}/source-candidates";

/** Resolve `#/components/schemas/...` references against the snapshot. */
function resolveRef(schema: JsonSchema): JsonSchema {
  if (schema.$ref === undefined) return schema;
  const name = schema.$ref.replace("#/components/schemas/", "");
  const target = openapi.components.schemas[name];
  if (target === undefined) {
    throw new Error(`unresolvable $ref in snapshot: ${schema.$ref}`);
  }
  return resolveRef(target);
}

/** The published JSON request-body schema for `POST <path>`. */
function requestBodySchema(path: string): JsonSchema {
  const schema = openapi.paths[path]?.post?.requestBody?.content?.[
    "application/json"
  ]?.schema;
  if (schema === undefined) {
    throw new Error(`snapshot has no JSON request body for POST ${path}`);
  }
  return resolveRef(schema);
}

// ---------------------------------------------------------------------------
// Minimal data-driven JSON Schema validator (the subset the snapshot uses)
// ---------------------------------------------------------------------------

function typeMatches(value: unknown, type: string): boolean {
  switch (type) {
    case "object":
      return typeof value === "object" && value !== null && !Array.isArray(value);
    case "array":
      return Array.isArray(value);
    case "string":
      return typeof value === "string";
    case "number":
      return typeof value === "number";
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "boolean":
      return typeof value === "boolean";
    case "null":
      return value === null;
    default:
      throw new Error(`unsupported schema type: ${type}`);
  }
}

/** Return every violation of `schema` by `value` (empty array = conformant). */
function violations(value: unknown, rawSchema: JsonSchema, path = "body"): string[] {
  const schema = resolveRef(rawSchema);

  if (schema.anyOf !== undefined) {
    const branchFailures = schema.anyOf.map((branch) =>
      violations(value, branch, path),
    );
    return branchFailures.some((failures) => failures.length === 0)
      ? []
      : [`${path}: matches no anyOf branch`];
  }

  const found: string[] = [];
  if (schema.type !== undefined && !typeMatches(value, schema.type)) {
    return [`${path}: expected type ${schema.type}`];
  }

  if (schema.type === "string" && typeof value === "string") {
    if (schema.minLength !== undefined && value.length < schema.minLength) {
      found.push(`${path}: shorter than minLength ${schema.minLength}`);
    }
    if (schema.maxLength !== undefined && value.length > schema.maxLength) {
      found.push(`${path}: longer than maxLength ${schema.maxLength}`);
    }
  }

  if (schema.type === "object" && typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    for (const required of schema.required ?? []) {
      if (!(required in record)) {
        found.push(`${path}: missing required key "${required}"`);
      }
    }
    const properties = schema.properties ?? {};
    for (const [key, propertyValue] of Object.entries(record)) {
      const propertySchema = properties[key];
      if (propertySchema === undefined) {
        if (schema.additionalProperties === false) {
          found.push(`${path}: forbidden extra key "${key}"`);
        }
        continue;
      }
      found.push(...violations(propertyValue, propertySchema, `${path}.${key}`));
    }
  }

  return found;
}

// ---------------------------------------------------------------------------
// Capture what the client actually sends
// ---------------------------------------------------------------------------

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const ITEM_ID = "44444444-4444-4444-4444-444444444444";

interface CapturedRequest {
  url: string;
  body: unknown;
}

async function capture(
  run: (fetchImpl: typeof fetch) => Promise<unknown>,
  responseBody: unknown,
): Promise<CapturedRequest> {
  const fetchMock = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => responseBody,
  } as unknown as Response);
  await run(fetchMock as unknown as typeof fetch);
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return { url, body: JSON.parse(init.body as string) };
}

/** Assert `url` addresses the snapshot's route template for `path`. */
function expectUrlMatchesRoute(url: string, path: string): void {
  const pattern = new RegExp(
    `^https://api\\.example\\.test${path.replace(/\{[^}]+\}/g, "[^/]+")}$`,
  );
  expect(url).toMatch(pattern);
}

// ---------------------------------------------------------------------------
// Conformance: the client's constructed bodies validate against the snapshot
// ---------------------------------------------------------------------------

describe("re-resolve request conformance (ReResolveRequest)", () => {
  const schema = requestBodySchema(RE_RESOLVE_PATH);

  it("a typical candidate re-resolve body validates against the published schema", async () => {
    const { url, body } = await capture(
      (fetchImpl) => reResolveItem(SESSION, ITEM_ID, "usda_fdc:2345170", fetchImpl),
      { item_type: "food", id: ITEM_ID },
    );

    expectUrlMatchesRoute(url, RE_RESOLVE_PATH);
    expect(violations(body, schema)).toEqual([]);
  });

  it("transmits a full-bound source_ref unmangled (bound read from the snapshot)", async () => {
    const maxLength = resolveRef(schema.properties?.source_ref ?? {}).maxLength;
    expect(maxLength).toBeDefined();
    const fullBoundRef = "r".repeat(maxLength as number);

    const { body } = await capture(
      (fetchImpl) => reResolveItem(SESSION, ITEM_ID, fullBoundRef, fetchImpl),
      { item_type: "food", id: ITEM_ID },
    );

    expect(violations(body, schema)).toEqual([]);
    expect((body as { source_ref: string }).source_ref).toBe(fullBoundRef);
  });
});

describe("list-candidates request conformance (ListAlternativesRequest)", () => {
  const schema = requestBodySchema(CANDIDATES_PATH);

  it("the no-query body validates against the published schema", async () => {
    const { url, body } = await capture(
      (fetchImpl) => listSourceCandidates(SESSION, ITEM_ID, undefined, fetchImpl),
      { candidates: [] },
    );

    expectUrlMatchesRoute(url, CANDIDATES_PATH);
    expect(violations(body, schema)).toEqual([]);
  });

  it("a query-override body validates, up to the snapshot's bound", async () => {
    // `query` is published as anyOf [bounded string, null]; read the bound from
    // the string branch so a tightened contract updates this test's data.
    const querySchema = resolveRef(schema.properties?.query ?? {});
    const stringBranch = (querySchema.anyOf ?? [querySchema]).find(
      (branch) => resolveRef(branch).type === "string",
    );
    expect(stringBranch).toBeDefined();
    const bound = resolveRef(stringBranch as JsonSchema).maxLength;
    expect(bound).toBeDefined();

    const { body } = await capture(
      (fetchImpl) =>
        listSourceCandidates(SESSION, ITEM_ID, "q".repeat(bound as number), fetchImpl),
      { candidates: [] },
    );

    expect(violations(body, schema)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Mechanism proof: the validator fails each documented drift class, so a
// client that started producing such a body would fail the suite above.
// ---------------------------------------------------------------------------

describe("drift detection mechanics", () => {
  const schema = requestBodySchema(RE_RESOLVE_PATH);

  it("flags a missing/renamed required field", () => {
    expect(violations({ ref: "usda_fdc:1" }, schema)).toEqual(
      expect.arrayContaining([expect.stringContaining('missing required key "source_ref"')]),
    );
  });

  it("flags a forbidden extra key (extra=forbid)", () => {
    expect(violations({ source_ref: "usda_fdc:1", calories: 50 }, schema)).toEqual(
      expect.arrayContaining([expect.stringContaining('forbidden extra key "calories"')]),
    );
  });

  it("flags out-of-bound values (bounds read from the snapshot)", () => {
    const bound = resolveRef(schema.properties?.source_ref ?? {}).maxLength as number;
    expect(violations({ source_ref: "r".repeat(bound + 1) }, schema)).not.toEqual([]);
    expect(violations({ source_ref: "" }, schema)).not.toEqual([]);
  });

  it("flags a non-string source_ref", () => {
    expect(violations({ source_ref: 12345 }, schema)).not.toEqual([]);
  });
});
