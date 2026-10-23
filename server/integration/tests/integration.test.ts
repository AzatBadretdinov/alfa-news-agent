import { test } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createRequire } from "node:module";
import { ROOT } from "../../config.js";
import type { Json } from "../../types.js";
import { ApiFault, envelope, validate, validateAnalysis } from "../contracts.js";
import { ContractClient } from "../client.js";
import { MockAgent, type AgentPort } from "../agent.js";
import { MockRetrieval, type RetrievalPort } from "../retrieval.js";
import { createGateway } from "../gateway.js";

const profile = JSON.parse(readFileSync(resolve(ROOT, "contracts/v1/examples/profile-response.json"), "utf8")).data;
const asOf = "2026-10-23T00:00:00Z";
const body = { company_id: "U_A", news_id: "demo-rate", as_of: asOf, audience_role: "cfo" };
const headers = { "Content-Type": "application/json", "X-Request-ID": "node-test-01" };

function mlClient(mutate?: (path: string, value: Json) => void) {
  return new ContractClient("http://ml.test", 500, (async (url, init) => {
    const path = new URL(String(url)).pathname, id = (init!.headers as Json)["X-Request-ID"];
    let data: Json;
    if (path === "/v1/health") data = { status: "ok", service: "ml" };
    else if (path === "/v1/rank") {
      const request = JSON.parse(String(init!.body));
      data = { company_id: request.company_id, as_of: request.as_of, items: request.events.map((e: Json) => ({
        news_id: e.news_id, event_id: e.event_id, score: 0.8, score_kind: "mock", reasons: [{ code: "fixture", text: "Профиль учтён", profile_paths: ["/industry"] }], warnings: ["mock_ranker"] })),
        excluded_future_news_ids: [], truncated: false };
    } else if (path === "/v1/companies") data = { items: ["U_A"], offset: 0, limit: 20 };
    else data = structuredClone(profile);
    const value = envelope(data, id, "mock"); mutate?.(path, value);
    return Response.json(value);
  }) as typeof fetch);
}
async function harness(options: { agent?: AgentPort; retrieval?: RetrievalPort; ml?: ContractClient; maxSessions?: number; ttlMs?: number } = {}) {
  const app = createGateway({ ml: options.ml ?? mlClient(), retrieval: new MockRetrieval(), agent: options.agent ?? new MockAgent(), ...options });
  const server = app.listen(0, "127.0.0.1");
  await new Promise<void>(resolve => server.once("listening", resolve));
  const address = server.address(); assert.ok(address && typeof address !== "string");
  const base = "http://127.0.0.1:" + address.port;
  return { base, async call(path: string, data?: Json) {
    const response = await fetch(base + path, { headers, method: data ? "POST" : "GET", ...(data ? { body: JSON.stringify(data) } : {}) });
    return { status: response.status, value: await response.json() as Json };
  }, async close() { server.closeAllConnections(); await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); } };
}

test("v1 composes context, rank and evidence; remembers scoped questions", async () => {
  const h = await harness();
  try {
    const analysis = await h.call("/v1/analyze", body);
    assert.equal(analysis.status, 200); validateAnalysis(analysis.value.data);
    assert.equal(analysis.value.meta.request_id, "node-test-01");
    assert.equal(analysis.value.meta.mode, "mock");
    assert.ok(analysis.value.meta.warnings.includes("synthetic_news"));
    const id = analysis.value.data.id;
    assert.equal((await h.call(`/v1/analyses/${id}?company_id=U_C`)).status, 404);
    assert.equal((await h.call(`/v1/analyses/${id}?company_id=U_A`)).status, 200);
    const first = await h.call(`/v1/analyses/${id}/questions`, { company_id: "U_A", question: "Что уточнить?" });
    const second = await h.call(`/v1/analyses/${id}/questions`, { company_id: "U_A", question: "А затем?" });
    assert.match(first.value.data.answer, /реплик: 0/); assert.match(second.value.data.answer, /реплик: 1/);
    assert.equal((await h.call(`/v1/analyses/${id}/questions`, { company_id: "U_C", question: "Что уточнить?" })).status, 404);
    assert.equal((await h.call("/v1/agent/analyze", body)).status, 404, "Internal provider route must not be public");
  } finally { await h.close(); }
});

test("agent can add evidence discovered by tools only when role 3 resolves the exact source", async () => {
  const registry = new MockRetrieval();
  const source = (await registry.rag({ as_of: asOf, limit: 5 }, "test")).data.items[0];
  const retrieval: RetrievalPort = { search: registry.search.bind(registry), resolve: registry.resolve.bind(registry),
    async rag(_body, id) { return envelope({ items: [], limitations: [] }, id, "mock"); } };
  const mock = new MockAgent();
  const agent: AgentPort = { answer: mock.answer.bind(mock), async analyze(input, id) {
    const result = await mock.analyze(input, id);
    result.data.sources.push(structuredClone(source));
    result.data.claims.push({ kind: "bank", text: source.excerpt, quote: source.excerpt, source_ids: [source.id] });
    return result;
  } };
  const h = await harness({ agent, retrieval });
  try { assert.equal((await h.call("/v1/analyze", body)).status, 200); }
  finally { await h.close(); }
});

test("gateway rejects wrong company, modified evidence and dangling claims from agents", async () => {
  for (const mutate of [
    (value: Json) => { value.company_id = "U_C"; },
    (value: Json) => { value.sources[1].excerpt = "Invented source text"; },
    (value: Json) => { value.claims[0].source_ids = ["absent"]; },
  ]) {
    const mock = new MockAgent();
    const agent: AgentPort = { answer: mock.answer.bind(mock), async analyze(input, id) { const result = await mock.analyze(input, id); mutate(result.data); return result; } };
    const h = await harness({ agent });
    try { const r = await h.call("/v1/analyze", body); assert.equal(r.status, 502); assert.equal(r.value.error.code, "CONTRACT_VIOLATION"); }
    finally { await h.close(); }
  }
});

