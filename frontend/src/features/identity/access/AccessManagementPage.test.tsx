import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { components } from "../../../shared/api/schema";
import { AccessManagementPage } from "./AccessManagementPage";

type Authority = components["schemas"]["UserAuthorityResponse"];
type Audit = components["schemas"]["AuthorityAuditResponse"];

const currentUser = {
  id: "00000000-0000-4000-8000-000000000001",
  display_name: "테스트 마스터",
  email: "master@example.test",
  role: "owner" as const,
};
const member: Authority = {
  id: "00000000-0000-4000-8000-000000000002",
  display_name: "합성 사용자",
  email: "member@example.test",
  role: "member",
  is_active: false,
  revision: 4,
  is_last_active_master: false,
  technologies: [{
    key: "rag",
    label: "RAG",
    capabilities: ["view", "execute"],
    delegation_enabled: false,
  }],
};
const owner: Authority = {
  id: currentUser.id,
  display_name: currentUser.display_name,
  email: currentUser.email,
  role: "owner",
  is_active: true,
  revision: 2,
  is_last_active_master: true,
  technologies: [{
    key: "rag",
    label: "RAG",
    capabilities: ["view", "configure", "execute"],
    delegation_enabled: false,
  }],
};
const audit: Audit = {
  id: 8,
  actor_id: currentUser.id,
  target_user_id: member.id,
  event_type: "technology_grant_changed",
  technology_key: "rag",
  before: {
    role: "member",
    is_active: false,
    revision: 3,
    technologies: { rag: ["view"] },
  },
  after: {
    role: "member",
    is_active: false,
    revision: 4,
    technologies: { rag: ["view", "execute"] },
  },
  created_at: "2026-09-09T00:00:00Z",
};
const technologies = [{ key: "rag", label: "RAG", delegation_enabled: false }];

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function pathOf(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
}

