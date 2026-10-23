import { randomUUID } from "node:crypto";
import type { Settings } from "../config.js";
import type { Store } from "../db.js";
import { ModelError, type Json } from "../types.js";
import { createComplete, parseJson } from "../llm.js";
import { envelope, ApiFault } from "./contracts.js";
import { prepareContext } from "./context.js";
import { ANALYSIS_PROMPT, QUESTION_PROMPT, PROMPT_VERSION } from "./analysis-prompts.js";
import { validateGrounding, validateQuestionGrounding } from "./grounding.js";

async function generate(settings: Settings, db: Store, prompt: string, data: Json,
  check: (value: Json) => void, request: typeof fetch) {
  const complete = createComplete(settings, db, request);
  const messages = [{ role: "system", content: prompt }, { role: "user", content: JSON.stringify(data) }];
  let reason = "";
  for (let attempt = 0; attempt < 2; attempt++) {
    // Transport/auth/quota/refusal errors are outside the repair block: never retry a billed POST blindly.
    const message = await complete(messages, undefined, true);
    try {
      const draft = parseJson(message); check(draft); return { draft, attempts: attempt + 1 };
    } catch (error) {
      if (!(error instanceof ApiFault || error instanceof ModelError)) throw error;
      reason = error.message;
      messages.push({ role: "user", content: "Проверка JSON не пройдена: " + reason + ". Сформируй заново по исходному контексту, строго по системной схеме." });
    }
  }
  throw new ModelError("Ответ модели не прошёл проверку: " + reason);
}
export async function generatePrepared(settings: Settings, db: Store, input: Json, id: string, request: typeof fetch = fetch) {
  const context = prepareContext(input, settings.maxContextBytes);
  if (!input.event.sources.some((s: Json) => s.excerpt.trim().length >= 8)) throw new ApiFault(422, "VALIDATION_ERROR", "News evidence is too short");
  const { draft, attempts } = await generate(settings, db, ANALYSIS_PROMPT, context, value => validateGrounding(value, context), request);
  const notices = [
    ...input.research.limitations,
    ...(!input.research.items.length ? ["Банковские материалы отсутствуют: позиция банка не подтверждена."] : []),
    ...(input.is_mock || context.sources.some(s => s.is_mock) ? ["Контекст содержит синтетические данные."] : []),
  ];
  return envelope({ ...draft, id: randomUUID(), company_id: input.company_id, news_id: input.event.news_id,
    created_at: new Date().toISOString(), sources: context.sources, mode: "live",
    limitations: [...new Set([...draft.limitations, ...notices])],
    trace: [{ step: "prepared_context", detail: "sha256=" + context.sha256 },
      { step: "grounding_check", detail: `${PROMPT_VERSION}; attempts=${attempts}; JSON, quotes, references, profile fields and conditions checked; semantics require expert review` }] }, id, input.is_mock ? "mock" : "live");
}
export async function answerPrepared(settings: Settings, db: Store, input: Json, id: string, request: typeof fetch = fetch) {
  const company = input.analysis.sources.find((s: Json) => s.id === "company:" + input.company_id);
  if (!company) throw new ApiFault(502, "CONTRACT_VIOLATION", "Missing saved company evidence");
  let profile: Json;
  try { profile = JSON.parse(company.excerpt); } catch { throw new ApiFault(502, "CONTRACT_VIOLATION", "Invalid saved company evidence"); }
  const context = { input: { company_id: input.company_id, profile,
    event: { sources: input.analysis.sources.filter((s: Json) => s.kind === "news") } }, sources: input.analysis.sources,
    sha256: "", serialized_bytes: 0 };
  if (Buffer.byteLength(JSON.stringify(input)) > (settings.maxContextBytes ?? 200000)) throw new ApiFault(422, "VALIDATION_ERROR", "Question context is too large");
  const { draft } = await generate(settings, db, QUESTION_PROMPT, input, value => validateQuestionGrounding(value, context), request);
  return envelope({ ...draft, analysis_id: input.analysis.id, company_id: input.company_id,
    source_ids: [...new Set(draft.claims.flatMap((c: Json) => c.source_ids))] }, id, "live");
}
