import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { EvidenceAnswerData, SearchResult } from "./api";
import { EvidenceAnswer } from "./EvidenceAnswer";

const workspaceNames = new Map([
  ["company-1", "전사 규정"],
  ["personal-1", "개인 리서치"],
]);

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
    expect(screen.getByText("전사 규정")).toBeVisible();
    expect(screen.getByText("제3조 › 환매")).toBeVisible();
    expect(screen.getByText("구성 버전 3")).toBeVisible();
    expect(screen.getByText("정확·키워드 일치")).toBeVisible();
    expect(screen.getByText("의미 일치")).toBeVisible();
    const warning = screen.getByText("원문 위치 정보가 완전하지 않습니다.");
    expect(warning).toBeVisible();
    expect(screen.getByText(answer.excerpt).closest("article")).toHaveAttribute(
      "aria-describedby",
      warning.id,
    );
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
    const cards = within(conflictSection).getAllByRole("article");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText("환매 규정.txt")).toBeVisible();
    expect(within(cards[1]).getByText("상품 약관.md")).toBeVisible();
    expect(screen.queryByText(/종합하면|따라서/)).not.toBeInTheDocument();
  });
});

function renderAnswer(result: SearchResult) {
  render(
    <MemoryRouter>
      <EvidenceAnswer result={result} workspaceNames={workspaceNames} />
    </MemoryRouter>,
  );
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