function installBoundary(
  initialUsers: Authority[] = [member],
  initialAudits: Audit[] = [audit],
) {
  let stored = structuredClone(
    initialUsers.find((candidate) => candidate.id === member.id) ?? member,
  );
  const fetch = vi.fn<typeof globalThis.fetch>(async (input, init) => {
    const path = pathOf(input);
    if (path === "/api/v1/admin/access/technologies") return response(technologies);
    if (path === "/api/v1/admin/access/users?limit=50") {
      return response({ items: initialUsers, next_cursor: null });
    }
    if (path === `/api/v1/admin/access/users/${member.id}` && (!init?.method || init.method === "GET")) {
      return response(stored);
    }
    if (path === `/api/v1/admin/access/users/${owner.id}` && (!init?.method || init.method === "GET")) {
      return response(owner);
    }
    if (path === `/api/v1/admin/access/users/${member.id}/audit?limit=50`) {
      return response({ items: initialAudits, next_cursor: null });
    }
    if (path === `/api/v1/admin/access/users/${owner.id}/audit?limit=50`) {
      return response({ items: [], next_cursor: null });
    }
    if (path === `/api/v1/admin/access/users/${member.id}/technologies/rag` && init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as {
        expected_revision: number;
        capabilities: Authority["technologies"][number]["capabilities"];
      };
      stored = {
        ...stored,
        revision: body.expected_revision + 1,
        technologies: [{ ...stored.technologies[0], capabilities: body.capabilities }],
      };
      return response(stored);
    }
    if (path === `/api/v1/admin/access/users/${member.id}/status` && init?.method === "PATCH") {
      const body = JSON.parse(String(init.body)) as {
        expected_revision: number;
        is_active: boolean;
      };
      stored = {
        ...stored,
        revision: body.expected_revision + 1,
        is_active: body.is_active,
      };
      return response(stored);
    }
    if (path === `/api/v1/admin/access/users/${member.id}/role` && init?.method === "PATCH") {
      const body = JSON.parse(String(init.body)) as {
        expected_revision: number;
        role: Authority["role"];
      };
      stored = {
        ...stored,
        revision: body.expected_revision + 1,
        role: body.role,
        technologies: [{
          ...stored.technologies[0],
          capabilities: body.role === "owner"
            ? ["view", "configure", "execute"]
            : [],
        }],
      };
      return response(stored);
    }
    throw new Error(`Unexpected fetch: ${init?.method ?? "GET"} ${path}`);
  });
  vi.stubGlobal("fetch", fetch);
  return {
    fetch,
    getStored: () => stored,
    setStored: (value: Authority) => { stored = value; },
  };
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

it("shows configured dormant grants as no current access and explains that legacy RAG delegation is not enabled", async () => {
  installBoundary();
  render(<AccessManagementPage currentUser={currentUser} />);

  expect(await screen.findByRole("heading", { name: "합성 사용자" })).toBeVisible();
  expect(screen.getByText(/비활성 계정은 현재 어떤 기술에도 접근할 수 없습니다/)).toBeVisible();
  expect(screen.getByText(/저장된 배정은 재활성화 전에 검토/)).toBeVisible();
  const rag = screen.getByRole("group", { name: "RAG 권한" });
  expect(within(rag).getByRole("checkbox", { name: "조회" })).toBeChecked();
  expect(within(rag).getByRole("checkbox", { name: "실행" })).toBeChecked();
  expect(within(rag).getByText("저장됨")).toBeVisible();
  expect(within(rag).getByText(/적용 준비 중.*기존 RAG 관리 기능의 접근을 아직 허용하지 않습니다/)).toBeVisible();
  expect(screen.getByText(/RAG: 조회, 실행/)).toBeVisible();
});

it("renders the real authorization bootstrap audit event with the initialization title", async () => {
  installBoundary([member], [{
    ...audit,
    event_type: "authorization_bootstrap",
    technology_key: null,
  }]);
  render(<AccessManagementPage currentUser={currentUser} />);

  expect(await screen.findByText("권한 기반 초기화")).toBeVisible();
  expect(screen.queryByText("authorization_bootstrap")).not.toBeInTheDocument();
});

it("renders an empty-member state without inventing invitation or account-creation controls", async () => {
  installBoundary([]);
  render(<AccessManagementPage currentUser={currentUser} />);

  expect(await screen.findByText("관리할 기존 사용자가 없습니다.")).toBeVisible();
  expect(screen.queryByRole("button", { name: /초대|사용자 생성|비밀번호/ })).not.toBeInTheDocument();
});

it("auto-selects view for dependent capabilities, rejects removing their prerequisite, and cancels without saving", async () => {
  installBoundary([{ ...member, is_active: true, technologies: [{ ...member.technologies[0], capabilities: [] }] }]);
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);
  const rag = await screen.findByRole("group", { name: "RAG 권한" });

  await user.click(within(rag).getByRole("checkbox", { name: "설정" }));
  expect(within(rag).getByRole("checkbox", { name: "조회" })).toBeChecked();
  expect(within(rag).getByRole("checkbox", { name: "설정" })).toBeChecked();
  expect(screen.getByRole("button", { name: "권한 저장" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "변경 취소" })).toBeEnabled();

  await user.click(within(rag).getByRole("checkbox", { name: "조회" }));
  expect(screen.getByRole("alert")).toHaveTextContent("설정 또는 실행 권한에는 조회 권한이 필요합니다");
  expect(within(rag).getByRole("checkbox", { name: "조회" })).toBeChecked();

  await user.click(screen.getByRole("button", { name: "변경 취소" }));
  expect(within(rag).getByRole("checkbox", { name: "조회" })).not.toBeChecked();
  expect(within(rag).getByRole("checkbox", { name: "설정" })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "권한 저장" })).toBeDisabled();
});

