import type { HumanIdentity } from "./human-art";
export type StationEquipment = "scanner" | "segments" | "index" | "retrieval" | "source" | "evaluation";
interface StationArt { person: HumanIdentity; equipment: StationEquipment; accent: string; label: string }
const stations: Record<string, StationArt> = {
  "document-structure": { person: "document-structure", equipment: "scanner", accent: "#76a899", label: "DOCUMENT INTAKE" },
  chunking: { person: "chunking", equipment: "segments", accent: "#c9a465", label: "EVIDENCE UNITS" },
  "embedding-indexing": { person: "embedding-indexing", equipment: "index", accent: "#779fb8", label: "INDEX ARCHIVE" },
  "retrieval-fusion": { person: "retrieval-fusion", equipment: "retrieval", accent: "#a3ad78", label: "RETRIEVAL DESK" },
  "evidence-highlighting": { person: "evidence-highlighting", equipment: "source", accent: "#b492ac", label: "SOURCE INSPECTION" },
  "quality-evaluation": { person: "quality-evaluation", equipment: "evaluation", accent: "#7bafb0", label: "EVALUATION DESK" },
};
export function ragStationArt(slug: string): StationArt {
  const art = stations[slug];
  if (!art) throw new Error(`Missing public RAG station artwork: ${slug}`);
  return art;
}
