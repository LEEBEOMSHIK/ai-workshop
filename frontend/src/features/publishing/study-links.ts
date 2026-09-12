import type { StudySnapshot } from "./types";

const workerTopics: Readonly<Record<string, readonly string[]>> = {
  "document-structure": ["data", "ocr", "parsing", "document-structure"],
  chunking: ["data", "evidence", "chunking", "evidence-unit"],
  "embedding-indexing": ["models", "infrastructure", "configuration", "embedding", "indexing"],
  "retrieval-fusion": ["retrieval", "configuration", "bm25", "rrf"],
  "evidence-highlighting": ["evidence", "interface", "security", "highlighting", "viewer"],
  "quality-evaluation": ["evaluation", "learning", "quality", "metrics"],
};

export function relatedStudiesForWorker(
  workerSlug: string,
  studies: readonly StudySnapshot[],
): readonly StudySnapshot[] {
  const topics = new Set(workerTopics[workerSlug] ?? []);
  return studies.filter((study) => study.content.topic_keys.some((topic) => topics.has(topic)));
}
