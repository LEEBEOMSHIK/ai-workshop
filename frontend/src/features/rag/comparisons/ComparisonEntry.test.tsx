import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigurationStudioPage } from "../configurations/ConfigurationStudioPage";
import { ExecutionListPage } from "../executions/ExecutionListPage";
import { searchExecutions } from "../executions/api";
import { comparisonPath, routes } from "../../../shared/routing/routes";

vi.mock("../executions/api", () => ({ searchExecutions: vi.fn() }));
vi.mock("./ComparisonListPanel", () => ({ ComparisonListPanel: () => <p>저장된 비교 목록 내용</p> }));

afterEach(() => vi.unstubAllGlobals());

it("opens stored comparisons only when that evaluation view is selected", async () => {
  render(<ConfigurationStudioPage initialTab="comparison" initialData={{ configurations: [], models: [], profiles: [], workspaces: [], runs: [] }} />);
  expect(screen.queryByText("저장된 비교 목록 내용")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "저장된 모델 비교" }));
  expect(screen.getByText("저장된 비교 목록 내용")).toBeVisible();
  expect(screen.getByRole("button", { name: "저장된 모델 비교" })).toHaveAttribute("aria-pressed", "true");
  expect(new URL(window.location.href).searchParams.get("view")).toBe("stored");
});

it("restores the saved comparison view without opening model execution preparation", () => {
  render(<ConfigurationStudioPage initialTab="comparison" initialComparisonView="stored" initialData={{ configurations: [], models: [], profiles: [], workspaces: [], runs: [] }} />);
  expect(screen.getByText("저장된 비교 목록 내용")).toBeVisible();
  expect(screen.queryByRole("heading", { name: "답변 비교 실험" })).not.toBeInTheDocument();
});

it("adds a separate navigation link without combining stored reports into execution statistics", async () => {
  vi.mocked(searchExecutions).mockResolvedValue({ items: [], total: 7, failed_count: 0, insufficient_count: 0,
    median_ms: null, p95_ms: null, duration_count: 0, duration_missing: 7, next_cursor: null });
  render(<ExecutionListPage />);
  expect(screen.getByRole("link", { name: "저장된 모델 비교" })).toHaveAttribute("href", routes.adminRagComparisons);
  await waitFor(() => expect(screen.getByLabelText("필터 전체 통계")).toHaveTextContent("7"));
  expect(searchExecutions).toHaveBeenCalledTimes(1);
});

it("encodes comparison route identifiers", () => {
  expect(comparisonPath("report/one?")).toBe("/admin/rag/comparisons/report%2Fone%3F");
});