test("JSON object key order from a remote agent does not change source identity", async () => {
  const mock = new MockAgent();
  const agent: AgentPort = { answer: mock.answer.bind(mock), async analyze(input, id) {
    const result = await mock.analyze(input, id);
    result.data.sources = result.data.sources.map((s: Json) => Object.fromEntries(Object.entries(s).reverse()));
    return result;
  } };
  const h = await harness({ agent });
  try { assert.equal((await h.call("/v1/analyze", body)).status, 200); }
  finally { await h.close(); }
});

test("upstream schema drift and context mismatch fail at the boundary", async () => {
  for (const mutate of [
    (path: string, value: Json) => { if (path.includes("/companies/")) value.data.schema_version = "2.0"; },
    (path: string, value: Json) => { if (path === "/v1/rank") value.data.company_id = "U_C"; },
  ]) {
    const h = await harness({ ml: mlClient(mutate) });
    try { assert.equal((await h.call("/v1/analyze", body)).status, 502); }
    finally { await h.close(); }
  }
});

test("HTTP clients classify provider failures without leaking response bodies", async () => {
  for (const [request, status, code] of [
    [async () => { throw new DOMException("private timeout", "TimeoutError"); }, 504, "DEPENDENCY_TIMEOUT"],
    [async () => { throw new Error("private provider URL or key"); }, 503, "DEPENDENCY_UNAVAILABLE"],
    [async () => new Response("private provider details", { status: 500 }), 502, "CONTRACT_VIOLATION"],
    [async () => Response.json({ wrong: "shape" }), 502, "CONTRACT_VIOLATION"],
  ] as const) {
    const client = new ContractClient("http://provider.test", 10, request as typeof fetch);
    await assert.rejects(client.call("/v1/health", "HealthDataResponse", "test"), (error: unknown) => {
      assert.ok(error instanceof ApiFault); assert.equal(error.status, status); assert.equal(error.code, code); assert.doesNotMatch(error.message, /private/); return true;
    });
  }
});

test("source dates, strict booleans, content types and origin checks are enforced", async () => {
  const h = await harness();
  try {
    assert.equal((await h.call("/v1/analyze", { ...body, as_of: "2020-01-01T00:00:00Z" })).status, 404);
    for (const data of [{ ...body, as_of: "2026-10-23" }, { ...body, unknown: true }]) assert.equal((await h.call("/v1/analyze", data)).status, 422);
    const forbidden = await fetch(h.base + "/v1/analyze", { method: "POST", headers: { ...headers, Origin: "https://evil.example" }, body: JSON.stringify(body) });
    assert.equal(forbidden.status, 403);
    const wrongType = await fetch(h.base + "/v1/analyze", { method: "POST", body: JSON.stringify(body) });
    assert.equal(wrongType.status, 415);
    const malformed = await fetch(h.base + "/v1/analyze", { method: "POST", headers, body: "{" });
    assert.equal(malformed.status, 400); validate("Error", await malformed.json());
    const large = await fetch(h.base + "/v1/analyze", { method: "POST", headers, body: JSON.stringify({ value: "x".repeat(1_000_001) }) });
    assert.equal(large.status, 413);
  } finally { await h.close(); }
});

test("analysis concurrency and session storage are bounded", { timeout: 5000 }, async () => {
  let started = 0; let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let ready!: () => void; const both = new Promise<void>(resolve => { ready = resolve; });
  const mock = new MockAgent();
  const agent: AgentPort = { answer: mock.answer.bind(mock), async analyze(input, id) { started++; if (started === 2) ready(); await gate; return mock.analyze(input, id); } };
  const h = await harness({ agent });
  try {
    const a = h.call("/v1/analyze", body), b = h.call("/v1/analyze", body);
    await both;
    assert.equal((await h.call("/v1/analyze", body)).status, 429);
    release(); assert.equal((await a).status, 200); assert.equal((await b).status, 200);
  } finally { release(); await h.close(); }
  const full = await harness({ maxSessions: 1 });
  try { assert.equal((await full.call("/v1/analyze", body)).status, 200); assert.equal((await full.call("/v1/analyze", body)).status, 429); }
  finally { await full.close(); }
  const expired = await harness({ ttlMs: -1 });
  try { const a = await expired.call("/v1/analyze", body); assert.equal((await expired.call(`/v1/analyses/${a.value.data.id}?company_id=U_A`)).status, 404); }
  finally { await expired.close(); }
});

test("manual baseline keeps its own scale", () => {
  const item = { news_id: "n", event_id: "e", score: 3.2, score_kind: "manual_feature_baseline", reasons: [{ code: "industry", text: "evidence", profile_paths: ["/industry"] }], warnings: [] };
  validate("RankedItem", item);
  assert.throws(() => validate("RankedItem", { ...item, score_kind: "logistic_relevance_uncalibrated" }));
});

test("OpenAPI 3.1 can be parsed and resolved without network references", async () => {
  const parser = createRequire(import.meta.url)("@apidevtools/swagger-parser");
  const api = await parser.validate(resolve(ROOT, "contracts/v1/openapi.json"));
  assert.equal(api.openapi, "3.1.0");
  assert.ok(api.paths["/v1/rank"].post.requestBody.content["application/json"].schema.properties.events);
});
