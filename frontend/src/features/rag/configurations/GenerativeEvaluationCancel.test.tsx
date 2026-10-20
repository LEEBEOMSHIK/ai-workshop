import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { GenerativeEvaluationPanel } from "./GenerativeEvaluationPanel";
import type { GenerativeRun } from "./generative-api";

const pending: GenerativeRun = {
  id: "synthetic-run", kind: "generative", metric_version: "generative-v1",
  dataset_snapshot_id: "synthetic-dataset", policy_id: "synthetic-policy", rules_digest: "digest",
  status: "pending", created_at: "2026-10-18T00:00:00Z", repetition_count: 2,
  attempts: [{ id: "synthetic-attempt", case_id: "synthetic-case", configuration_version_id: "synthetic-config",
    query: "합성 질문", repetition: 0, attempt_number: 1, status: "pending", sources: [],
    answer: null, execution_id: null, result_digest: null, error_code: null,
    observation: null, metrics: null, judgment: null }],
};
const cancelled = {
  ...pending, status: "cancelled", cancelled_by: "synthetic-owner", cancelled_at: "2026-10-18T01:00:00Z",
  cancellation_reason: "user_requested", attempts: pending.attempts.map(item => ({ ...item, status: "cancelled" })),
};
const base = "/api/v1/rag/generative-evaluations";
let loaded: GenerativeRun;
let cancelResponse: () => Promise<Response>;
let requests: { path: string; init?: RequestInit }[];
let refreshFails: boolean;
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}
beforeEach(() => {
  loaded = pending;
  requests = [];
  refreshFails = false;
  cancelResponse = async () => json(cancelled);
  vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
    requests.push({ path, init });
    if (path === `${base}/synthetic-run/cancel`) return cancelResponse();
    if (path === `${base}/policies`) return json([]);
    if (path === base) return json([loaded]);
    if (path === `${base}/synthetic-run`) return refreshFails ? json({}, 503) : json(loaded);
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());
function openRun() {
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="synthetic-run" />);
}

it("cancels only after an explicit click through the authenticated API and shows the audit record", async () => {
  openRun();
  const button = await screen.findByRole("button", { name: "시작 전 평가 취소" });
  expect(requests.every(item => item.init?.method !== "POST")).toBe(true);
  button.focus();
  await userEvent.setup().keyboard("{Enter}");
  expect(await screen.findByText("실행: 취소")).toBeVisible();
  expect(screen.getByText("시작 전에 취소된 평가입니다. 모델을 호출하지 않았습니다.")).toBeVisible();
  expect(screen.getByText("synthetic-owner")).toBeVisible();
  expect(screen.getByText("취소된 시도 1건")).toBeVisible();
  expect(screen.getByText("사용자 요청")).toBeVisible();
  expect(screen.getByText(new Date(cancelled.cancelled_at).toLocaleString("ko-KR"))).toBeVisible();
  const posts = requests.filter(item => item.init?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatchObject({ path: `${base}/synthetic-run/cancel`, init: { credentials: "include", body: JSON.stringify({ reason: "user_requested" }) } });
  expect(screen.queryByRole("button", { name: "시작 전 평가 취소" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "실패한 사례 재시도" })).not.toBeInTheDocument();
  expect(screen.queryByText("DB 검증 후 구성에 생성형 통과 반영")).not.toBeInTheDocument();
});

it("prevents repeated cancellation clicks while the request is pending", async () => {
  let resolve!: (value: Response) => void;
  cancelResponse = () => new Promise(done => { resolve = done; });
  openRun();
  const button = await screen.findByRole("button", { name: "시작 전 평가 취소" });
  fireEvent.click(button);
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(requests.filter(item => item.init?.method === "POST")).toHaveLength(1);
  await act(async () => resolve(json(cancelled)));
  expect(screen.getByText("실행: 취소")).toBeVisible();
});

it("refreshes the status after a claim conflict without retrying cancellation", async () => {
  cancelResponse = async () => {
    loaded = { ...pending, status: "running", attempts: pending.attempts.map(item => ({ ...item, status: "running" })) };
    return json({ error: { code: "evaluation_not_pending", message: "Already claimed", correlation_id: "synthetic" } }, 409);
  };
  openRun();
  fireEvent.click(await screen.findByRole("button", { name: "시작 전 평가 취소" }));
  expect(await screen.findByText("실행: 실행 중")).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("취소할 수 없는 상태입니다. 최신 실행 상태를 확인해 주세요.");
  expect(screen.queryByRole("button", { name: "시작 전 평가 취소" })).not.toBeInTheDocument();
  expect(requests.filter(item => item.init?.method === "POST")).toHaveLength(1);
});

it("does not claim cancellation if the request fails", async () => {
  cancelResponse = async () => json({ error: { code: "unavailable", message: "취소 요청을 처리하지 못했습니다.", correlation_id: "synthetic" } }, 503);
  openRun();
  fireEvent.click(await screen.findByRole("button", { name: "시작 전 평가 취소" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("취소 요청을 처리하지 못했습니다.");
  expect(screen.getByText("실행: 대기")).toBeVisible();
  expect(screen.queryByText("실행: 취소")).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", { name: "시작 전 평가 취소" })).toBeEnabled());
});

it("reports an unreadable status after a cancellation conflict without claiming a terminal state", async () => {
  cancelResponse = async () => {
    refreshFails = true;
    return json({}, 409);
  };
  openRun();
  fireEvent.click(await screen.findByRole("button", { name: "시작 전 평가 취소" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("취소 요청이 거절됐습니다. 최신 상태를 불러오지 못했습니다. 결과 새로고침으로 확인해 주세요.");
  expect(screen.queryByText("실행: 취소")).not.toBeInTheDocument();
  expect(requests.filter(item => item.init?.method === "POST")).toHaveLength(1);
});

it.each(["running", "completed", "failed", "interrupted", "cancelled"])("does not offer cancellation for %s runs", async status => {
  loaded = { ...pending, status, attempts: pending.attempts.map(item => ({ ...item, status })) };
  openRun();
  await screen.findByRole("button", { name: "결과 새로고침" });
  expect(screen.queryByRole("button", { name: "시작 전 평가 취소" })).not.toBeInTheDocument();
  expect(requests.every(item => item.init?.method !== "POST")).toBe(true);
});
