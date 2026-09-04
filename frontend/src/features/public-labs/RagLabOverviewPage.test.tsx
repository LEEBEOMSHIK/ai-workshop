import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { loginPath, routes } from "../../shared/routing/routes";
import { listRagLabAgents } from "./rag-lab-agents";
import { RagLabOverviewPage } from "./RagLabOverviewPage";

describe("RagLabOverviewPage", () => {
  it("shows the RAG chief and six implemented workers in pipeline order", () => {
    render(<RagLabOverviewPage />);

    expect(
      screen.getByRole("heading", { name: "RAG 기술 연구실" }),
    ).toBeVisible();
    const pipeline = screen.getByRole("region", { name: "RAG 작업 파이프라인" });
    expect(
      within(pipeline).getByRole("button", { name: "RAG 총괄에게 말 걸기" }),
    ).toBeVisible();

    const workerButtons = within(pipeline)
      .getAllByRole("listitem")
      .map((station) => within(station).getByRole("button"));
    expect(workerButtons).toHaveLength(6);
    expect(
      workerButtons.map((button) => button.getAttribute("aria-label")),
    ).toEqual([
      "구조 분석가 루미에게 말 걸기",
      "근거 설계자 토리에게 말 걸기",
      "색인 기술자 벡터에게 말 걸기",
      "검색 조율자 리프에게 말 걸기",
      "근거 검증자 하이라에게 말 걸기",
      "품질 분석가 메트릭에게 말 걸기",
    ]);
    expect(
      within(pipeline).queryByRole("button", { name: /생성|LLM|리랭커/u }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "로그인하고 현재 검색 기능 사용하기" }),
    ).toHaveAttribute("href", loginPath(routes.workshopRagSearch));
    expect(
      within(pipeline).getByText(
        "화면의 캐릭터는 각 기술 책임을 설명하며, 실제 처리는 검증된 서비스와 worker가 수행합니다.",
      ),
    ).toBeVisible();
  });

  it("lets nonadjacent workers explain their different responsibilities", async () => {
    const user = userEvent.setup();
    const agents = listRagLabAgents();
    const first = agents[0];
    const last = agents.at(-1);
    expect(first).toBeDefined();
    expect(last).toBeDefined();

    render(<RagLabOverviewPage />);

    await user.click(
      screen.getByRole("button", { name: `${first!.name}에게 말 걸기` }),
    );
    expect(screen.getByRole("dialog", { name: `${first!.name} 소개` })).toHaveTextContent(
      first!.currentWork,
    );
    await user.click(screen.getByRole("button", { name: "소개 닫기" }));

    await user.click(
      screen.getByRole("button", { name: `${last!.name}에게 말 걸기` }),
    );
    expect(screen.getByRole("dialog", { name: `${last!.name} 소개` })).toHaveTextContent(
      last!.handoff,
    );
  });

  it("keeps verified RAG capability visible without presenting the page as a demo", () => {
    render(<RagLabOverviewPage />);

    expect(screen.getByText("BM25 + bi-encoder + RRF")).toBeVisible();
    expect(
      screen.getByText("정확 일치와 의미 일치를 구분한 원문 하이라이트"),
    ).toBeVisible();
    expect(screen.queryByText(/데모/u)).not.toBeInTheDocument();
  });
});
