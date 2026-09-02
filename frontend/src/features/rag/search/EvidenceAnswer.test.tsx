import { render, screen, within } from "@testing-library/react";

import type { EvidenceAnswerData, SearchResult, SearchSubmissionContext } from "./api";
import { EvidenceAnswer } from "./EvidenceAnswer";

const submissionContext: SearchSubmissionContext = {
  query: "환매 제한은 무엇인가요?",
  configuration: {
    id: "configuration-1",
    versionId: "configuration-version-1",
    version: 3,
    name: "승인된 하이브리드",
    experimental: false,
  },
  workspaces: [
    { id: "company-1", name: "전사 규정", kind: "company" },
    { id: "personal-1", name: "개인 리서치", kind: "personal" },
    { id: "temporary-1", name: "임시 검토", kind: "temporary" },
  ],
  folders: [{ id: "folder-1", name: "상품 규정", workspaceId: "company-1" }],
  experimentalConsent: false,
};

describe("EvidenceAnswer", () => {
  it("renders a supported extract with immutable provenance and distinct keyword and semantic labels", () => {
    const answer = evidence({
      warnings: ["provenance_incomplete"],
      highlights: [
        highlight("keyword", "환매 요청", 0, 5),
        highlight("semantic", "영업일 기준 3일", 6, 15),
      ],
    });

    renderAnswer(searchResult({ answer, status: "supported" }));

    expect(screen.getByRole("status")).toHaveTextContent("근거로 답변할 수 있습니다");
    expect(screen.getByRole("heading", { name: "확인된 근거" })).toBeVisible();
    expect(screen.getByText("환매 규정.txt")).toBeVisible();
    expect(screen.getByText("버전 4")).toBeVisible();
    expect(screen.getByText("전사")).toBeVisible();
    expect(screen.getByText(/전사 규정/)).toHaveTextContent("company-1");
    expect(screen.getByText("제3조 › 환매")).toBeVisible();
    const configuration = screen.getByLabelText("사용한 저장 RAG 구성");
    expect(configuration).toHaveTextContent("승인된 하이브리드");
    expect(configuration).toHaveTextContent("configuration-1");
    expect(configuration).toHaveTextContent("configuration-version-1");
    expect(configuration).toHaveTextContent("버전 3");
    expect(configuration).toHaveTextContent("일반 실행");
    expect(screen.getByText("정확·키워드 일치")).toBeVisible();
    expect(screen.getByText("의미 일치")).toBeVisible();
    const sourceLink = screen.getByRole("link", { name: "원문에서 확인" });
    expect(sourceLink).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/workshop\/rag\/sources\/asset-version-1\?projectionId=projection-1/),
    );
    expect(sourceLink.getAttribute("href")).toContain("keyword=");
    expect(sourceLink.getAttribute("href")).toContain("semantic=");
    const warning = screen.getByText("원문 위치 정보가 완전하지 않습니다.");
    expect(warning).toBeVisible();
    expect(screen.getByText(answer.excerpt).closest("article")).toHaveAttribute(
      "aria-describedby",
      warning.id,
    );
  });

  it("associates a supported result warning once without duplicating a source warning", () => {
    renderAnswer(
      searchResult({
        answer: evidence({ warnings: [] }),
        status: "supported",
        warnings: ["projection_provenance_incomplete"],
      }),
    );

    const state = screen.getByRole("status");
    const warnings = screen.getAllByText(
      "검색 결과에 원문 위치 정보가 완전하지 않은 항목이 있습니다.",
    );
    expect(warnings).toHaveLength(1);
    expect(state).toHaveAttribute("aria-describedby", warnings[0].id);
    expect(screen.queryByText("원문 위치 정보가 완전하지 않습니다.")).not.toBeInTheDocument();
  });

  it("keeps related-looking content out of the answer when evidence is insufficient", () => {
    renderAnswer(
      searchResult({
        answer: evidence(),
        status: "insufficient_evidence",
        warnings: ["projection_provenance_incomplete"],
      }),
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("직접 답할 근거가 부족합니다");
    expect(status).toHaveTextContent("원문 위치 정보가 완전하지 않은 후보는 답변 근거에서 제외했습니다.");
    expect(screen.queryByRole("heading", { name: "확인된 근거" })).not.toBeInTheDocument();
    expect(screen.queryByText("환매 요청은 영업일 기준 3일 전에 접수해야 합니다.")).not.toBeInTheDocument();
  });

  it("renders conflicting excerpts as separate source cards without a synthesized answer", () => {
    const first = evidence();
    const second = evidence({
      excerpt: "특정 상품은 환매 신청이 제한될 수 있습니다.",
      source: {
        ...first.source,
        asset_version_id: "asset-version-2",
        asset_version_number: 2,
        chunk_id: "chunk-2",
        evidence_unit_id: "evidence-2",
        element_id: "element-2",
        projection_id: "projection-2",
        title: "상품 약관.md",
        workspace_id: "personal-1",
        folder_id: null,
        location: { ...first.source.location, element_id: "element-2" },
      },
    });

    renderAnswer(
      searchResult({
        answer: first,
        conflict_state: "separate_sources",
        conflicts: [first, second],
        status: "supported",
      }),
    );

    const conflictSection = screen.getByRole("region", { name: "충돌하는 근거" });
    expect(within(conflictSection).getByLabelText("사용한 저장 RAG 구성")).toHaveTextContent(
      "configuration-version-1",
    );
    const cards = within(conflictSection).getAllByRole("article");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText("환매 규정.txt")).toBeVisible();
    expect(within(cards[1]).getByText("상품 약관.md")).toBeVisible();
    expect(within(cards[0]).getByText("전사")).toBeVisible();
    expect(within(cards[1]).getByText("개인")).toBeVisible();
    expect(screen.queryByText(/종합하면|따라서/)).not.toBeInTheDocument();
  });

  it("shows the authorized folder identity and exact ids without inventing missing labels", () => {
    const withFolder = evidence({
      source: {
        ...evidence().source,
        folder_id: "folder-1",
      },
    });
    const unknownScope = evidence({
      source: {
        ...evidence().source,
        document_id: "document-unknown",
        asset_version_id: "asset-version-unknown",
        evidence_unit_id: "evidence-unknown",
        workspace_id: "workspace-unknown",
        folder_id: "folder-unknown",
      },
    });
    const temporaryScope = evidence({
      source: {
        ...evidence().source,
        document_id: "document-temporary",
        asset_version_id: "asset-version-temporary",
        evidence_unit_id: "evidence-temporary",
        workspace_id: "temporary-1",
        folder_id: null,
      },
    });

    renderAnswer(
      searchResult({
        answer: withFolder,
        conflict_state: "separate_sources",
        conflicts: [withFolder, unknownScope, temporaryScope],
      }),
    );

    expect(screen.getAllByText(/상품 규정/)[0]).toHaveTextContent("folder-1");
    expect(screen.getByText(/workspace-unknown/)).toBeVisible();
    expect(screen.getByText(/folder-unknown/)).toBeVisible();
    expect(screen.getByText("임시")).toBeVisible();
    expect(screen.getByText(/임시 검토/)).toHaveTextContent("temporary-1");
    expect(screen.queryByText("알 수 없는 지식 공간")).not.toBeInTheDocument();
  });
});

