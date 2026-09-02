import { listPublicLabs, parsePublicLabCatalog } from "./catalog";

const validLab = {
  slug: "rag",
  name: "RAG 기술 연구실",
  eyebrow: "RETRIEVAL · EVIDENCE · GENERATION",
  description: "문서를 찾고 원문 근거와 함께 답하는 AI 검색 기술을 연구합니다.",
  status: "researching",
  statusLabel: "연구 중",
  href: "/labs/rag",
  manager: {
    name: "RAG 총괄",
    role: "RAG 기술 총괄",
    intro: "나는 문서 검색과 근거 기반 답변 기술을 관리하는 RAG 총괄 에이전트야.",
    invitation: "내가 관리하는 검색 기술과 해결 과정을 보러 갈래?",
    ctaLabel: "RAG 연구실 들어가기",
  },
};

describe("public Lab catalog", () => {
  it("loads only the current RAG Lab without speculative empty Labs", () => {
    expect(listPublicLabs()).toEqual([
      expect.objectContaining({
        slug: "rag",
        href: "/labs/rag",
        manager: expect.objectContaining({ role: "RAG 기술 총괄" }),
      }),
    ]);
  });

  it("rejects duplicate slugs and non-local or mismatched links", () => {
    expect(() => parsePublicLabCatalog({ labs: [validLab, validLab] })).toThrow(
      "public_lab_slug_duplicate",
    );
    expect(() =>
      parsePublicLabCatalog({
        labs: [{ ...validLab, href: "https://example.com" }],
      }),
    ).toThrow("public_lab_href_invalid");
    expect(() =>
      parsePublicLabCatalog({ labs: [{ ...validLab, href: "/labs/other" }] }),
    ).toThrow("public_lab_href_invalid");
  });

  it.each([
    [null, "public_lab_catalog_invalid"],
    [[], "public_lab_catalog_invalid"],
    [{}, "public_lab_labs_invalid"],
    [{ labs: {} }, "public_lab_labs_invalid"],
  ])("rejects malformed catalog roots", (input, error) => {
    expect(() => parsePublicLabCatalog(input)).toThrow(error);
  });

  it.each([
    ["slug", "public_lab_slug_invalid"],
    ["name", "public_lab_string_invalid"],
    ["eyebrow", "public_lab_string_invalid"],
    ["description", "public_lab_string_invalid"],
    ["statusLabel", "public_lab_string_invalid"],
    ["href", "public_lab_href_invalid"],
  ])("rejects blank required Lab fields", (field, error) => {
    expect(() =>
      parsePublicLabCatalog({ labs: [{ ...validLab, [field]: "  " }] }),
    ).toThrow(error);
  });

  it.each(["name", "role", "intro", "invitation", "ctaLabel"]) (
    "rejects blank required manager field %s",
    (field) => {
      expect(() =>
        parsePublicLabCatalog({
          labs: [{ ...validLab, manager: { ...validLab.manager, [field]: "  " } }],
        }),
      ).toThrow("public_lab_string_invalid");
    },
  );

  it("rejects malformed Lab values and objects", () => {
    expect(() =>
      parsePublicLabCatalog({ labs: [{ ...validLab, slug: "RAG" }] }),
    ).toThrow("public_lab_slug_invalid");
    expect(() =>
      parsePublicLabCatalog({ labs: [{ ...validLab, status: "draft" }] }),
    ).toThrow("public_lab_status_invalid");
    expect(() => parsePublicLabCatalog({ labs: [null] })).toThrow(
      "public_lab_invalid",
    );
    expect(() =>
      parsePublicLabCatalog({ labs: [{ ...validLab, manager: null }] }),
    ).toThrow("public_lab_manager_invalid");
  });

  it("copies parsed values and never exposes shared manifest state", () => {
    const parsed = parsePublicLabCatalog({ labs: [validLab] });
    expect(parsed[0]).not.toBe(validLab);
    expect(parsed[0].manager).not.toBe(validLab.manager);

    const first = listPublicLabs() as Array<(typeof parsed)[number]>;
    first[0].manager.name = "변경된 이름";
    first[0].name = "변경된 연구실";
    first.push(first[0]);

    expect(listPublicLabs()).toEqual([
      expect.objectContaining({
        name: "RAG 기술 연구실",
        manager: expect.objectContaining({ name: "RAG 총괄" }),
      }),
    ]);
  });
});
