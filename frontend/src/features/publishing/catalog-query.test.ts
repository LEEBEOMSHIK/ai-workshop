import { catalogPath, normalizeCatalogQuery, studyCatalogPath, catalogPages } from "./catalog-query";

describe("catalog query", () => {
  it.each(["0", "-1", "1.5", "1e2", "1000001", "oops", ["2", "3"]])("rejects invalid pages %s", (page) => {
    expect(normalizeCatalogQuery({ page, topic: "retrieval" })).toEqual({ page: 1, topic: "retrieval" });
  });
  it("accepts bounded integers and unknown valid topic keys", () => {
    expect(normalizeCatalogQuery({ page: "1000000", topic: "new-topic" })).toEqual({ page: 1000000, topic: "new-topic" });
  });
  it.each(["https://evil.test", "rag&x=1", "a".repeat(129), ["rag", "ocr"]])("ignores malformed topics %s", (topic) => {
    expect(normalizeCatalogQuery({ topic })).toEqual({ page: 1 });
  });
  it("builds only local page and topic links", () => {
    expect(catalogPath({ page: 2, topic: "rag" })).toBe("/labs/rag/studies?topic=rag&page=2");
    expect(catalogPath()).toBe("/labs/rag/studies");
    expect(studyCatalogPath("hybrid-search", { page: 2, topic: "rag" })).toBe("/studies/hybrid-search?topic=rag&page=2");
  });
  it("bounds page windows while retaining the first and last page", () => {
    expect(catalogPages(50, 100)).toEqual([1, "gap-before", 48, 49, 50, 51, 52, "gap-after", 100]);
    expect(catalogPages(1, 2)).toEqual([1, 2]);
    expect(catalogPages(1, 0)).toEqual([]);
  });
});
