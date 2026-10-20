import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import { GenerativeEvaluationPanel } from "./GenerativeEvaluationPanel";
import type { SavedConfiguration, Workspace } from "./api";

const configs = [{ version_id: "candidate", name: "Synthetic candidate", version: 1, is_system: false,
  generation_profile_id: "generation", generation_execution_preview: { provider: "local_transformers" } }] as SavedConfiguration[];
const workspaces = [{ id: "workspace", name: "Synthetic workspace", kind: "company", expires_at: null }] as Workspace[];
const saved = { id: "saved-data", cases: [
  { id: "supported-case", query: "Synthetic supported question", expected_answer_status: "supported", expected_evidence_ids: ["evidence"], expected_highlight: null },
  { id: "negative-case", query: "Synthetic negative question", expected_answer_status: "insufficient_evidence", expected_evidence_ids: [], expected_highlight: null },
] };
const created = { id: "created-data", cases: [{ ...saved.cases[1], id: "created-case", query: "Authored synthetic question" }] };
const document = { document_id: "document", workspace_id: "workspace", asset_version_id: "asset", title: "Synthetic document", number: 1, ready: true, sha256: "hash" };
const preview = { complete: true, scope: { configuration_version_id: "candidate", workspace_ids: ["workspace"], asset_version_ids: ["asset"] },
  scope_sha256: "scope-hash", documents: [document], evidence: [], document_count: 1, evidence_count: 0 };
