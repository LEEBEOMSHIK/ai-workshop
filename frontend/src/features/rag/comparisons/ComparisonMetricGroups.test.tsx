import { render, screen, within } from "@testing-library/react";
import { ComparisonMetricGroups } from "./ComparisonMetricGroups";
import { comparisonFixture } from "./comparison.test-support";

it("keeps API observations on the left and local observations on the right across repetitions", () => {
  render(<ComparisonMetricGroups requests={comparisonFixture().report.requests} kind="timing" />);
  const [api, local] = screen.getAllByRole("table");
  expect(api).toHaveAccessibleName("OpenAI · synthetic-cloud — 처리 시간");
  expect(local).toHaveAccessibleName("Local · synthetic-local — 처리 시간");
  expect(within(api).getAllByRole("columnheader").map(node => node.textContent)).toEqual([
    "측정 항목", "첫 요청1회차 · 요청 1", "동일 입력 반복2회차 · 요청 3",
  ]);
  expect(within(api).getByRole("row", { name: "완료 응답 3.781초 3.347초" })).toBeVisible();
  expect(within(local).getByRole("row", { name: "완료 응답 159.723초 11.123초" })).toBeVisible();
  expect(within(api).getByRole("row", { name: "입력 처리 미측정 미측정" })).toBeVisible();
  expect(within(local).getByRole("row", { name: "입력 처리 133.632초 0.075초" })).toBeVisible();
  expect(within(api).queryByText("159.723초")).not.toBeInTheDocument();
  expect(within(local).queryByText("3.781초")).not.toBeInTheDocument();
});

it("separates usage metrics and preserves zero, unreported, estimated and inapplicable amounts", () => {
  render(<ComparisonMetricGroups requests={comparisonFixture().report.requests} kind="usage" />);
  const api = screen.getByRole("table", { name: "OpenAI · synthetic-cloud — 사용량·비용" });
  const local = screen.getByRole("table", { name: "Local · synthetic-local — 사용량·비용" });
  expect(within(api).getByRole("row", { name: "입력 토큰 2,630 2,630" })).toBeVisible();
  expect(within(api).getByRole("row", { name: "캐시 읽기 토큰 0 0" })).toBeVisible();
  expect(within(local).getByRole("row", { name: "캐시 읽기 토큰 미보고 미보고" })).toBeVisible();
  expect(within(api).getByRole("row", { name: "예상 API 비용 USD 0.0003255 USD 0.0003415" })).toBeVisible();
  expect(within(local).getByRole("row", { name: "예상 API 비용 API 청구 해당 없음 API 청구 해당 없음" })).toBeVisible();
  expect(within(api).getByRole("row", { name: "실제 청구액 미확인 미확인" })).toBeVisible();
  expect(within(local).getByRole("row", { name: "실제 청구액 해당 없음 해당 없음" })).toBeVisible();
  expect(within(api).getByRole("row", { name: "출력 토큰 125 157" })).toBeVisible();
});

it.each(["timing", "usage"] as const)("keeps API first in %s when both local calls were recorded first", kind => {
  const original = comparisonFixture().report.requests;
  const requests = [original[1], original[3], original[0], original[2]].map((request, index) => ({
    ...request, sequence: index + 1, provider: index < 2 ? "Ollama · 로컬" : "OpenAI API",
  }));
  const before = JSON.stringify(requests);
  render(<ComparisonMetricGroups requests={requests} kind={kind} />);
  const subject = kind === "timing" ? "처리 시간" : "사용량·비용";
  const [api, local] = screen.getAllByRole("table");
  expect(api).toHaveAccessibleName(`OpenAI API · synthetic-cloud — ${subject}`);
  expect(local).toHaveAccessibleName(`Ollama · 로컬 · synthetic-local — ${subject}`);
  expect(within(api).getAllByRole("columnheader").map(node => node.textContent)).toEqual([
    "측정 항목", "첫 요청1회차 · 요청 3", "동일 입력 반복2회차 · 요청 4",
  ]);
  expect(within(local).getAllByRole("columnheader").map(node => node.textContent)).toEqual([
    "측정 항목", "첫 요청1회차 · 요청 1", "동일 입력 반복2회차 · 요청 2",
  ]);
  if (kind === "timing") {
    expect(within(api).getByRole("row", { name: "완료 응답 3.781초 3.347초" })).toBeVisible();
    expect(within(local).getByRole("row", { name: "완료 응답 159.723초 11.123초" })).toBeVisible();
  } else {
    expect(within(api).getByRole("row", { name: "예상 API 비용 USD 0.0003255 USD 0.0003415" })).toBeVisible();
    expect(within(local).getByRole("row", { name: "예상 API 비용 API 청구 해당 없음 API 청구 해당 없음" })).toBeVisible();
  }
  expect(JSON.stringify(requests)).toBe(before);
});

it("keeps unknown provider positions and stable order within API and local groups", () => {
  const [api, local] = comparisonFixture().report.requests;
  const requests = [
    { ...local, provider: "Local", model: "local-one" },
    { ...api, provider: "Unclassified", model: "unknown-one" },
    { ...api, provider: "OpenAI", model: "api-one" },
    { ...local, provider: "Ollama", model: "local-two" },
    { ...api, provider: "OpenAI-compatible local", model: "unknown-two" },
    { ...api, provider: "API", model: "api-two" },
  ].map((request, index) => ({ ...request, sequence: index + 1 }));
  const before = JSON.stringify(requests);
  render(<ComparisonMetricGroups requests={requests} kind="timing" />);
  expect(screen.getAllByRole("table").map(table => table.querySelector("caption")?.textContent)).toEqual([
    "OpenAI · api-one — 처리 시간", "Unclassified · unknown-one — 처리 시간",
    "API · api-two — 처리 시간", "Local · local-one — 처리 시간",
    "OpenAI-compatible local · unknown-two — 처리 시간", "Ollama · local-two — 처리 시간",
  ]);
  expect(JSON.stringify(requests)).toBe(before);
});
