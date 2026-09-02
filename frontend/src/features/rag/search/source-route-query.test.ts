import { buildSourceHref, parseSourceQuery } from "./source-route-query";

describe("source route query", () => {
  it("round-trips highlight metadata without putting source text in the URL", () => {
    const href = buildSourceHref("asset version/1", "projection-1", [
      {
        kind: "keyword",
        evidence_unit_id: "evidence-1",
        text: "비공개 원문 문구",
        char_start: 2,
        char_end: 7,
        page: 3,
        bbox: [10, 20, 30, 40],
        score: null,
        warnings: [],
      },
      {
        kind: "semantic",
        evidence_unit_id: "evidence-1",
        text: "또 다른 비공개 원문",
        char_start: 9,
        char_end: 12,
        page: null,
        bbox: null,
        score: 0.91,
        warnings: [],
      },
    ], 3);

    expect(href).toMatch(/^\/app\/rag\/sources\/asset%20version%2F1\?/);
    expect(href).not.toContain("비공개");
    const parsed = parseSourceQuery(Object.fromEntries(new URL(href, "http://local").searchParams));
    expect(parsed).toEqual({
      projectionId: "projection-1",
      page: 3,
      highlights: [
        expect.objectContaining({ kind: "keyword", char_start: 2, char_end: 7, text: "" }),
        expect.objectContaining({ kind: "semantic", char_start: 9, char_end: 12, text: "" }),
      ],
    });
  });

  it("rejects malformed or excessive query values instead of accepting storage keys", () => {
    expect(parseSourceQuery({
      projectionId: "projection-1",
      keyword: "not-json",
      semantic: Array.from({ length: 25 }, () => "{}"),
      objectKey: "private/path.pdf",
      page: "-1",
    })).toEqual({ projectionId: "projection-1", page: null, highlights: [] });
  });
});
