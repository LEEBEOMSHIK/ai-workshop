import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ComparisonMetricGroups } from "./ComparisonMetricGroups";
import { ComparisonReportView } from "./ComparisonReportView";
import type { ComparisonRequest } from "./api";
import { comparisonFixture } from "./comparison.test-support";

function timingTable(provider: string, model: string) {
  return screen.getByRole("table", { name: `${provider} · ${model} — 처리 시간` });
}

it("keeps answer cards in the same provider order as timing and cost when switching repetitions", async () => {
  const detail = comparisonFixture();
  const [firstA, firstB, repeatA, repeatB] = detail.report.requests;
  detail.report.requests = [firstA, firstB, { ...repeatB, sequence: 3 }, { ...repeatA, sequence: 4 }];
  render(<ComparisonReportView detail={detail} />);
  await userEvent.click(screen.getByRole("radio", { name: "동일 입력 반복 · 2회차" }));
  const cards = screen.getAllByRole("article");
  expect(cards[0]).toHaveAccessibleName("synthetic-cloud · 동일 입력 반복 · 2회차");
  expect(cards[1]).toHaveAccessibleName("synthetic-local · 동일 입력 반복 · 2회차");
  expect(within(cards[0]).getByText("반복에서도 일반 규칙을 설명합니다.")).toBeVisible();
});

it("keeps provider lanes distinct for the same model name despite reversed repeat execution order", () => {
  const [firstA, firstB, repeatA, repeatB] = comparisonFixture().report.requests;
  const requests: ComparisonRequest[] = [
    { ...firstA, provider: "Provider A", model: "shared-model" },
    { ...firstB, provider: "Provider B", model: "shared-model" },
    { ...repeatB, sequence: 3, provider: "Provider B", model: "shared-model" },
    { ...repeatA, sequence: 4, provider: "Provider A", model: "shared-model" },
  ];
  render(<ComparisonMetricGroups requests={requests} kind="timing" />);
  const firstLane = timingTable("Provider A", "shared-model");
  const secondLane = timingTable("Provider B", "shared-model");
  expect(screen.getAllByRole("table")).toEqual([firstLane, secondLane]);
  expect(within(firstLane).getByRole("row", { name: "완료 응답 3.781초 3.347초" })).toBeVisible();
  expect(within(secondLane).getByRole("row", { name: "완료 응답 159.723초 11.123초" })).toBeVisible();
  expect(within(firstLane).queryByText("159.723초")).not.toBeInTheDocument();
  expect(within(secondLane).queryByText("3.347초")).not.toBeInTheDocument();
  expect(within(firstLane).getAllByRole("columnheader")[2]).toHaveTextContent("요청 4");
  expect(within(secondLane).getAllByRole("columnheader")[2]).toHaveTextContent("요청 3");
});

it("does not invent a missing repetition within a model lane", () => {
  const requests = comparisonFixture().report.requests.slice(0, 3);
  render(<ComparisonMetricGroups requests={requests} kind="timing" />);
  const cloud = timingTable("OpenAI", "synthetic-cloud");
  const local = timingTable("Local", "synthetic-local");
  expect(within(cloud).getAllByRole("columnheader")).toHaveLength(3);
  expect(within(local).getAllByRole("columnheader")).toHaveLength(2);
  expect(within(local).queryByText(/동일 입력 반복/)).not.toBeInTheDocument();
  expect(within(local).getByRole("row", { name: "완료 응답 159.723초" })).toBeVisible();
  expect(screen.getAllByRole("table")).toHaveLength(2);
});

it("preserves numeric zero separately from unavailable observations within a single lane", () => {
  const requests = comparisonFixture().report.requests;
  requests[0] = { ...requests[0], duration_seconds: 0, first_token_seconds: 0,
    native_timing: { load_seconds: 0, input_seconds: 0, output_seconds: 0, total_seconds: 0 },
  };
  render(<ComparisonMetricGroups requests={requests} kind="timing" />);
  const cloud = timingTable("OpenAI", "synthetic-cloud");
  expect(within(cloud).getByRole("row", { name: "첫 토큰 0.000초 미측정" })).toBeVisible();
  expect(within(cloud).getByRole("row", { name: "입력 처리 0.000초 미측정" })).toBeVisible();
});

it("keeps reported zero billing, unknown cost and local inapplicability in their own lanes", () => {
  const requests = comparisonFixture().report.requests;
  requests[0] = { ...requests[0], estimated_cost_usd: "0", actual_billed_cost_usd: "0" };
  requests[2] = { ...requests[2], cost_status: "unknown", estimated_cost_usd: null,
    actual_billed_cost_usd: null };
  render(<ComparisonMetricGroups requests={requests} kind="usage" />);
  const cloud = screen.getByRole("table", { name: "OpenAI · synthetic-cloud — 사용량·비용" });
  const local = screen.getByRole("table", { name: "Local · synthetic-local — 사용량·비용" });
  expect(within(cloud).getByRole("row", { name: "예상 API 비용 USD 0 미확인" })).toBeVisible();
  expect(within(cloud).getByRole("row", { name: "실제 청구액 USD 0 미확인" })).toBeVisible();
  expect(within(cloud).queryByText("API 청구 해당 없음")).not.toBeInTheDocument();
  expect(within(local).getByRole("row", { name: "예상 API 비용 API 청구 해당 없음 API 청구 해당 없음" })).toBeVisible();
});

it("supports three repetitions with native header relationships and preserves original input order", () => {
  const [firstA, firstB, repeatA] = comparisonFixture().report.requests;
  const requests: ComparisonRequest[] = [firstA, firstB,
    { ...repeatA, sequence: 3, repetition: 3, duration_seconds: 42 },
    { ...repeatA, sequence: 4 },
  ];
  const before = JSON.stringify(requests);
  Object.freeze(requests);
  render(<ComparisonMetricGroups requests={requests} kind="timing" />);
  const cloud = timingTable("OpenAI", "synthetic-cloud");
  expect(within(cloud).getAllByRole("columnheader")).toHaveLength(4);
  for (const column of within(cloud).getAllByRole("columnheader")) expect(column).toHaveAttribute("scope", "col");
  for (const metric of within(cloud).getAllByRole("rowheader")) expect(metric).toHaveAttribute("scope", "row");
  expect(within(cloud).getByRole("row", { name: "완료 응답 3.781초 3.347초 42.000초" })).toBeVisible();
  expect(within(cloud).getAllByRole("columnheader")[3]).toHaveTextContent("3회차");
  expect(JSON.stringify(requests)).toBe(before);
});
