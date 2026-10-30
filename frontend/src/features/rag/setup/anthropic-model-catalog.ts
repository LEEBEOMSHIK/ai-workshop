import catalog from "./anthropic-model-catalog.json";

export const anthropicModelCatalog = catalog;
export const anthropicModels = [...catalog.models].sort((a, b) => b.released_at.localeCompare(a.released_at, "en")
  || a.name.localeCompare(b.name, "en") || a.id.localeCompare(b.id, "en"));
