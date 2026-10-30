import catalog from "./openai-model-catalog.json";

export interface OpenAiModelCatalogEntry {
  id: string;
  name: string;
  released_at: string;
  verified_at: string;
  documentation_url: string;
  supports: { responses: boolean; text_output: boolean; structured_outputs: boolean };
  parameter_notes: string[];
}

export function sortOpenAiModels(models: readonly OpenAiModelCatalogEntry[]): OpenAiModelCatalogEntry[] {
  return [...models].sort((left, right) => right.released_at.localeCompare(left.released_at, "en")
    || left.name.localeCompare(right.name, "en") || left.id.localeCompare(right.id, "en"));
}

export const openAiModelCatalog = catalog;
export const openAiModels = sortOpenAiModels(catalog.models);

export function findOpenAiModel(id: string): OpenAiModelCatalogEntry | undefined {
  return openAiModels.find(model => model.id === id);
}
