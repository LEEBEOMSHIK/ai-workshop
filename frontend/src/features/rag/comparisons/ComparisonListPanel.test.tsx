import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ComparisonListPanel } from "./ComparisonListPanel";
import { importComparisonReport, listComparisonReports } from "./api";
import { comparisonFixture, comparisonSummary } from "./comparison.test-support";

vi.mock("./api", () => ({ listComparisonReports: vi.fn(), importComparisonReport: vi.fn() }));
beforeEach(() => { vi.mocked(listComparisonReports).mockReset(); vi.mocked(importComparisonReport).mockReset(); });

function jsonFile(text: string) {
  const file = new File([text], "comparison.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: async () => text, configurable: true });
  return file;
}

it("lists saved comparison metadata and its precise estimate without starting a request", async () => {
  vi.mocked(listComparisonReports).mockResolvedValue({ items: [comparisonSummary()] });
  render(<ComparisonListPanel />);
  expect(await screen.findByRole("link", { name: "공개 합성 모델 비교" })).toHaveAttribute("href", "/admin/rag/comparisons/synthetic-report");
  expect(screen.getByText(/USD 0.000667/)).toBeVisible();
  expect(importComparisonReport).not.toHaveBeenCalled();
});

it("clears the old list on refresh failure", async () => {
  vi.mocked(listComparisonReports).mockResolvedValueOnce({ items: [comparisonSummary()] }).mockRejectedValueOnce(new Error("denied"));
  render(<ComparisonListPanel />);
  await screen.findByRole("link", { name: "공개 합성 모델 비교" });
  await userEvent.click(screen.getByRole("button", { name: "비교 목록 새로고침" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("link", { name: "공개 합성 모델 비교" })).not.toBeInTheDocument();
});

it("previews a bounded JSON import and saves only after the explicit action", async () => {
  vi.mocked(listComparisonReports).mockResolvedValue({ items: [] });
  vi.mocked(importComparisonReport).mockResolvedValue(comparisonFixture());
  render(<ComparisonListPanel />);
  await screen.findByText("저장된 모델 비교가 없습니다.");
  await userEvent.click(screen.getByText("결과 파일 가져오기", { selector: "summary" }));
  const file = jsonFile(JSON.stringify(comparisonFixture().report));
  await userEvent.upload(screen.getByLabelText("비교 결과 JSON 파일"), file);
  expect(await screen.findByText("제목: 공개 합성 모델 비교")).toBeVisible();
  expect(screen.getByText("완료 요청: 4회")).toBeVisible();
  expect(importComparisonReport).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "비교 결과 저장" }));
  await waitFor(() => expect(importComparisonReport).toHaveBeenCalledTimes(1));
  expect(importComparisonReport).toHaveBeenCalledWith(comparisonFixture().report, expect.any(AbortSignal));
});

it("rejects invalid JSON and clears a previously valid preview", async () => {
  vi.mocked(listComparisonReports).mockResolvedValue({ items: [] });
  render(<ComparisonListPanel />);
  await screen.findByText("저장된 모델 비교가 없습니다.");
  await userEvent.click(screen.getByText("결과 파일 가져오기", { selector: "summary" }));
  const input = screen.getByLabelText("비교 결과 JSON 파일");
  await userEvent.upload(input, jsonFile(JSON.stringify(comparisonFixture().report)));
  await screen.findByText("제목: 공개 합성 모델 비교");
  await userEvent.upload(input, jsonFile("{invalid"));
  expect(await screen.findByRole("alert")).toHaveTextContent("JSON");
  expect(screen.queryByText("제목: 공개 합성 모델 비교")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "비교 결과 저장" })).toBeDisabled();
});

it("does not read files over the two MiB import limit", async () => {
  vi.mocked(listComparisonReports).mockResolvedValue({ items: [] });
  render(<ComparisonListPanel />);
  await screen.findByText("저장된 모델 비교가 없습니다.");
  await userEvent.click(screen.getByText("결과 파일 가져오기", { selector: "summary" }));
  const file = jsonFile("{}"), read = vi.fn();
  Object.defineProperty(file, "size", { value: 2 * 1024 * 1024 + 1 });
  Object.defineProperty(file, "text", { value: read, configurable: true });
  await userEvent.upload(screen.getByLabelText("비교 결과 JSON 파일"), file);
  expect(await screen.findByRole("alert")).toHaveTextContent("2MiB");
  expect(read).not.toHaveBeenCalled();
});