const base = "/api/v1/rag/evaluation-authoring";
type Request = { path: string; method: string; body: Record<string, unknown> | undefined };
let requests: Request[];
let loadSaved: () => Promise<Response>;
let freeze: () => Promise<Response>;
let readPreview: () => Promise<Response>;
const json = (value: unknown) => Response.json(value);
function deferred() {
  let resolve!: (value: Response) => void;
  let reject!: (cause: Error) => void;
  const promise = new Promise<Response>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  requests = [];
  loadSaved = async () => json(saved);
  freeze = async () => json(created);
  readPreview = async () => json(preview);
  vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
    requests.push({ path, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (path === "/api/v1/rag/generative-evaluations/policies") return json([{ id: "policy", name: "Synthetic policy", definition: { version: 1 } }]);
    if (path === "/api/v1/rag/generative-evaluations") return json(init?.method === "POST"
      ? { id: "mock-run", created_at: "2026-10-19T00:00:00Z", status: "pending", repetition_count: 2, attempts: [] } : []);
    if (path === `${base}/snapshots/saved-data`) return loadSaved();
    if (path === `${base}/snapshots`) return freeze();
    if (path === `${base}/documents`) return json({ documents: [document], next_cursor: null });
    if (path === `${base}/preview`) return readPreview();
    throw new Error(`Unexpected mock request: ${path}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());
function open() {
  render(<StrictMode><GenerativeEvaluationPanel configurations={configs} workspaces={workspaces} /></StrictMode>);
  fireEvent.click(screen.getByText("새 생성형 평가 준비"));
}
function mode(name: "저장 자료 재사용" | "새 자료 작성") { fireEvent.click(screen.getByRole("radio", { name })); }
async function load() {
  fireEvent.change(screen.getByLabelText("저장된 평가 자료 ID"), { target: { value: saved.id } });
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 불러오기" }));
  await screen.findByText("Synthetic supported question");
}
async function selectPreview() {
  fireEvent.click(screen.getByRole("checkbox", { name: "Synthetic workspace" }));
  fireEvent.click(screen.getByRole("button", { name: "문서 목록 불러오기" }));
  fireEvent.click(await screen.findByRole("checkbox", { name: "Synthetic document v1" }));
  fireEvent.click(screen.getByRole("button", { name: "근거 불러오기" }));
}
async function draft() {
  await selectPreview();
  fireEvent.change(await screen.findByLabelText("질문 1"), { target: { value: "Authored synthetic question" } });
  fireEvent.change(screen.getByLabelText("기대 결과 1"), { target: { value: "insufficient_evidence" } });
  fireEvent.change(screen.getByLabelText("평가 이름"), { target: { value: "Synthetic retained draft" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "자료와 질문의 불변 보관을 확인합니다" }));
}
function rulesFor(question: string) { return within(screen.getByText(question, { selector: "legend" }).closest("fieldset")!); }
function editRule(question: string, text: string, history: string) {
  const group = rulesFor(question);
  fireEvent.change(group.getByLabelText("반드시 포함할 내용 (한 줄에 하나)"), { target: { value: text } });
  fireEvent.change(group.getByLabelText("이전 질문 문맥 (선택, 원문 그대로 고정)"), { target: { value: history } });
}

it("separates visible preparation modes and labels the loaded case types without inventing answers", async () => {
  open();
  expect(screen.getByRole("radio", { name: "저장 자료 재사용" })).toBeChecked();
  expect(screen.queryByRole("combobox", { name: "평가할 구성" })).not.toBeInTheDocument();
  await load();
  expect(rulesFor(saved.cases[0].query).getByText("기대 결과: 정상 답변")).toBeVisible();
  expect(rulesFor(saved.cases[1].query).getByText("기대 결과: 근거 부족")).toBeVisible();
  for (const item of screen.getAllByLabelText("반드시 포함할 내용 (한 줄에 하나)")) expect(item).toHaveValue("");
  mode("새 자료 작성");
  expect(screen.getByRole("combobox", { name: "평가할 구성" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "평가 자료 불러오기" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "답변 내용 판정 범위" })).not.toBeInTheDocument();
  expect(screen.queryByText(/저장된 평가 자료를 불러왔습니다/)).not.toBeInTheDocument();
});

it("retains both modes' snapshots, rules, history and draft while keeping common candidate and policy selection", async () => {
  open(); await load();
  editRule(saved.cases[0].query, "saved-rule", "saved-history");
  fireEvent.change(screen.getByLabelText("검색 K"), { target: { value: "17" } });
  fireEvent.change(screen.getByLabelText("사례별 반복 횟수"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "Synthetic candidate v1" }));
  fireEvent.change(screen.getByLabelText("생성형 승격 기준"), { target: { value: "policy" } });
  mode("새 자료 작성"); await draft();
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 저장" }));
  await screen.findByText(created.cases[0].query, { selector: "legend" });
  editRule(created.cases[0].query, "created-rule", "created-history");
  fireEvent.change(screen.getByLabelText("검색 K"), { target: { value: "8" } });
  mode("저장 자료 재사용");
  expect(rulesFor(saved.cases[0].query).getByLabelText("반드시 포함할 내용 (한 줄에 하나)")).toHaveValue("saved-rule");
  expect(rulesFor(saved.cases[0].query).getByLabelText("이전 질문 문맥 (선택, 원문 그대로 고정)")).toHaveValue("saved-history");
  expect(screen.getByLabelText("검색 K")).toHaveValue(17);
  expect(screen.getByLabelText("사례별 반복 횟수")).toHaveValue(3);
  expect(screen.getByRole("checkbox", { name: "Synthetic candidate v1" })).toBeChecked();
  expect(screen.getByLabelText("생성형 승격 기준")).toHaveValue("policy");
  fireEvent.click(screen.getByRole("button", { name: "생성형 평가 실행" }));
  await waitFor(() => expect(requests.filter(item => item.path === "/api/v1/rag/generative-evaluations" && item.method === "POST")).toHaveLength(1));
  const submitted = requests.find(item => item.path === "/api/v1/rag/generative-evaluations" && item.method === "POST")!.body;
  expect(submitted).toMatchObject({ dataset_snapshot_id: saved.id, retrieval_k: 17, repetition_count: 3,
    expected_rules: { "supported-case": { required_propositions: ["saved-rule"] } }, case_histories: { "supported-case": [{ role: "user", content: "saved-history" }] } });
  expect(JSON.stringify(submitted)).not.toContain("created-rule");
  await waitFor(() => expect(screen.getByRole("button", { name: "생성형 평가 실행" })).toBeEnabled());
  mode("새 자료 작성");
  expect(screen.getByLabelText("평가 이름")).toHaveValue("Synthetic retained draft");
  expect(screen.getByLabelText("질문 1")).toHaveValue("Authored synthetic question");
  expect(screen.getByRole("checkbox", { name: "Synthetic workspace" })).toBeChecked();
  expect(rulesFor(created.cases[0].query).getByLabelText("반드시 포함할 내용 (한 줄에 하나)")).toHaveValue("created-rule");
  expect(screen.getByLabelText("검색 K")).toHaveValue(8);
  fireEvent.click(screen.getByRole("button", { name: "생성형 평가 실행" }));
  await waitFor(() => expect(requests.filter(item => item.path === "/api/v1/rag/generative-evaluations" && item.method === "POST")).toHaveLength(2));
  const next = requests.filter(item => item.path === "/api/v1/rag/generative-evaluations" && item.method === "POST")[1].body;
  expect(next).toMatchObject({ dataset_snapshot_id: created.id, expected_rules: { "created-case": { required_propositions: ["created-rule"] } } });
  expect(JSON.stringify(next)).not.toContain("saved-rule");
});

it.each(["resolve", "reject"] as const)("ignores stale saved load %s after saved-create-saved switching", async outcome => {
  const delayed = deferred(); loadSaved = () => delayed.promise;
  open();
  fireEvent.change(screen.getByLabelText("저장된 평가 자료 ID"), { target: { value: saved.id } });
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 불러오기" }));
  mode("새 자료 작성"); mode("저장 자료 재사용");
  await act(async () => outcome === "resolve" ? delayed.resolve(json(saved)) : delayed.reject(new Error("stale failure")));
  expect(screen.queryByRole("heading", { name: "답변 내용 판정 범위" })).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByText(/저장된 평가 자료를 불러왔습니다/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "평가 자료 불러오기" })).toBeEnabled();
});

it.each(["resolve", "reject"] as const)("ignores stale author save %s across switching while preserving draft and saved data", async outcome => {
  open(); await load(); editRule(saved.cases[0].query, "preserved", "context");
  mode("새 자료 작성"); await draft();
  const delayed = deferred(); freeze = () => delayed.promise;
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 저장" }));
  mode("저장 자료 재사용"); mode("새 자료 작성");
  await act(async () => outcome === "resolve" ? delayed.resolve(json(created)) : delayed.reject(new Error("stale failure")));
  expect(screen.getByLabelText("평가 이름")).toHaveValue("Synthetic retained draft");
  expect(screen.queryByRole("heading", { name: "답변 내용 판정 범위" })).not.toBeInTheDocument();
  expect(screen.queryByText(/평가 자료를 저장했습니다/)).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "평가 자료 저장" })).toBeEnabled();
  mode("저장 자료 재사용");
  expect(rulesFor(saved.cases[0].query).getByLabelText("반드시 포함할 내용 (한 줄에 하나)")).toHaveValue("preserved");
});

it("does not let a hidden author preview overwrite the saved rules or show obsolete feedback", async () => {
  open(); await load(); editRule(saved.cases[0].query, "preserved", "context");
  mode("새 자료 작성");
  const delayed = deferred(); readPreview = () => delayed.promise;
  await selectPreview(); mode("저장 자료 재사용");
  await act(async () => delayed.resolve(json(preview)));
  expect(rulesFor(saved.cases[0].query).getByLabelText("반드시 포함할 내용 (한 줄에 하나)")).toHaveValue("preserved");
  mode("새 자료 작성");
  expect(screen.queryByRole("textbox", { name: "질문 1" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "근거 불러오기" })).toBeEnabled();
});

it("keeps the retained draft editable when validation fails after leaving an outstanding save", async () => {
  open(); mode("새 자료 작성"); await draft();
  const delayed = deferred(); freeze = () => delayed.promise;
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 저장" }));
  mode("저장 자료 재사용"); mode("새 자료 작성");
  fireEvent.change(screen.getByLabelText("평가 이름"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 저장" }));
  expect(screen.getByRole("alert")).toHaveTextContent("평가 이름");
  expect(screen.getByLabelText("평가 이름")).toBeEnabled();
  expect(screen.getByRole("button", { name: "평가 자료 저장" })).toBeEnabled();
  await act(async () => delayed.reject(new Error("obsolete")));
});

it("does not revive an old save success message when a subsequent validation fails", async () => {
  open(); mode("새 자료 작성"); await draft();
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 저장" }));
  await screen.findByText(/평가 자료를 저장했습니다/);
  mode("저장 자료 재사용"); mode("새 자료 작성");
  fireEvent.click(screen.getByRole("checkbox", { name: "자료와 질문의 불변 보관을 확인합니다" }));
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 저장" }));
  expect(screen.getByRole("alert")).toHaveTextContent("자료 보관 동의");
  expect(screen.queryByText(/평가 자료를 저장했습니다/)).not.toBeInTheDocument();
});
