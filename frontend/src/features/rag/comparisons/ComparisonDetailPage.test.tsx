import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ComparisonDetailPage } from "./ComparisonDetailPage";
import { getComparisonReport } from "./api";
import { comparisonFixture } from "./comparison.test-support";

vi.mock("./api", () => ({ getComparisonReport: vi.fn() }));

beforeEach(() => { vi.mocked(getComparisonReport).mockReset(); });

it("shows saved observations with tiny estimated cost, unknown billing and unmeasured TTFT", async () => {
  vi.mocked(getComparisonReport).mockResolvedValue(comparisonFixture());
  render(<ComparisonDetailPage id="synthetic-report" />);
  expect(await screen.findByRole("heading", { name: "공개 합성 모델 비교" })).toBeVisible();
  expect(screen.getByText("USD 0.000667")).toBeVisible();
  expect(screen.getByText("청구 미확인")).toBeVisible();
  expect(screen.getByText(/고유 질문 1개 · 완료 요청 4회/)).toBeVisible();
  expect(screen.getAllByText("미측정").length).toBeGreaterThan(0);
  expect(screen.queryByText("USD 0.00")).not.toBeInTheDocument();
  const local = screen.getByRole("article", { name: "synthetic-local · 첫 요청" });
  expect(within(local).getByText("기존 답변과 동일")).toBeVisible();
  expect(within(local).getByText("해당 질문 의미 검토: 미충족")).toBeVisible();
  expect(within(local).getByText("형식 검사: 통과")).toBeVisible();
  expect(within(local).getByText("인용 검사: 통과")).toBeVisible();
});

it("switches repetitions using the shared native selection and keeps each saved answer", async () => {
  vi.mocked(getComparisonReport).mockResolvedValue(comparisonFixture());
  render(<ComparisonDetailPage id="synthetic-report" />);
  await screen.findByRole("heading", { name: "공개 합성 모델 비교" });
  expect(screen.getByText("접수일 기준 4영업일 뒤 지급합니다.")).toBeVisible();
  await userEvent.click(screen.getByRole("radio", { name: "동일 입력 반복 · 2회차" }));
  expect(screen.getByText("반복에서도 일반 규칙을 설명합니다.")).toBeVisible();
  expect(screen.queryByText("접수일 기준 4영업일 뒤 지급합니다.")).not.toBeInTheDocument();
});

it("keeps each model in its own lane with first and repeat times together", async () => {
  vi.mocked(getComparisonReport).mockResolvedValue(comparisonFixture());
  render(<ComparisonDetailPage id="synthetic-report" />);
  const api = await screen.findByRole("table", { name: "OpenAI · synthetic-cloud — 처리 시간" });
  const local = screen.getByRole("table", { name: "Local · synthetic-local — 처리 시간" });
  expect(within(api).getByRole("row", { name: "완료 응답 3.781초 3.347초" })).toBeVisible();
  expect(within(local).getByRole("row", { name: "완료 응답 159.723초 11.123초" })).toBeVisible();
});

