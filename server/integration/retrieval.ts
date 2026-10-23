import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ROOT } from "../config.js";
import type { Json } from "../types.js";
import type { Store } from "../db.js";
import type { Retrieval } from "../retrieval.js";
import { ApiFault, envelope, validate, type Envelope } from "./contracts.js";
import { ContractClient } from "./client.js";

export interface RetrievalPort {
  search(body: Json, requestId: string): Promise<Envelope>;
  rag(body: Json, requestId: string): Promise<Envelope>;
  resolve(body: Json, requestId: string): Promise<Envelope>;
}
export class HttpRetrieval implements RetrievalPort {
  constructor(private client: ContractClient) {}
  search(body: Json, id: string) { return this.client.call("/v1/tools/search_news", "SearchDataResponse", id, body); }
  rag(body: Json, id: string) { return this.client.call("/v1/tools/rag_bank_analytics", "RagDataResponse", id, body); }
  resolve(body: Json, id: string) { return this.client.call("/v1/tools/resolve_sources", "ResolveDataResponse", id, body); }
}
export class MockRetrieval implements RetrievalPort {
  private events: Json[] = JSON.parse(readFileSync(resolve(ROOT, "integration/fixtures/events.json"), "utf8"));
  private research: Json[] = JSON.parse(readFileSync(resolve(ROOT, "integration/fixtures/research.json"), "utf8"));
  async search(body: Json, id: string) {
    const items = this.events.filter(e => Date.parse(e.published_at) <= Date.parse(body.as_of) && (!body.news_id || e.news_id === body.news_id) && (!body.query || (e.title + " " + e.text).toLowerCase().includes(body.query.toLowerCase()))).slice(0, body.limit);
    return envelope({ items }, id, "mock", ["synthetic_news"]);
  }
  async rag(body: Json, id: string) {
    return envelope({ items: this.research.filter(s => Date.parse(s.published_at) <= Date.parse(body.as_of)).slice(0, body.limit), limitations: ["Синтетический корпус; не является аналитикой банка"] }, id, "mock", ["synthetic_bank_corpus"]);
  }
  async resolve(body: Json, id: string) {
    const registry = new Map<string, Json>([...this.events.flatMap(e => e.sources), ...this.research].map(s => [s.id, s]));
    const items = body.source_ids.map((key: string) => registry.get(key)).filter((s: Json | undefined) => s && s.published_at && Date.parse(s.published_at) <= Date.parse(body.as_of));
    const found = new Set(items.map((s: Json) => s.id));
    return envelope({ items, unknown_ids: body.source_ids.filter((key: string) => !found.has(key)) }, id, "mock", ["synthetic_source_registry"]);
  }
}
const date = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) ? value + "T00:00:00Z" : value;

/** Read-only projection of the existing prototype; extraction is deliberately 'other/reported'. */
export class LegacyRetrieval implements RetrievalPort {
  constructor(private db: Store, private retrieval: Retrieval) {}
  async search(body: Json, id: string) {
    const rows = body.news_id ? [{ id: body.news_id }] : this.db.all("SELECT id FROM news ORDER BY published DESC LIMIT 1000");
    const items = rows.map(row => this.db.news(row.id)).filter(n => Date.parse(date(n.published)) <= Date.parse(body.as_of) && (!body.query || (n.title + " " + n.text).toLowerCase().includes(body.query.toLowerCase()))).slice(0, body.limit).map(n => {
      if (!n.url && !n.is_demo) throw new ApiFault(502, "CONTRACT_VIOLATION", "Real news has no source URL");
      const event = { news_id: n.id, event_id: n.id, title: n.title, text: n.text, event_type: "other", published_at: date(n.published), event_at: null,
        fact_status: "reported", okved_divisions: [], countries: [], regions: [], company_ids: [], entity_mapping_source: null,
        sources: [{ id: "news:" + n.id, kind: "news", title: n.title, url: n.url || "https://example.invalid/demo/" + n.id, excerpt: n.text,
          document_id: null, page: null, published_at: date(n.published), is_mock: n.is_demo }], is_mock: n.is_demo };
      validate("Event", event, true); return event;
    });
    return envelope({ items }, id, items.some(e => e.is_mock) ? "mock" : "live", ["legacy_extraction_other_reported", "date_only_timestamps_assume_utc_midnight"]);
  }
  async rag(body: Json, id: string) {
    const items = this.retrieval.research(body.query, body.limit).map(doc => ({ id: "research:" + doc.id, kind: "bank", title: doc.title,
      url: doc.url, excerpt: doc.text, document_id: doc.document_id, page: doc.page, published_at: doc.date ? date(doc.date) : null, is_mock: false }))
      .filter(doc => doc.published_at !== null && Date.parse(doc.published_at) <= Date.parse(body.as_of));
    return envelope({ items, limitations: ["Лексический поиск исходного прототипа; недатированные страницы исключены."] }, id, "live", ["legacy_lexical_search", "undated_bank_pages_excluded"]);
  }
  async resolve(body: Json, id: string) {
    const items: Json[] = [], unknown_ids: string[] = [];
    for (const key of body.source_ids as string[]) {
      let source: Json | undefined;
      if (key.startsWith("news:")) {
        try {
          const result = await this.search({ news_id: key.slice(5), query: "", limit: 1, as_of: body.as_of }, id);
          source = result.data.items[0]?.sources[0];
        } catch (error) { if (!(error instanceof Error && "status" in error && error.status === 404)) throw error; }
      } else if (key.startsWith("research:")) {
        const match = /^(.*):c(\d+)$/.exec(key.slice(9));
        if (match) {
          const row = this.db.get("SELECT payload FROM research WHERE id=?", match[1]);
          if (row) {
            const doc = JSON.parse(row.payload), start = Number(match[2]);
            if (doc.date && start % 1400 === 0 && start < doc.text.length && Date.parse(date(doc.date)) <= Date.parse(body.as_of)) source = {
              id: key, kind: "bank", title: doc.title, url: doc.url, excerpt: doc.text.slice(Math.max(0, start - 150), start + 1600),
              document_id: doc.document_id, page: doc.page, published_at: date(doc.date), is_mock: false,
            };
          }
        }
      }
      if (source) items.push(source); else unknown_ids.push(key);
    }
    return envelope({ items, unknown_ids }, id, items.some(s => s.is_mock) ? "mock" : "live", ["undated_bank_pages_excluded"]);
  }
}