function renderAnswer(result: SearchResult) {
  render(<EvidenceAnswer result={result} context={submissionContext} />);
}

function searchResult(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    status: "supported",
    answer: evidence(),
    conflict_state: "none",
    conflicts: [],
    warnings: [],
    related_sources: [],
    configuration_version: {
      configuration_id: "configuration-1",
      version_id: "configuration-version-1",
      version: 3,
    },
    experimental: false,
    ...overrides,
  };
}

function evidence(overrides: Partial<EvidenceAnswerData> = {}): EvidenceAnswerData {
  return {
    excerpt: "환매 요청은 영업일 기준 3일 전에 접수해야 합니다.",
    source: {
      document_id: "document-1",
      asset_version_id: "asset-version-1",
      asset_version_number: 4,
      workspace_id: "company-1",
      folder_id: null,
      projection_id: "projection-1",
      chunk_id: "chunk-1",
      evidence_unit_id: "evidence-1",
      element_id: "element-1",
      title: "환매 규정.txt",
      media_type: "text/plain",
      section_path: ["제3조", "환매"],
      location: {
        element_id: "element-1",
        page: null,
        char_start: 0,
        char_end: 29,
        bbox: null,
      },
    },
    highlights: [],
    keyword_coverage: 0.8,
    semantic_score: 0.91,
    warnings: [],
    ...overrides,
  };
}

function highlight(
  kind: "keyword" | "semantic",
  text: string,
  charStart: number,
  charEnd: number,
) {
  return {
    kind,
    evidence_unit_id: "evidence-1",
    text,
    char_start: charStart,
    char_end: charEnd,
    page: null,
    bbox: null,
    score: kind === "semantic" ? 0.91 : null,
    warnings: [],
  };
}
