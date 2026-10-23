import type { Json } from "../types.js";
import { ApiFault, validate } from "./contracts.js";
import type { prepareContext } from "./context.js";

export type PreparedContext = ReturnType<typeof prepareContext>;
const roots = new Set(["industry", "scale", "company_attributes", "bank_products", "foreign_trade", "geography",
  "dataset_position", "group", "related_companies", "counterparties", "payment_summary"]);
function reject(message: string): never { throw new ApiFault(502, "CONTRACT_VIOLATION", message); }
const nonblank = (s: unknown) => typeof s === "string" && Boolean(s.trim());
export function profileValue(profile: Json, path: string): unknown {
  const parts = path.slice(1).split("/").map(s => s.replace(/~1/g, "/").replace(/~0/g, "~"));
  if (!roots.has(parts[0]) || parts.some(s => ["__proto__", "prototype", "constructor", "source", "evidence", "limitation"].includes(s))) reject("Invalid business profile path");
  let value: any = profile;
  for (const key of parts) {
    if (value === null || typeof value !== "object" || !Object.hasOwn(value, key)) reject("Unknown profile path");
    value = value[key];
  }
  if (value !== null && typeof value === "object" && !(Array.isArray(value) && value.every(v => v === null || typeof v !== "object"))) reject("Profile path must select a concrete value");
  return value;
}
function numbers(text: string) {
  return text.replace(/(\d)[\s\u00a0\u202f](?=\d{3}(?:\D|$))/g, "$1").match(/[-+−]?\d+(?:[.,]\d+)?/g)?.map(s => s.replace(",", ".").replace("−", "-").replace(/^\+/, "")) ?? [];
}
/** Structural/provenance checks, not a proof of factual truth or economic causality. */
export function validateGrounding(answer: Json, context: PreparedContext, serverNotices = false) {
  validate("GeneratedAnalysis", serverNotices && Array.isArray(answer.limitations)
    ? { ...answer, limitations: answer.limitations.slice(0, 20) } : answer, true);
  if (!answer.limitations.every(nonblank)) reject("Blank limitation");
  const sources = new Map<string, Json>(context.sources.map(s => [s.id, s]));
  const companyId = context.input.company_id as string;
  // A numeric suffix in an identifier is not financial evidence. Permit the literal ID in prose without admitting its number on its own.
  const scan = (text: string) => numbers(/[A-Za-z_:]/.test(companyId) ? text.split(companyId).join(" ") : text);
  const supports: string[] = [];
  for (const c of answer.claims as Json[]) {
    if (!nonblank(c.text) || !c.source_ids.every((id: string) => sources.has(id))) reject("Unknown claim source or blank text");
    if (c.kind !== "ai") {
      const kind = c.kind === "fact" ? "news" : "bank";
      if (c.quote.trim().length < 8 || c.text !== c.quote || !c.source_ids.every((id: string) => sources.get(id)!.kind === kind)
        || !c.source_ids.every((id: string) => sources.get(id)!.excerpt.includes(c.quote))) reject("Quote not found in selected evidence");
      supports.push(c.quote);
    } else {
      if (c.quote !== "" || !c.source_ids.includes("company:" + context.input.company_id)
        || !c.source_ids.some((id: string) => context.input.event.sources.some((s: Json) => s.id === id))
        || !c.profile_paths?.length || !c.conditions?.length || !c.conditions.every(nonblank)) reject("AI claim needs company, news, business fields and conditions");
      const values = c.profile_paths.map((path: string) => profileValue(context.input.profile, path));
      if (values.some((v: unknown) => v === null || v === "unknown" || v === "" || Array.isArray(v) && !v.length)
        && (!answer.missing_data.some(nonblank) || !answer.limitations.some(nonblank))) reject("Unknown business field needs missing data and limitation");
      // Only selected news/bank excerpts and selected business values may supply numbers.
      const evidence = c.source_ids.filter((id: string) => sources.get(id)!.kind !== "company").map((id: string) => sources.get(id)!.excerpt).join(" ");
      supports.push(evidence + " " + JSON.stringify(values));
      const allowed = new Set(scan(supports.at(-1)!));
      if (scan(c.text + " " + c.conditions.join(" ")).some(n => !allowed.has(n))) reject("Unsupported numeric assertion");
    }
  }
  const used = new Set<number>();
  function section(text: string, indexes: number[], kind: string) {
    if (!indexes.length || indexes.some(i => i >= answer.claims.length)) reject("Unknown claim index");
    if (!indexes.some(i => answer.claims[i].kind === kind)) reject("Wrong evidence type for section");
    indexes.forEach(i => used.add(i));
    const allowed = new Set(indexes.flatMap(i => scan(supports[i])));
    if (scan(text).some(n => !allowed.has(n))) reject("Unsupported section number");
  }
  const g = answer.grounding;
  section(answer.summary, g.summary, "fact"); section(answer.why_relevant, g.why_relevant, "ai");
  for (const key of ["risks", "opportunities", "recommendations"]) {
    if (answer[key].length !== g[key].length) reject("Section and grounding length mismatch");
    answer[key].forEach((text: string, i: number) => {
      const refs = key === "recommendations" ? g[key][i].claim_indexes : g[key][i];
      const rec = key === "recommendations" ? g[key][i] : null;
      if (rec && (!nonblank(rec.condition) || !rec.required_data.every(nonblank))) reject("Recommendation needs condition and required data");
      section(text + (rec ? " " + rec.condition + " " + rec.required_data.join(" ") : ""), refs, "ai");
    });
  }
  if (used.size !== answer.claims.length) reject("Unused claim");
}
export function analysisDraft(value: Json) {
  return Object.fromEntries(["summary", "why_relevant", "claims", "risks", "opportunities", "recommendations", "limitations", "missing_data", "grounding"].map(key => [key, value[key]]));
}
export function validateQuestionGrounding(draft: Json, context: PreparedContext) {
  validate("GeneratedAnswer", draft, true);
  validateGrounding({ summary: draft.answer, why_relevant: draft.answer, claims: draft.claims,
    risks: [], opportunities: [], recommendations: [], limitations: draft.limitations, missing_data: draft.missing_data,
    grounding: { summary: draft.claim_indexes, why_relevant: draft.claim_indexes, risks: [], opportunities: [], recommendations: [] } }, context);
}
