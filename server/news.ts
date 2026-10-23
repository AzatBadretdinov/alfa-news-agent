import { createHash } from "node:crypto";
import { XMLParser, XMLValidator } from "fast-xml-parser";
import type { Settings } from "./config.js";
import type { Store } from "./db.js";
import { tags } from "./retrieval.js";
import { AppError, type Json } from "./types.js";
export function saveNews(db: Store, data: Json) {
  const title = String(data.title ?? "")
      .trim()
      .slice(0, 300),
    text = String(data.text ?? "")
      .trim()
      .slice(0, 18000);
  if (title.length < 5 || text.length < 30) throw new AppError("Нужны заголовок от 5 и текст от 30 символов.");
  const url = String(data.url ?? "")
    .trim()
    .slice(0, 2000);
  if (url) {
    try {
      if (!["https:", "http:"].includes(new URL(url).protocol)) throw new Error();
    } catch {
      throw new AppError("Источник должен быть HTTP(S)-ссылкой.");
    }
  }
  const id = createHash("sha256")
    .update(title + text)
    .digest("hex")
    .slice(0, 20);
  const published = String(data.published || new Date().toISOString()).slice(0, 100);
  db.run(
    "INSERT OR IGNORE INTO news VALUES(?,?,?,?,?,?,?)",
    id,
    title,
    text,
    url,
    published,
    JSON.stringify(tags(title + " " + text)),
    0,
  );
  return db.news(id);
}
const array = (value: any): any[] => (value == null ? [] : Array.isArray(value) ? value : [value]);
const textValue = (value: any): string =>
  value == null ? "" : typeof value === "object" ? textValue(value["#text"] ?? value["@_href"]) : String(value);
export async function ingestFeeds(settings: Settings, db: Store, request: typeof fetch = fetch) {
  if (!settings.feeds.length)
    throw new AppError("RSS не настроен. Добавьте NEWS_FEEDS_JSON в .env или вставьте новость вручную.");
  let processed = 0;
  const failed_hosts: string[] = [];
  const parser = new XMLParser({
    ignoreAttributes: false,
    removeNSPrefix: true,
    parseTagValue: false,
    processEntities: false,
    isArray: (name) => name === "item" || name === "entry",
  });
  for (const url of settings.feeds.slice(0, 5)) {
    try {
      const response = await request(url, {
        redirect: "error",
        signal: AbortSignal.timeout(20000),
        headers: { "User-Agent": "AlfaInsightHackathon/2.0" },
      });
      if (!response.ok || !response.body) {
        await response.body?.cancel();
        throw new Error();
      }
      const reader = response.body.getReader(),
        chunks: Uint8Array[] = [];
      let size = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > 2000000) throw new Error("RSS превышает 2 МБ");
          chunks.push(value);
        }
      } finally {
        await reader.cancel();
      }
      const xml = Buffer.concat(chunks).toString("utf8");
      if (/<!DOCTYPE|<!ENTITY/i.test(xml) || XMLValidator.validate(xml) !== true) throw new Error("Недопустимый XML");
      const doc = parser.parse(xml),
        entries = array(doc.rss?.channel?.item ?? doc.feed?.entry);
      for (const entry of entries.slice(0, 30)) {
        try {
          const links = array(entry.link),
            link = links.find((l) => l?.["@_rel"] === "alternate") ?? links[0];
          saveNews(db, {
            title: textValue(entry.title),
            text: textValue(entry.description ?? entry.summary ?? entry.content),
            url: textValue(link),
            published: textValue(entry.pubDate ?? entry.updated ?? entry.published),
          });
          processed++;
        } catch (error) {
          if (!(error instanceof AppError)) throw error;
        }
      }
    } catch {
      failed_hosts.push(new URL(url).hostname);
    }
  }
  return { processed, failed_hosts };
}
