import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "../../../shared/api/client";
import { ComparisonImportForm } from "./ComparisonImportForm";
import { importComparisonReport } from "./api";
import { comparisonFixture } from "./comparison.test-support";

vi.mock("./api", () => ({ importComparisonReport: vi.fn() }));
beforeEach(() => { vi.mocked(importComparisonReport).mockReset(); });

function file(read: () => Promise<string>, name = "comparison.json") {
  const value = new File(["{}"], name, { type: "application/json" });
  Object.defineProperty(value, "text", { value: read });
  return value;
}

async function openForm(onImported = vi.fn()) {
  const view = render(<ComparisonImportForm onImported={onImported} />);
  await userEvent.click(screen.getByText("결과 파일 가져오기", { selector: "summary" }));
  return view;
}

it("ignores a slow old file read when another file was selected", async () => {
  let finishOld!: (value: string) => void;
  const old = file(() => new Promise(resolve => { finishOld = resolve; }), "old.json");
  await openForm();
  const input = screen.getByLabelText("비교 결과 JSON 파일");
  await userEvent.upload(input, old);
  await userEvent.upload(input, file(async () => JSON.stringify({ ...comparisonFixture().report, title: "새 파일 제목" })));
  expect(await screen.findByText("제목: 새 파일 제목")).toBeVisible();
  await act(async () => finishOld(JSON.stringify(comparisonFixture().report)));
  expect(screen.queryByText("제목: 공개 합성 모델 비교")).not.toBeInTheDocument();
});

it("clears the selected preview on permission denial without exposing the provider message", async () => {
  vi.mocked(importComparisonReport).mockRejectedValue(new ApiError("private source payload", 403, "forbidden"));
  await openForm();
  await userEvent.upload(screen.getByLabelText("비교 결과 JSON 파일"), file(async () => JSON.stringify(comparisonFixture().report)));
  await screen.findByText("제목: 공개 합성 모델 비교");
  await userEvent.click(screen.getByRole("button", { name: "비교 결과 저장" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("접근 권한");
  expect(screen.queryByText("제목: 공개 합성 모델 비교")).not.toBeInTheDocument();
  expect(screen.queryByText("private source payload")).not.toBeInTheDocument();
  expect(importComparisonReport).toHaveBeenCalledTimes(1);
});

it("aborts an in-flight import on unmount and ignores its late response", async () => {
  let finish!: (value: ReturnType<typeof comparisonFixture>) => void;
  vi.mocked(importComparisonReport).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const onImported = vi.fn();
  const view = await openForm(onImported);
  await userEvent.upload(screen.getByLabelText("비교 결과 JSON 파일"), file(async () => JSON.stringify(comparisonFixture().report)));
  await screen.findByText("제목: 공개 합성 모델 비교");
  await userEvent.dblClick(screen.getByRole("button", { name: "비교 결과 저장" }));
  expect(importComparisonReport).toHaveBeenCalledTimes(1);
  const signal = vi.mocked(importComparisonReport).mock.calls[0][1]!;
  view.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => finish(comparisonFixture()));
  expect(onImported).not.toHaveBeenCalled();
});
