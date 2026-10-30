import { describe, expect, it } from "vitest";
import { findOpenAiModel, sortOpenAiModels, type OpenAiModelCatalogEntry } from "./openai-model-catalog";

function entry(id: string, name: string, releasedAt: string): OpenAiModelCatalogEntry {
  return { id, name, released_at: releasedAt, verified_at: "2026-10-30",
    documentation_url: `https://developers.openai.com/api/docs/models/${id}`,
    supports: { responses: true, text_output: true, structured_outputs: true }, parameter_notes: [] };
}

describe("public OpenAI model catalog", () => {
  it("orders by release date descending then name and leaves the versioned source unchanged", () => {
    const original = [entry("beta", "Beta", "2026-09-22"), entry("new", "Newest", "2026-10-26"),
      entry("old", "Aardvark", "2026-09-03"), entry("alpha", "Alpha", "2026-09-22")];
    expect(sortOpenAiModels(original).map(model => model.id)).toEqual(["new", "alpha", "beta", "old"]);
    expect(original.map(model => model.id)).toEqual(["beta", "new", "old", "alpha"]);
  });

  it("uses ID as a stable final tie breaker and accepts an empty catalog", () => {
    expect(sortOpenAiModels([entry("z", "Same", "2026-09-22"), entry("a", "Same", "2026-09-22")]).map(model => model.id)).toEqual(["a", "z"]);
    expect(sortOpenAiModels([])).toEqual([]);
  });

  it("requires an exact catalog ID instead of falling back to the newest model", () => {
    expect(findOpenAiModel("")).toBeUndefined();
    expect(findOpenAiModel("not-in-catalog")).toBeUndefined();
    expect(findOpenAiModel("gpt-6.1-terra")?.id).toBe("gpt-6.1-terra");
  });
});