it("does not auto-save, confirms before submission, and reports success only after refreshing actual detail and audit", async () => {
  const boundary = installBoundary([{ ...member, is_active: true }]);
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);
  const rag = await screen.findByRole("group", { name: "RAG 권한" });

  await user.click(within(rag).getByRole("checkbox", { name: "설정" }));
  expect(boundary.fetch.mock.calls.some(([input, init]) =>
    pathOf(input).endsWith("/technologies/rag") && init?.method === "PUT",
  )).toBe(false);

  const saveTrigger = screen.getByRole("button", { name: "권한 저장" });
  await user.click(saveTrigger);
  const dialog = screen.getByRole("dialog", { name: "기술 권한 변경 확인" });
  expect(within(dialog).getByText("변경 전: 조회, 실행")).toBeVisible();
  expect(within(dialog).getByText("변경 후: 조회, 설정, 실행")).toBeVisible();
  expect(within(dialog).getByRole("button", { name: "변경 저장" })).toHaveFocus();
  expect(boundary.getStored().revision).toBe(4);

  await user.click(within(dialog).getByRole("button", { name: "변경 저장" }));
  expect(await screen.findByRole("status")).toHaveTextContent("저장했습니다");
  expect(boundary.getStored()).toMatchObject({
    revision: 5,
    technologies: [{ capabilities: ["view", "configure", "execute"] }],
  });
  expect(saveTrigger).toBeDisabled();
  expect(screen.getByRole("heading", { name: "합성 사용자" })).toHaveFocus();
  expect(document.activeElement).not.toBe(document.body);
  const detailGets = boundary.fetch.mock.calls.filter(([input, init]) =>
    pathOf(input) === `/api/v1/admin/access/users/${member.id}` && (!init?.method || init.method === "GET"),
  );
  const auditGets = boundary.fetch.mock.calls.filter(([input]) =>
    pathOf(input) === `/api/v1/admin/access/users/${member.id}/audit?limit=50`,
  );
  expect(detailGets).toHaveLength(2);
  expect(auditGets).toHaveLength(2);
  const put = boundary.fetch.mock.calls.find(([input, init]) =>
    pathOf(input).endsWith("/technologies/rag") && init?.method === "PUT",
  );
  expect(put?.[1]?.body).toBe(JSON.stringify({
    expected_revision: 4,
    capabilities: ["view", "configure", "execute"],
  }));
});

it("clears user A's save notice after selecting user B", async () => {
  installBoundary([{ ...member, is_active: true }, owner]);
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);
  const rag = await screen.findByRole("group", { name: "RAG 권한" });

  await user.click(within(rag).getByRole("checkbox", { name: "설정" }));
  await user.click(screen.getByRole("button", { name: "권한 저장" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "변경 저장" }));
  expect(await screen.findByRole("status")).toHaveTextContent("저장했습니다");

  await user.click(screen.getByRole("button", { name: /테스트 마스터/ }));
  expect(await screen.findByRole("heading", { name: "테스트 마스터" })).toBeVisible();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("never renders a late response or draft for a previously selected user", async () => {
  let resolveFirst!: (value: Response) => void;
  const firstDetail = new Promise<Response>((resolve) => { resolveFirst = resolve; });
  const second = { ...member, id: "00000000-0000-4000-8000-000000000003", display_name: "두 번째 사용자" };
  const fetch = vi.fn<typeof globalThis.fetch>(async (input) => {
    const path = pathOf(input);
    if (path === "/api/v1/admin/access/technologies") return response(technologies);
    if (path === "/api/v1/admin/access/users?limit=50") return response({ items: [member, second], next_cursor: null });
    if (path === `/api/v1/admin/access/users/${member.id}`) return firstDetail;
    if (path === `/api/v1/admin/access/users/${second.id}`) return response(second);
    if (path.includes("/audit?limit=50")) return response({ items: [], next_cursor: null });
    throw new Error(`Unexpected fetch: ${path}`);
  });
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);

  await user.click(await screen.findByRole("button", { name: /두 번째 사용자/ }));
  expect(await screen.findByRole("heading", { name: "두 번째 사용자" })).toBeVisible();
  await act(async () => resolveFirst(response(member)));
  expect(screen.getByRole("heading", { name: "두 번째 사용자" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "합성 사용자" })).not.toBeInTheDocument();
  const firstCall = fetch.mock.calls.find(([input]) => pathOf(input) === `/api/v1/admin/access/users/${member.id}`);
  expect(firstCall?.[1]?.signal).toHaveProperty("aborted", true);
});

