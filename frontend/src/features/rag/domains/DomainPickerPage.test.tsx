import { render, screen } from "@testing-library/react";

import { ragDomainFilesPath, routes } from "../../../shared/routing/routes";
import { DomainPickerPage } from "./DomainPickerPage";

describe("DomainPickerPage", () => {
  it("renders server-provided domains and enables chat only when ready", () => {
    render(
      <DomainPickerPage
        domains={[
          domain({ slug: "asset-management", display_name: "자산운용" }),
          domain({ id: "domain-2", slug: "insurance", display_name: "보험" }),
        ]}
        isOwner={false}
      />,
    );

    expect(screen.getByText("전문 도메인을 선택하세요")).toBeVisible();
    expect(screen.getByRole("link", { name: "문서함 홈" })).toHaveAttribute("href", routes.workshopHome);
    expect(screen.getByRole("link", { name: "자산운용 대화 시작" })).toHaveAttribute(
      "href",
      "/workshop/rag/domains/asset-management/chat",
    );
    expect(screen.getByRole("link", { name: "보험 대화 시작" })).toHaveAttribute(
      "href",
      "/workshop/rag/domains/insurance/chat",
    );
  });

  it("keeps file access available when generation is not ready", () => {
    render(
      <DomainPickerPage
        domains={[
          domain({
            ready: false,
            readiness: {
              search_ready: true,
              answer_ready: false,
              service_ready: false,
              reason_codes: ["generation_not_configured"],
            },
          }),
        ]}
        isOwner={false}
      />,
    );

    expect(screen.getByRole("link", { name: "자산운용 파일함" })).toHaveAttribute(
      "href",
      ragDomainFilesPath("asset-management"),
    );
    expect(screen.queryByRole("link", { name: "자산운용 대화 시작" })).not.toBeInTheDocument();
    expect(screen.getByText("준비 필요")).toBeVisible();
    expect(screen.getByText("생성 구성 누락으로 대화가 제한됩니다.")).toBeVisible();
  });

  it("does not expose dead file link for inactive unbound domain", () => {
    render(
      <DomainPickerPage
        domains={[
          domain({
            active: false,
            ready: false,
            connection_version: null,
            workspace_options: [],
          }),
        ]}
        isOwner={false}
      />,
    );

    expect(screen.queryByRole("link", { name: "자산운용 파일함" })).not.toBeInTheDocument();
    expect(screen.getByText("연결 준비 중")).toBeVisible();
  });

  it("shows domain management shortcut only for owner", () => {
    render(
      <DomainPickerPage
        domains={[domain(), domain({ id: "domain-2", slug: "insurance", display_name: "보험" })]}
        isOwner
      />,
    );

    expect(screen.getAllByRole("link", { name: "자산운용 도메인 관리" })[0]).toHaveAttribute(
      "href",
      routes.adminRagDomains,
    );
    expect(screen.getAllByRole("link", { name: "보험 도메인 관리" })[0]).toHaveAttribute(
      "href",
      routes.adminRagDomains,
    );
  });

  it("renders clear instructions for empty domain list", () => {
    const { rerender } = render(<DomainPickerPage domains={[]} isOwner={false} />);

    expect(screen.getByRole("heading", { name: "사용 가능한 도메인이 아직 없습니다" })).toBeVisible();
    expect(screen.getByRole("link", { name: "문서함 홈" })).toHaveAttribute("href", routes.workshopHome);
    expect(screen.queryByRole("link", { name: "도메인 관리" })).not.toBeInTheDocument();

    rerender(<DomainPickerPage domains={[]} isOwner />);
    expect(screen.getByText("도메인 준비가 필요합니다")).toBeVisible();
    expect(screen.getByRole("link", { name: "도메인 관리" })).toHaveAttribute(
      "href",
      routes.adminRagDomains,
    );
  });
});

function domain(overrides: Record<string, unknown> = {}) {
  return {
    id: "domain-1",
    slug: "asset-management",
    display_name: "자산운용",
    description: "도메인 설명",
    active: true,
    ready: true,
    connection_version: { id: "connection-1", version: 2 },
    readiness: {
      search_ready: true,
      answer_ready: true,
      service_ready: true,
      reason_codes: [],
    },
    workspace_options: [
      { id: "workspace-1", name: "대표 작업공간", kind: "company" as const, expires_at: null },
    ],
    generation_execution_preview: {
      deployment_name: "실행 후보",
      model_name: "로컬 LLM",
      model_version: 3,
      provider: "local_openai_compatible" as const,
      disclosure_version: "on-premise-generation-v1",
      location: "on_premise" as const,
      external_transfer: false,
      disclosure: "질문 내용이 민감할 경우 별도 분류를 선택하세요.",
    },
    ...overrides,
  };
}
