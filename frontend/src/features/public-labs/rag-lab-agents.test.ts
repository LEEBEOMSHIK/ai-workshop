import { listRagLabAgents, parseRagLabAgents } from "./rag-lab-agents";

const validAgent = {
  slug: "document-structure",
  name: "구조 분석가 루미",
  role: "파싱·구조 분석 담당",
  statusLabel: "작업 중",
  eyebrow: "PARSE · STRUCTURE",
  intro: "나는 문서의 구조를 읽어 검색 가능한 형태로 정리하는 담당 에이전트야.",
  currentWork: "Markdown, TXT와 텍스트 PDF에서 제목과 본문 구조를 보존해 추출하고 있어.",
  inputOutput: "원본 문서를 받아 구조화된 파싱 결과와 원문 위치 정보를 전달해.",
  handoff: "정리한 문서는 청킹 담당에게 넘겨 근거 단위로 나누게 해.",
};

describe("RAG Lab agent registry", () => {
  it("loads the six implemented workers in pipeline order", () => {
    const agents = listRagLabAgents();

    expect(agents.map(({ slug, role }) => ({ slug, role }))).toEqual([
      { slug: "document-structure", role: "파싱·구조 분석 담당" },
      { slug: "chunking", role: "청킹 담당" },
      { slug: "embedding-indexing", role: "임베딩·색인 담당" },
      { slug: "retrieval-fusion", role: "검색·융합 담당" },
      { slug: "evidence-highlighting", role: "근거·하이라이트 담당" },
      { slug: "quality-evaluation", role: "품질 평가 담당" },
    ]);
    expect(agents).toHaveLength(6);
    expect(agents.map((agent) => agent.role).join(" ")).not.toMatch(
      /생성|LLM|리랭커/u,
    );
    expect(agents.map((agent) => agent.intro).join(" ")).not.toContain(
      "담당 에이전트",
    );
  });

  it("rejects duplicate slugs", () => {
    expect(() => parseRagLabAgents({ agents: [validAgent, validAgent] })).toThrow(
      "rag_lab_agent_slug_duplicate",
    );
  });

  it.each([
    [null, "rag_lab_agent_registry_invalid"],
    [[], "rag_lab_agent_registry_invalid"],
    [{}, "rag_lab_agents_invalid"],
    [{ agents: {} }, "rag_lab_agents_invalid"],
  ])("rejects malformed registry roots", (input, error) => {
    expect(() => parseRagLabAgents(input)).toThrow(error);
  });

  it.each([
    "name",
    "role",
    "statusLabel",
    "eyebrow",
    "intro",
    "currentWork",
    "inputOutput",
    "handoff",
  ])("rejects blank required worker field %s", (field) => {
    expect(() =>
      parseRagLabAgents({ agents: [{ ...validAgent, [field]: "  " }] }),
    ).toThrow("rag_lab_agent_string_invalid");
  });

  it("rejects invalid slugs and extra fields", () => {
    expect(() =>
      parseRagLabAgents({ agents: [{ ...validAgent, slug: "Document Worker" }] }),
    ).toThrow("rag_lab_agent_slug_invalid");
    expect(() =>
      parseRagLabAgents({ agents: [{ ...validAgent, futureState: "ready" }] }),
    ).toThrow("rag_lab_agent_invalid");
  });

  it("returns defensive copies instead of shared manifest objects", () => {
    const first = listRagLabAgents() as Array<ReturnType<typeof listRagLabAgents>[number]>;
    first[0].name = "변경된 이름";
    first.push(first[0]);

    expect(listRagLabAgents()).toHaveLength(6);
    expect(listRagLabAgents()[0]?.name).toBe("구조 분석가 루미");
  });
});