it("clears user A's failure on user B and ignores a late failed request for aborted user A", async () => {
  let rejectLateFirst!: (reason: Error) => void;
  const lateFirst = new Promise<Response>((_, reject) => { rejectLateFirst = reject; });
  const second = {
    ...member,
    id: "00000000-0000-4000-8000-000000000003",
    display_name: "두 번째 사용자",
  };
  let firstDetailCount = 0;
  const fetch = vi.fn<typeof globalThis.fetch>(async (input) => {
    const path = pathOf(input);
    if (path === "/api/v1/admin/access/technologies") return response(technologies);
    if (path === "/api/v1/admin/access/users?limit=50") {
      return response({ items: [member, second], next_cursor: null });
    }
    if (path === `/api/v1/admin/access/users/${member.id}`) {
      firstDetailCount += 1;
      if (firstDetailCount === 1) {
        return response({
          error: {
            code: "request_failed",
            message: "synthetic first-user failure",
            correlation_id: "synthetic",
          },
        }, 500);
      }
      return lateFirst;
    }
    if (path === `/api/v1/admin/access/users/${second.id}`) return response(second);
    if (path.includes("/audit?limit=50")) return response({ items: [], next_cursor: null });
    throw new Error(`Unexpected fetch: ${path}`);
  });
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);

  expect(await screen.findByRole("alert")).toHaveTextContent("선택한 사용자의 권한을 불러오지 못했습니다");
  const secondButton = screen.getByRole("button", { name: /두 번째 사용자/ });
  await user.click(secondButton);
  expect(await screen.findByRole("heading", { name: "두 번째 사용자" })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /합성 사용자/ }));
  await waitFor(() => expect(firstDetailCount).toBe(2));
  await user.click(secondButton);
  expect(await screen.findByRole("heading", { name: "두 번째 사용자" })).toBeVisible();
  await act(async () => rejectLateFirst(new Error("synthetic late first-user failure")));

  expect(screen.getByRole("heading", { name: "두 번째 사용자" })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  const lateFirstCall = fetch.mock.calls.filter(([input]) =>
    pathOf(input) === `/api/v1/admin/access/users/${member.id}`,
  )[1];
  expect(lateFirstCall?.[1]?.signal).toHaveProperty("aborted", true);
});