it("keeps API answers left in both repetitions even when local calls ran first", async () => {
  const detail = comparisonFixture();
  const original = detail.report.requests;
  detail.report.requests = [original[1], original[3], original[0], original[2]].map((request, index) => ({
    ...request, sequence: index + 1, provider: index < 2 ? "Ollama · 로컬" : "OpenAI API",
  }));
  const before = JSON.stringify(detail);
  vi.mocked(getComparisonReport).mockResolvedValue(detail);
  render(<ComparisonDetailPage id="synthetic-report" />);
  await screen.findByRole("heading", { name: "공개 합성 모델 비교" });
  let cards = screen.getAllByRole("article");
  expect(cards[0]).toHaveAccessibleName("synthetic-cloud · 첫 요청");
  expect(cards[1]).toHaveAccessibleName("synthetic-local · 첫 요청");
  expect(within(cards[0]).getByText("요청 3 · OpenAI API · 첫 요청")).toBeVisible();
  expect(within(cards[1]).getByText("요청 1 · Ollama · 로컬 · 첫 요청")).toBeVisible();
  expect(within(cards[0]).getByText("접수일 기준 4영업일 뒤 지급합니다.")).toBeVisible();
  expect(within(cards[1]).getByText("특정 날짜 예시만 설명한 답변입니다.")).toBeVisible();
  await userEvent.click(screen.getByRole("radio", { name: "동일 입력 반복 · 2회차" }));
  cards = screen.getAllByRole("article");
  expect(cards[0]).toHaveAccessibleName("synthetic-cloud · 동일 입력 반복 · 2회차");
  expect(cards[1]).toHaveAccessibleName("synthetic-local · 동일 입력 반복 · 2회차");
  expect(within(cards[0]).getByText("요청 4 · OpenAI API · 동일 입력 반복 · 2회차")).toBeVisible();
  expect(within(cards[1]).getByText("요청 2 · Ollama · 로컬 · 동일 입력 반복 · 2회차")).toBeVisible();
  expect(within(cards[0]).getByText("반복에서도 일반 규칙을 설명합니다.")).toBeVisible();
  expect(within(cards[1]).getByText("특정 날짜 예시만 설명한 답변입니다.")).toBeVisible();
  expect(JSON.stringify(detail)).toBe(before);
  expect(getComparisonReport).toHaveBeenCalledTimes(1);
});

it("shows cited text and builds the existing exact-location source link", async () => {
  vi.mocked(getComparisonReport).mockResolvedValue(comparisonFixture());
  render(<ComparisonDetailPage id="synthetic-report" />);
  await screen.findByRole("heading", { name: "공개 합성 모델 비교" });
  const cloud = screen.getByRole("article", { name: "synthetic-cloud · 첫 요청" });
  await userEvent.click(within(cloud).getByText("주장 1 · 인용 근거 1개", { selector: "summary" }));
  expect(within(cloud).getByText("접수일 T+4 영업일")).toBeVisible();
  const source = within(cloud).getByRole("link", { name: /e1 · 합성 문서 · 2쪽 원문/ });
  const url = new URL(source.getAttribute("href")!, "http://localhost");
  expect(url.pathname).toBe("/workshop/rag/sources/synthetic-version");
  expect(url.searchParams.get("projectionId")).toBe("synthetic-projection");
  expect(JSON.parse(url.searchParams.get("context")!)).toMatchObject({ evidenceUnitId: "synthetic-evidence", charStart: 0, charEnd: 12 });
});

it("clears the saved body before refresh and keeps it absent after access failure", async () => {
  vi.mocked(getComparisonReport).mockResolvedValueOnce(comparisonFixture()).mockRejectedValueOnce(new Error("denied"));
  render(<ComparisonDetailPage id="synthetic-report" />);
  await screen.findByRole("heading", { name: "공개 합성 모델 비교" });
  await userEvent.click(screen.getByRole("button", { name: "비교 기록 새로고침" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("현재 원문 접근 권한");
  expect(screen.queryByText("접수일 기준 4영업일 뒤 지급합니다.")).not.toBeInTheDocument();
});

it("does not allow an old in-flight response to populate a new route", async () => {
  let resolveOld!: (value: ReturnType<typeof comparisonFixture>) => void;
  vi.mocked(getComparisonReport).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
    .mockRejectedValueOnce(new Error("denied"));
  const view = render(<ComparisonDetailPage id="old" />);
  view.rerender(<ComparisonDetailPage id="new" />);
  await screen.findByRole("alert");
  await act(async () => resolveOld(comparisonFixture("old")));
  expect(screen.queryByText("언제 지급되나요? old")).not.toBeInTheDocument();
  await waitFor(() => expect(getComparisonReport).toHaveBeenCalledTimes(2));
});
