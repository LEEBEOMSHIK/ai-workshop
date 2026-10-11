import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FlowchartsPage } from "./FlowchartsPage";
import { ragFlows } from "../rag/flows/catalog";
import { projectAgentFlows } from "../project-agents/flows";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const flows = [...ragFlows, ...projectAgentFlows];
const href = (category: string, id: string) => `/workshop/flows/${category}/${id}`;

async function openTechnicalSteps(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "기술 상세" }));
  const disclosure = screen.getByText("세부 처리·예외 흐름 보기");
  if (!disclosure.closest("details")?.open) await user.click(disclosure);
}

describe("flowcharts workspace viewer", () => {
  it("explains the real session stack with an architecture diagram before optional processing details", async () => {
    const user = userEvent.setup();
    render(<FlowchartsPage flows={flows} selectedFlow={ragFlows[2]} flowHref={href} />);
    expect(screen.queryByRole("region", { name: "기술 구성과 내부 동작" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "기술 상세" }));
    const architecture = screen.getByRole("region", { name: "기술 구성과 내부 동작" });
    expect(within(architecture).getByRole("figure", { name: "대화 세션 관리 기술 구성도" })).toBeVisible();
    expect(architecture).toHaveTextContent("PostgreSQL");
    expect(architecture).toHaveTextContent("SQLAlchemy");
    expect(within(architecture).getByText("이해를 돕는 가상 예시")).toBeVisible();
    expect(screen.queryByRole("region", { name: "단계 설명" })).not.toBeInTheDocument();
    await user.click(screen.getByText("세부 처리·예외 흐름 보기"));
    expect(screen.getByRole("region", { name: "단계 설명" })).toBeVisible();
  });

  it("shows a follow-up question example and separates model calls from application context management", async () => {
    const user = userEvent.setup();
    render(<FlowchartsPage flows={flows} selectedFlow={ragFlows[3]} flowHref={href} />);
    await user.click(screen.getByRole("button", { name: "기술 상세" }));
    const architecture = screen.getByRole("region", { name: "기술 구성과 내부 동작" });
    expect(architecture).toHaveTextContent("ContextPolicy");
    expect(within(architecture).getByText("이어서 질문")).toBeVisible();
    expect(within(architecture).getByText("사용 기술과 구현 방식").closest("details")).not.toHaveAttribute("open");
    await user.click(within(architecture).getByText("사용 기술과 구현 방식"));
    expect(architecture).toHaveTextContent("HTTPX");
    expect(architecture).toHaveTextContent("SDK");
  });

  it("starts with an overview and opens a large stage's technical flow", async () => {
    const user = userEvent.setup();
    render(<FlowchartsPage flows={flows} selectedFlow={ragFlows[1]} flowHref={href} />);
    expect(screen.getByRole("button", { name: "전체 흐름" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("region", { name: "단계 설명" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "기술 설명" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "원문 검색·근거 선택 기술 상세 보기" }));
    expect(screen.getByRole("button", { name: "기술 상세" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "권한 선필터·하이브리드 검색 단계" })).toHaveAttribute("aria-pressed", "true");
    const technical = screen.getByRole("region", { name: "기술 설명" });
    expect(technical).toHaveTextContent("BM25");
    expect(technical).toHaveTextContent("RRF");
    expect(within(technical).getByText("어떻게 작동하나요?")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "전체 흐름" }));
    expect(screen.queryByRole("region", { name: "단계 설명" })).not.toBeInTheDocument();
    await openTechnicalSteps(user);
    expect(screen.getByRole("button", { name: "권한 선필터·하이브리드 검색 단계" })).toHaveAttribute("aria-pressed", "true");
  });

  it("offers technology and the selected technology's flows before one full-width reader", () => {
    render(<FlowchartsPage flows={flows} selectedFlow={ragFlows[1]} flowHref={href} />);
    const categories = screen.getByRole("navigation", { name: "기술 선택" });
    expect(within(categories).getByRole("link", { name: "RAG" })).toHaveAttribute("aria-current", "true");
    expect(within(categories).getByRole("link", { name: "공통" })).toHaveAttribute("href", "/workshop/flows/common/development-agents");
    const navigation = screen.getByRole("navigation", { name: "흐름 선택" });
    expect(within(navigation).getByRole("link", { name: "멀티턴 문맥 관리" })).toHaveAttribute("href", "/workshop/flows/rag/multiturn");
    expect(within(navigation).getAllByRole("link")).toHaveLength(4);
    expect(within(navigation).getByRole("link", { name: "검색·답변 생성" })).toHaveAttribute("aria-current", "page");
    expect(within(navigation).queryByRole("link", { name: "개발 에이전트 관리" })).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "흐름 분류" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("figure")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "검색·답변 생성", level: 2 })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "대화 세션 관리", level: 2 })).not.toBeInTheDocument();
    expect(screen.getByText(/실제 실행 상태/)).toBeVisible();
  });

  it("keeps deep-link category selection and exposes only common flows", () => {
    render(<FlowchartsPage flows={flows} selectedFlow={projectAgentFlows[0]} flowHref={href} />);
    const categories = screen.getByRole("navigation", { name: "기술 선택" });
    expect(within(categories).getByRole("link", { name: "공통" })).toHaveAttribute("aria-current", "true");
    expect(within(categories).getByRole("link", { name: "RAG" })).toHaveAttribute("href", "/workshop/flows/rag/ingestion");
    const navigation = screen.getByRole("navigation", { name: "흐름 선택" });
    expect(within(navigation).getAllByRole("link")).toHaveLength(1);
    expect(within(navigation).getByRole("link", { name: "개발 에이전트 관리" })).toHaveAttribute("aria-current", "page");
  });

  it("allows keyboard step selection and exposes one detail region", async () => {
    const user = userEvent.setup();
    render(<FlowchartsPage flows={flows} selectedFlow={ragFlows[1]} flowHref={href} />);
    await openTechnicalSteps(user);
    const step = screen.getByRole("button", { name: "인용 검증 단계" });
    step.focus();
    await user.keyboard("{Enter}");
    expect(step).toHaveAttribute("aria-pressed", "true");
    const detail = screen.getByRole("region", { name: "단계 설명" });
    expect(detail).toHaveTextContent("검증 실패한 초안을 정상 답변으로 노출하지 않습니다.");
    expect(within(detail).getByText("입력")).toBeVisible();
    expect(within(detail).getByText("처리")).toBeVisible();
    expect(within(detail).getByText("결과")).toBeVisible();
    expect(screen.getAllByRole("region", { name: "단계 설명" })).toHaveLength(1);
  });

  it("resets the selected step when another flow is rendered", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<FlowchartsPage flows={flows} selectedFlow={ragFlows[1]} flowHref={href} />);
    await openTechnicalSteps(user);
    await user.click(screen.getByRole("button", { name: "인용 검증 단계" }));
    rerender(<FlowchartsPage flows={flows} selectedFlow={ragFlows[2]} flowHref={href} />);
    expect(screen.getByRole("button", { name: "전체 흐름" })).toHaveAttribute("aria-pressed", "true");
    await openTechnicalSteps(user);
    expect(screen.getByRole("button", { name: "새 대화 또는 기존 세션 선택 단계" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "단계 설명" })).toHaveTextContent("메뉴 클릭만으로 DB 세션을 만들지 않습니다.");
  });

  it.each(["인용 검증 단계", "답변 생성 완료 → 인용 검증"])("brings offscreen details into view and returns to the selected node: %s", async (name) => {
    const user = userEvent.setup();
    render(<FlowchartsPage flows={flows} selectedFlow={ragFlows[1]} flowHref={href} />);
    await openTechnicalSteps(user);
    const detail = screen.getByRole("region", { name: "단계 설명" });
    vi.spyOn(detail, "getBoundingClientRect").mockReturnValue({ x: 0, y: 2000, top: 2000, bottom: 2500, left: 0, right: 360, width: 360, height: 500, toJSON() {} });
    const scroll = vi.fn();
    Object.defineProperty(detail, "scrollIntoView", { configurable: true, value: scroll });
    const selectedNode = screen.getByRole("button", { name: "인용 검증 단계" });
    Object.defineProperty(selectedNode, "scrollIntoView", { configurable: true, value: vi.fn() });
    await user.click(screen.getByRole("button", { name }));
    expect(detail).toHaveTextContent("검증 실패한 초안을 정상 답변으로 노출하지 않습니다.");
    expect(detail).toHaveFocus();
    expect(scroll).toHaveBeenCalledWith({ block: "start", behavior: "smooth" });
    expect(screen.getAllByRole("region", { name: "단계 설명" })).toHaveLength(1);
    await user.click(within(detail).getByRole("button", { name: "선택 단계로 돌아가기" }));
    expect(selectedNode).toHaveFocus();
    expect(selectedNode).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps desktop selection at its node when details are already visible", async () => {
    const user = userEvent.setup();
    render(<FlowchartsPage flows={flows} selectedFlow={ragFlows[1]} flowHref={href} />);
    await openTechnicalSteps(user);
    const detail = screen.getByRole("region", { name: "단계 설명" });
    vi.spyOn(detail, "getBoundingClientRect").mockReturnValue({ x: 600, y: 100, top: 100, bottom: 500, left: 600, right: 950, width: 350, height: 400, toJSON() {} });
    const step = screen.getByRole("button", { name: "인용 검증 단계" });
    await user.click(step);
    expect(step).toHaveFocus();
    expect(screen.queryByRole("button", { name: "선택 단계로 돌아가기" })).not.toBeInTheDocument();
  });

  it("renders long descriptions and markup as text, with text alternatives initially collapsed", () => {
    const flow = { ...ragFlows[1], summary: "<img src=x onerror=alert(1)> 아주긴조건".repeat(4) };
    render(<FlowchartsPage flows={flows} selectedFlow={flow} flowHref={href} />);
    expect(screen.getByText(flow.summary)).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("텍스트로 흐름 읽기").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("RAG 검색·생성 설계")).toBeVisible();
  });

  it("keeps focus at the desktop node when a long technical detail begins inside the viewport", async () => {
    const user = userEvent.setup();
    render(<FlowchartsPage flows={flows} selectedFlow={ragFlows[1]} flowHref={href} />);
    await openTechnicalSteps(user);
    const detail = screen.getByRole("region", { name: "단계 설명" });
    vi.spyOn(detail, "getBoundingClientRect").mockReturnValue({ x: 600, y: 100, top: 100, bottom: 1500, left: 600, right: 950, width: 350, height: 1400, toJSON() {} });
    const step = screen.getByRole("button", { name: "인용 검증 단계" });
    await user.click(step);
    expect(step).toHaveFocus();
    expect(screen.queryByRole("button", { name: "선택 단계로 돌아가기" })).not.toBeInTheDocument();
  });
});
