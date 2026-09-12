import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import { ModelLabPage } from "./ModelLabPage";

afterEach(() => vi.unstubAllGlobals());

const labels = ["현재 구성 확인", "모델·실행 환경 설정", "처리·검색·답변 구성", "데이터 사용 범위·승인", "연결 검사·사용 준비"];
function metadata() {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    if (input === "/api/v1/admin/rag/deployments" || input === "/api/v1/workspaces") return Response.json([]);
    if (input === "/api/v1/admin/rag/data-policies/installation") return Response.json({ policy_id: "installation", version_id: "policy-v1", version: 1, mode: "deny", approved_providers: [], changed_by: "owner", created_at: "2026-09-09T00:00:00Z" });
    throw new Error("Unexpected request");
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

it("starts with read-only registered metadata and follows the ordered keyboard tab workflow", async () => {
  const fetcher = metadata();
  const user = userEvent.setup();
  render(<ModelLabPage />);
  expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(labels);
  expect(screen.getByRole("tabpanel", { name: labels[0] })).toBeVisible();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /등록|정책 저장|상태 확인/ })).not.toBeInTheDocument();
  screen.getByRole("tab", { name: labels[0] }).focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: labels[1] })).toHaveFocus();
  expect(screen.getByRole("tabpanel", { name: labels[1] })).toBeVisible();
  await user.keyboard("{End}");
  expect(screen.getByRole("tab", { name: labels[4] })).toHaveFocus();
  expect(screen.getByRole("link", { name: "저장 구성에서 연결 검사하기" })).toHaveAttribute("href", "/admin/rag/configurations");
  await user.keyboard("{Home}{ArrowLeft}");
  expect(screen.getByRole("tab", { name: labels[4] })).toHaveFocus();
  expect(fetcher.mock.calls.map(([url]) => url).every((url) => !String(url).includes("codex"))).toBe(true);
});

it("retains model and policy drafts while tab navigation never saves or loads runners", async () => {
  const fetcher = metadata();
  const user = userEvent.setup();
  render(<ModelLabPage />);
  await user.click(screen.getByRole("tab", { name: labels[1] }));
  await user.click(screen.getByText("고급 모델 정의 JSON 등록"));
  await user.type(screen.getByRole("textbox", { name: "이름" }), "unfinished-model");
  await user.click(screen.getByRole("tab", { name: labels[3] }));
  await screen.findByRole("heading", { name: "외부 전송 정책" });
  const policyPanel = screen.getByRole("tabpanel", { name: labels[3] });
  await user.selectOptions(within(policyPanel).getByRole("combobox", { name: "회사 외부 전송 정책" }), "approved_providers");
  await user.click(screen.getByRole("tab", { name: labels[1] }));
  expect(screen.getByRole("textbox", { name: "이름" })).toHaveValue("unfinished-model");
  await user.click(screen.getByRole("tab", { name: labels[3] }));
  expect(screen.getByRole("combobox", { name: "회사 외부 전송 정책" })).toHaveValue("approved_providers");
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it("keeps embedded model metadata read-only without admin loading or tabs", () => {
  const fetcher = metadata();
  render(<ModelLabPage embedded />);
  expect(screen.getByRole("heading", { name: "모델 레지스트리" })).toBeVisible();
  expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
});

it("shows actual document-processing data before indexing, retrieval and generation", async () => {
  metadata();
  const user = userEvent.setup();
  render(<ModelLabPage initialProfiles={[{ id: "processing-v1", kind: "document_processing", name: "synthetic-processing", version: 1, config: {}, bindings: [], deployment_version_id: null, legacy: false, readiness: { ready: false, reason_codes: [] }, evaluation_state: "draft", is_default: false }]} />);
  await user.click(screen.getByRole("tab", { name: labels[2] }));
  const panel = screen.getByRole("tabpanel", { name: labels[2] });
  expect(within(panel).getByText("synthetic-processing")).toBeVisible();
  expect(within(panel).getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["문서 처리 프로파일", "색인 프로파일", "검색 프로파일", "생성 프로파일"]);
  expect(screen.getByRole("textbox", { name: "프로파일 YAML" })).not.toBeVisible();
});

it("shares one explicit runner catalog and retains provider and generation drafts across tabs", async () => {
  const fetcher = metadata();
  const original = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (input) => {
    if (input === "/api/v1/admin/rag/codex-runners") return Response.json([{
      runner_ref: "test-runner", cli_version: "1", local_preflight_passed: true, safe_error_code: null,
      limits: { timeout_seconds: 60, max_output_tokens: 2048, max_concurrent: 1 },
      prompt_options: [{ answer_ref: "answer-v1", context_ref: "context-v1", control_ref: "control-v1", response_schema_version: 2, control_text: "Synthetic control", answer_text: "Synthetic answer", context_text: "Synthetic context" }],
    }]);
    if (input === "/api/v1/admin/rag/deployments") return Response.json([{
      deployment_id: "d", version_id: "dv", version: 1, display_name: "Synthetic Codex", description: "",
      model_name: "Synthetic model", model_version: 1, provider: "development_codex_exec", provider_model_id: "requested-test", runner_ref: "test-runner", location: "external", external_transfer: true,
      allowed_environments: ["development"], capabilities: ["structured_output"], secret_configured: false, readiness: { ready: false, reason_codes: [] }, latest_health: null,
    }]);
    return original(input);
  });
  const user = userEvent.setup();
  render(<ModelLabPage />);
  await user.click(screen.getByRole("tab", { name: labels[1] }));
  await user.selectOptions(screen.getByRole("combobox", { name: "설정할 실행 환경" }), "development_codex_exec");
  await user.click(screen.getByRole("button", { name: "서버 Codex 설정 불러오기" }));
  await screen.findByRole("combobox", { name: "서버 runner" });
  await user.type(screen.getByRole("textbox", { name: "배포 이름" }), "draft-deployment");
  await user.click(screen.getByRole("tab", { name: labels[2] }));
  expect(screen.getByText("Synthetic control")).toBeVisible();
  await user.type(screen.getByRole("textbox", { name: "생성 프로파일 이름" }), "draft-profile");
  await user.click(screen.getByRole("tab", { name: labels[1] }));
  expect(screen.getByRole("combobox", { name: "설정할 실행 환경" })).toHaveValue("development_codex_exec");
  expect(screen.getByRole("textbox", { name: "배포 이름" })).toHaveValue("draft-deployment");
  await user.click(screen.getByRole("tab", { name: labels[2] }));
  expect(screen.getByRole("textbox", { name: "생성 프로파일 이름" })).toHaveValue("draft-profile");
  expect(fetcher.mock.calls.map(([url]) => url).filter((url) => String(url).includes("codex"))).toEqual(["/api/v1/admin/rag/codex-runners"]);
  expect(fetcher).toHaveBeenCalledTimes(4);
});
