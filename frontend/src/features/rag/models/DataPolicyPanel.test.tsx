import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { DataPolicyPanel } from "./DataPolicyPanel";
import type { InstallationDataPolicy, WorkspaceDataPolicy } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("DataPolicyPanel", () => {
  it("allows the first Workspace policy version when no current version exists", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(workspacePolicy({ version: 1 }), 201)));
    const user = userEvent.setup();
    render(
      <DataPolicyPanel
        installationPolicy={installationPolicy()}
        workspaces={[{ id: "workspace-1", name: "전사 지식", kind: "company", expires_at: null }]}
        workspacePolicies={{ "workspace-1": null }}
      />,
    );

    expect(screen.getByText("아직 별도 정책 없음")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "정책 첫 버전 추가" }));
    expect(await screen.findByText("전사 지식 정책 v1이 추가되었습니다.")).toBeVisible();
  });

  it("appends an Installation policy version only after the server succeeds", async () => {
    const initial = installationPolicy();
    const saved = installationPolicy({ version: 3, mode: "approved_providers" });
    let requestBody: unknown;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(input).toBe("/api/v1/admin/rag/data-policies/installation/versions");
      requestBody = JSON.parse(String(init?.body));
      return jsonResponse(saved, 201);
    }));
    const user = userEvent.setup();
    render(
      <DataPolicyPanel
        installationPolicy={initial}
        workspaces={[]}
        workspacePolicies={{}}
      />,
    );

    expect(screen.getByText("현재 버전 v2")).toBeVisible();
    await user.selectOptions(screen.getByLabelText("회사 외부 전송 정책"), "approved_providers");
    await user.click(screen.getByRole("checkbox", { name: "OpenAI Responses API" }));
    await user.click(screen.getByRole("button", { name: "회사 정책 새 버전 추가" }));

    expect(requestBody).toEqual({
      mode: "approved_providers",
      approved_providers: ["openai_responses"],
    });
    expect(await screen.findByText("회사 정책 v3이 추가되었습니다.")).toBeVisible();
    expect(screen.getByText("현재 버전 v3")).toBeVisible();
  });

  it("updates a selected Workspace policy and reports a safe server failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      detail: { code: "invalid_data_policy", message: "unsafe internal detail" },
    }, 422)));
    const user = userEvent.setup();
    render(
      <DataPolicyPanel
        installationPolicy={installationPolicy({ mode: "approved_providers" })}
        workspaces={[{ id: "workspace-1", name: "전사 지식", kind: "company", expires_at: null }]}
        workspacePolicies={{ "workspace-1": workspacePolicy() }}
      />,
    );

    const workspaceRegion = screen.getByRole("group", { name: "전사 지식 외부 전송 정책" });
    expect(within(workspaceRegion).getByText("현재 버전 v4")).toBeVisible();
    await user.selectOptions(
      within(workspaceRegion).getByLabelText("지식 공간 외부 전송 정책"),
      "deny",
    );
    await user.click(within(workspaceRegion).getByRole("button", { name: "정책 새 버전 추가" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("정책 값과 상위 정책 범위를 확인");
    expect(screen.queryByText("unsafe internal detail")).not.toBeInTheDocument();
    expect(within(workspaceRegion).getByText("현재 버전 v4")).toBeVisible();
  });

  it("prevents a Workspace provider policy after the Installation policy removes it", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (input === "/api/v1/admin/rag/data-policies/installation/versions") {
        return jsonResponse(installationPolicy({ version: 3, mode: "deny", approved_providers: [] }), 201);
      }
      throw new Error(`Forbidden request: ${String(input)}`);
    }));
    const user = userEvent.setup();
    render(
      <DataPolicyPanel
        installationPolicy={installationPolicy({
          mode: "approved_providers",
          approved_providers: ["openai_responses"],
        })}
        workspaces={[{ id: "workspace-1", name: "전사 지식", kind: "company", expires_at: null }]}
        workspacePolicies={{
          "workspace-1": workspacePolicy({
            mode: "approved_providers",
            approved_providers: ["openai_responses"],
          }),
        }}
      />,
    );

    await user.selectOptions(screen.getByLabelText("회사 외부 전송 정책"), "deny");
    await user.click(screen.getByRole("button", { name: "회사 정책 새 버전 추가" }));
    expect(await screen.findByText("회사 정책 v3이 추가되었습니다.")).toBeVisible();
    const workspace = screen.getByRole("group", { name: "전사 지식 외부 전송 정책" });
    expect(within(workspace).getByRole("button", { name: "정책 새 버전 추가" })).toBeDisabled();
    expect(within(workspace).getByRole("status")).toHaveTextContent("회사 정책에서 허용하지 않는 공급자");
  });
});

function installationPolicy(
  overrides: Partial<InstallationDataPolicy> = {},
): InstallationDataPolicy {
  return {
    policy_id: "installation-policy",
    version_id: "installation-policy-v2",
    version: 2,
    mode: "deny",
    approved_providers: [],
    changed_by: "owner",
    created_at: "2026-09-05T07:00:00Z",
    ...overrides,
  };
}

function workspacePolicy(overrides: Partial<WorkspaceDataPolicy> = {}): WorkspaceDataPolicy {
  return {
    policy_id: "workspace-policy",
    version_id: "workspace-policy-v4",
    workspace_id: "workspace-1",
    version: 4,
    mode: "inherit",
    approved_providers: [],
    changed_by: "owner",
    created_at: "2026-09-05T07:30:00Z",
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}