it("refreshes stale authority on 409 without silently resubmitting", async () => {
  const boundary = installBoundary([{ ...member, is_active: true }]);
  const original = boundary.fetch.getMockImplementation();
  boundary.fetch.mockImplementation(async (input, init) => {
    if (pathOf(input).endsWith("/technologies/rag") && init?.method === "PUT") {
      boundary.setStored({ ...member, is_active: true, revision: 9 });
      return response({ error: { code: "authority_revision_conflict", message: "stale", correlation_id: "synthetic" } }, 409);
    }
    return original!(input, init);
  });
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);
  const rag = await screen.findByRole("group", { name: "RAG 권한" });
  await user.click(within(rag).getByRole("checkbox", { name: "설정" }));
  await user.click(screen.getByRole("button", { name: "권한 저장" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "변경 저장" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("다른 변경이 먼저 저장되었습니다");
  expect(screen.getByText(/revision 9/)).toBeVisible();
  expect(boundary.fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("locks stale authority after a 409 refresh failure until explicit detail and audit retry succeeds", async () => {
  const boundary = installBoundary([{ ...member, is_active: true }]);
  const original = boundary.fetch.getMockImplementation();
  let failRefresh = false;
  boundary.fetch.mockImplementation(async (input, init) => {
    const path = pathOf(input);
    if (path.endsWith("/technologies/rag") && init?.method === "PUT") {
      boundary.setStored({ ...member, is_active: true, revision: 9 });
      failRefresh = true;
      return response({
        error: {
          code: "authority_revision_conflict",
          message: "stale",
          correlation_id: "synthetic",
        },
      }, 409);
    }
    if (
      failRefresh
      && path === `/api/v1/admin/access/users/${member.id}`
      && (!init?.method || init.method === "GET")
    ) {
      return response({
        error: {
          code: "request_failed",
          message: "refresh failed",
          correlation_id: "synthetic",
        },
      }, 500);
    }
    return original!(input, init);
  });
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);
  const rag = await screen.findByRole("group", { name: "RAG 권한" });
  await user.click(within(rag).getByRole("checkbox", { name: "설정" }));
  await user.click(screen.getByRole("button", { name: "권한 저장" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "변경 저장" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("최신 권한을 다시 불러오지 못했습니다");
  expect(screen.queryByRole("heading", { name: "합성 사용자" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "권한 저장" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "선택 다시 불러오기" })).toBeVisible();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(boundary.fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);

  failRefresh = false;
  await user.click(screen.getByRole("button", { name: "선택 다시 불러오기" }));
  expect(await screen.findByText(/revision 9/)).toBeVisible();
  expect(screen.getByRole("button", { name: "권한 저장" })).toBeDisabled();
  expect(boundary.fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
});

it("locks the editor and never announces success when a successful mutation cannot refresh detail or audit", async () => {
  const boundary = installBoundary([{ ...member, is_active: true }]);
  const original = boundary.fetch.getMockImplementation();
  let failAuditRefresh = false;
  boundary.fetch.mockImplementation(async (input, init) => {
    const path = pathOf(input);
    if (path.endsWith("/technologies/rag") && init?.method === "PUT") {
      const result = await original!(input, init);
      failAuditRefresh = true;
      return result;
    }
    if (
      failAuditRefresh
      && path === `/api/v1/admin/access/users/${member.id}/audit?limit=50`
    ) {
      return response({
        error: {
          code: "request_failed",
          message: "audit refresh failed",
          correlation_id: "synthetic",
        },
      }, 500);
    }
    return original!(input, init);
  });
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);
  const rag = await screen.findByRole("group", { name: "RAG 권한" });
  await user.click(within(rag).getByRole("checkbox", { name: "설정" }));
  await user.click(screen.getByRole("button", { name: "권한 저장" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "변경 저장" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("최신 상태를 확인하지 못했습니다");
  expect(screen.queryByRole("heading", { name: "합성 사용자" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "선택 다시 불러오기" })).toBeVisible();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(boundary.fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);

  failAuditRefresh = false;
  await user.click(screen.getByRole("button", { name: "선택 다시 불러오기" }));
  expect(await screen.findByText(/revision 5/)).toBeVisible();
  expect(screen.getByRole("button", { name: "권한 저장" })).toBeDisabled();
  expect(boundary.fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
});

it("allows only one mutation from rapid duplicate confirmation and cannot cancel the submitted request", async () => {
  const boundary = installBoundary([{ ...member, is_active: true }]);
  const original = boundary.fetch.getMockImplementation();
  let releaseMutation!: () => void;
  boundary.fetch.mockImplementation((input, init) => {
    if (pathOf(input).endsWith("/technologies/rag") && init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as {
        expected_revision: number;
        capabilities: Authority["technologies"][number]["capabilities"];
      };
      const updated: Authority = {
        ...boundary.getStored(),
        revision: body.expected_revision + 1,
        technologies: [{
          ...boundary.getStored().technologies[0],
          capabilities: body.capabilities,
        }],
      };
      return new Promise<Response>((resolve) => {
        releaseMutation = () => {
          boundary.setStored(updated);
          resolve(response(updated));
        };
      });
    }
    return original!(input, init);
  });
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);
  const rag = await screen.findByRole("group", { name: "RAG 권한" });
  await user.click(within(rag).getByRole("checkbox", { name: "설정" }));
  await user.click(screen.getByRole("button", { name: "권한 저장" }));
  const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: "변경 저장" });

  fireEvent.click(confirm);
  fireEvent.click(confirm);
  await waitFor(() => {
    expect(boundary.fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
  });
  expect(screen.getByRole("button", { name: "저장 중…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "취소" })).toBeDisabled();
  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();

  await act(async () => releaseMutation());
  expect(await screen.findByRole("status")).toHaveTextContent("저장했습니다");
  expect(boundary.fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
});

it("keeps mutation failure distinct from success and clears privileged detail on 403", async () => {
  const boundary = installBoundary([{ ...member, is_active: true }]);
  const original = boundary.fetch.getMockImplementation();
  boundary.fetch.mockImplementation(async (input, init) => {
    if (pathOf(input).endsWith("/technologies/rag") && init?.method === "PUT") {
      return response({ error: { code: "owner_required", message: "denied", correlation_id: "synthetic" } }, 403);
    }
    return original!(input, init);
  });
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);
  const rag = await screen.findByRole("group", { name: "RAG 권한" });
  await user.click(within(rag).getByRole("checkbox", { name: "설정" }));
  await user.click(screen.getByRole("button", { name: "권한 저장" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "변경 저장" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("권한 관리 접근이 거절되었습니다");
  expect(screen.getByRole("link", { name: "작업소로 이동" })).toHaveAttribute("href", "/workshop/workspaces");
  expect(screen.queryByRole("heading", { name: "합성 사용자" })).not.toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("shows inherited master capabilities and protects the last active master", async () => {
  installBoundary([owner]);
  render(<AccessManagementPage currentUser={currentUser} />);

  expect(await screen.findByRole("heading", { name: "테스트 마스터" })).toBeVisible();
  expect(screen.getByText("마스터 상속")).toBeVisible();
  expect(screen.getAllByRole("checkbox").every((checkbox) => checkbox.hasAttribute("disabled"))).toBe(true);
  expect(screen.getByRole("button", { name: "일반 사용자로 변경" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "계정 비활성화" })).toBeDisabled();
  expect(screen.getByText(/마지막 활성 마스터/)).toBeVisible();
});

it("contains modal focus, makes the background inert, closes on Escape, and restores the trigger", async () => {
  installBoundary([{ ...member, is_active: true }]);
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);
  const rag = await screen.findByRole("group", { name: "RAG 권한" });
  await user.click(within(rag).getByRole("checkbox", { name: "설정" }));
  const trigger = screen.getByRole("button", { name: "권한 저장" });
  const background = screen.getByRole("main");
  await user.click(trigger);

  const dialog = screen.getByRole("dialog", { name: "기술 권한 변경 확인" });
  const confirm = within(dialog).getByRole("button", { name: "변경 저장" });
  const cancel = within(dialog).getByRole("button", { name: "취소" });
  expect(background).toHaveAttribute("inert");
  expect(confirm).toHaveFocus();
  await user.keyboard("{Shift>}{Tab}{/Shift}");
  expect(cancel).toHaveFocus();
  await user.tab();
  expect(confirm).toHaveFocus();

  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(background).not.toHaveAttribute("inert");
  expect(trigger).toHaveFocus();
});

it("uses separate confirmations and current revisions for account and role changes", async () => {
  const boundary = installBoundary();
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);
  expect(await screen.findByRole("heading", { name: "합성 사용자" })).toBeVisible();

  await user.click(screen.getByRole("button", { name: "계정 활성화" }));
  const statusDialog = screen.getByRole("dialog", { name: "계정 상태 변경 확인" });
  expect(statusDialog).toHaveTextContent("expected revision 4");
  expect(statusDialog).toHaveTextContent("저장된 기술 권한이 잠재적으로 다시 적용");
  expect(boundary.fetch.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(false);
  await user.click(within(statusDialog).getByRole("button", { name: "변경 확인" }));
  expect(await screen.findByRole("button", { name: "계정 비활성화" })).toBeEnabled();

  await user.click(screen.getByRole("button", { name: "마스터로 변경" }));
  const roleDialog = screen.getByRole("dialog", { name: "역할 변경 확인" });
  expect(roleDialog).toHaveTextContent("expected revision 5");
  expect(roleDialog).toHaveTextContent("개별 grant가 제거");
  await user.click(within(roleDialog).getByRole("button", { name: "변경 확인" }));
  expect(await screen.findByText("마스터 상속")).toBeVisible();
  expect(screen.getByRole("button", { name: "일반 사용자로 변경" })).toHaveFocus();

  const patches = boundary.fetch.mock.calls.filter(([, init]) => init?.method === "PATCH");
  expect(patches.map(([input, init]) => [pathOf(input), init?.body])).toEqual([
    [
      `/api/v1/admin/access/users/${member.id}/status`,
      JSON.stringify({ expected_revision: 4, is_active: true }),
    ],
    [
      `/api/v1/admin/access/users/${member.id}/role`,
      JSON.stringify({ expected_revision: 5, role: "owner" }),
    ],
  ]);
});

it("paginates users and audit with cursor-only GET requests and retries an initial load failure", async () => {
  let initialFailed = false;
  const nextUser = { ...member, id: "00000000-0000-4000-8000-000000000004", display_name: "추가 사용자" };
  const fetch = vi.fn<typeof globalThis.fetch>(async (input, init) => {
    const path = pathOf(input);
    if (path === "/api/v1/admin/access/technologies" && !initialFailed) {
      initialFailed = true;
      return response({ error: { code: "request_failed", message: "failed", correlation_id: "synthetic" } }, 500);
    }
    if (path === "/api/v1/admin/access/technologies") return response(technologies);
    if (path === "/api/v1/admin/access/users?limit=50") return response({ items: [member], next_cursor: member.id });
    if (path === `/api/v1/admin/access/users?limit=50&cursor=${encodeURIComponent(member.id)}`) {
      return response({ items: [nextUser], next_cursor: null });
    }
    if (path === `/api/v1/admin/access/users/${member.id}`) return response(member);
    if (path === `/api/v1/admin/access/users/${member.id}/audit?limit=50`) {
      return response({ items: [audit], next_cursor: 8 });
    }
    if (path === `/api/v1/admin/access/users/${member.id}/audit?limit=50&cursor=8`) {
      return response({ items: [{ ...audit, id: 7, created_at: "2026-09-08T00:00:00Z" }], next_cursor: null });
    }
    throw new Error(`Unexpected fetch: ${init?.method ?? "GET"} ${path}`);
  });
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  render(<AccessManagementPage currentUser={currentUser} />);

  expect(await screen.findByRole("alert")).toHaveTextContent("권한 정보를 불러오지 못했습니다");
  await user.click(screen.getByRole("button", { name: "다시 시도" }));
  expect(await screen.findByRole("heading", { name: "합성 사용자" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "사용자 더 보기" }));
  expect(screen.getByRole("button", { name: /추가 사용자/ })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "이전 변경 더 보기" }));
  expect(screen.getAllByText(/기술 권한 변경/)).toHaveLength(2);

  for (const [input, init] of fetch.mock.calls.filter(([input]) => pathOf(input).includes("cursor="))) {
    expect(pathOf(input)).toMatch(/cursor=/);
    expect(init?.body).toBeUndefined();
    expect(init?.method).toBeUndefined();
  }
});
