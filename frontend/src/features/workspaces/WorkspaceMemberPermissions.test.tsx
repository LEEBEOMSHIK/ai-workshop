import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { WorkspaceMemberPermissions } from "./WorkspaceMemberPermissions";

const owner = {
  user_id: "owner-id",
  display_name: "공간 소유자",
  role: "owner",
  is_active: true,
  read: true,
  write: true,
  delete: true,
  permission_revision: 2,
} as const;

const member = {
  user_id: "member-id",
  display_name: "김연구",
  role: "member",
  is_active: true,
  read: true,
  write: false,
  delete: false,
  permission_revision: 7,
} as const;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("keeps member management hidden and does not fetch members without the server capability", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({ read: true, write: true, delete: false, manage_members: false }));
  vi.stubGlobal("fetch", fetcher);

  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await act(async () => undefined);
  expect(screen.queryByRole("button", { name: "구성원 권한 관리" })).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/workspaces/workspace-1/capabilities",
    expect.objectContaining({ credentials: "include", signal: expect.any(AbortSignal) }),
  );
});

it("opens an accessible inline panel and renders owner and inactive rows as read-only", async () => {
  let resolveMembers!: (response: Response) => void;
  const membersResponse = new Promise<Response>((resolve) => { resolveMembers = resolve; });
  const inactive = { ...member, user_id: "inactive-id", display_name: "퇴사한 구성원", is_active: false };
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: true, manage_members: true });
    if (path.includes("/members")) return membersResponse;
    throw new Error(`Unexpected request: ${path}`);
  }));
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  const trigger = await screen.findByRole("button", { name: "구성원 권한 관리" });
  await user.click(trigger);
  expect(trigger).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("status")).toHaveTextContent("구성원을 불러오는 중");
  await act(async () => resolveMembers(Response.json({ items: [owner, inactive], next_after: null })));

  expect(await screen.findByRole("region", { name: "구성원 권한 관리" })).toBeVisible();
  expect(screen.getByText("공간 소유자")).toBeVisible();
  expect(screen.getByText("소유자 권한은 변경할 수 없습니다.")).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "공간 소유자 읽기" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "퇴사한 구성원 읽기" })).toBeDisabled();
  expect(screen.getByText("비활성 계정")).toBeVisible();
  expect(screen.getByText(/삭제 권한은 저장만 되며/)).toBeVisible();
});

it("enforces read dependencies and saves one row with its original revision", async () => {
  const grantedMember = { ...member, write: true, delete: true };
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: true, manage_members: true });
    if (init?.method === "PUT") return Response.json({ ...member, read: true, write: true, delete: false, permission_revision: 8 });
    if (path.includes("/members")) return Response.json({ items: [grantedMember], next_after: null });
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  const read = await screen.findByRole("checkbox", { name: "김연구 읽기" });
  const write = screen.getByRole("checkbox", { name: "김연구 쓰기" });
  const remove = screen.getByRole("checkbox", { name: "김연구 삭제" });
  await user.click(read);
  expect(write).not.toBeChecked();
  expect(remove).not.toBeChecked();
  expect(write).toBeDisabled();
  expect(remove).toBeDisabled();
  await user.click(read);
  await user.click(write);
  await user.click(screen.getByRole("button", { name: "김연구 권한 저장" }));

  expect(await screen.findByText("김연구 권한을 저장했습니다.")).toBeVisible();
  const put = fetcher.mock.calls.find(([, init]) => init?.method === "PUT");
  expect(put?.[0]).toBe("/api/v1/workspaces/workspace-1/members/member-id");
  expect(JSON.parse(String(put?.[1]?.body))).toEqual({ read: true, write: true, delete: false, expected_revision: 7 });
});

it("does not auto-save and blocks duplicate submission while a row save is pending", async () => {
  let resolveSave!: (response: Response) => void;
  const saveResponse = new Promise<Response>((resolve) => { resolveSave = resolve; });
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: true, manage_members: true });
    if (init?.method === "PUT") return saveResponse;
    return Response.json({ items: [member], next_after: null });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  await user.click(await screen.findByRole("checkbox", { name: "김연구 쓰기" }));
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(0);
  const save = screen.getByRole("button", { name: "김연구 권한 저장" });
  await user.click(save);
  expect(save).toBeDisabled();
  await user.click(save);
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
  await act(async () => resolveSave(Response.json({ ...member, write: true, permission_revision: 8 })));
  expect(await screen.findByText("김연구 권한을 저장했습니다.")).toBeVisible();
});

it("keeps an unsaved draft after a failed save and retries with the same original revision", async () => {
  let saves = 0;
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: true, manage_members: true });
    if (init?.method === "PUT") {
      saves += 1;
      return saves === 1
        ? Response.json({ error: { code: "temporary", message: "private", correlation_id: "synthetic" } }, { status: 500 })
        : Response.json({ ...member, write: true, permission_revision: 8 });
    }
    return Response.json({ items: [member], next_after: null });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  await user.click(await screen.findByRole("checkbox", { name: "김연구 쓰기" }));
  const save = screen.getByRole("button", { name: "김연구 권한 저장" });
  await user.click(save);
  expect(await screen.findByRole("alert")).toHaveTextContent("권한을 저장하지 못했습니다");
  expect(screen.getByRole("checkbox", { name: "김연구 쓰기" })).toBeChecked();
  expect(screen.queryByText("김연구 권한을 저장했습니다.")).not.toBeInTheDocument();
  await user.click(save);
  expect(await screen.findByText("김연구 권한을 저장했습니다.")).toBeVisible();
  const payloads = fetcher.mock.calls
    .filter(([, init]) => init?.method === "PUT")
    .map(([, init]) => JSON.parse(String(init?.body)));
  expect(payloads).toEqual([
    { read: true, write: true, delete: false, expected_revision: 7 },
    { read: true, write: true, delete: false, expected_revision: 7 },
  ]);
});

it("shows list errors with retry and appends the next member page", async () => {
  let listCalls = 0;
  const second = { ...member, user_id: "member-2", display_name: "박연구", permission_revision: 1 };
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: true, manage_members: true });
    listCalls += 1;
    if (listCalls === 1) return Response.json({ error: { code: "temporary", message: "private", correlation_id: "synthetic" } }, { status: 500 });
    if (path.includes("after=next-page")) return Response.json({ items: [second], next_after: null });
    return Response.json({ items: [member], next_after: "next-page" });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("구성원 목록을 불러오지 못했습니다");
  await user.click(screen.getByRole("button", { name: "다시 시도" }));
  expect(await screen.findByText("김연구")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "구성원 더 보기" }));
  expect(await screen.findByText("박연구")).toBeVisible();
  expect(fetcher.mock.calls.some(([input]) => String(input).includes("after=next-page"))).toBe(true);
});

it("locks a stale row on conflict until the owner explicitly refreshes the list", async () => {
  let listCalls = 0;
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: true, manage_members: true });
    if (init?.method === "PUT") return Response.json({ error: { code: "workspace_member_revision_conflict", message: "private", correlation_id: "synthetic" } }, { status: 409 });
    listCalls += 1;
    return Response.json({ items: [{ ...member, permission_revision: listCalls === 1 ? 7 : 8 }], next_after: null });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  await user.click(await screen.findByRole("checkbox", { name: "김연구 쓰기" }));
  await user.click(screen.getByRole("button", { name: "김연구 권한 저장" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("다른 변경이 먼저 저장되었습니다");
  expect(screen.getByRole("checkbox", { name: "김연구 읽기" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "김연구 권한 저장" })).toBeDisabled();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "구성원 목록 새로고침" }));
  expect(await screen.findByRole("checkbox", { name: "김연구 읽기" })).toBeEnabled();
  expect(listCalls).toBe(2);
});

it.each([401, 403, 404])("clears and hides member management after authorization is lost with %s", async (status) => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: true, manage_members: true });
    return Response.json({ error: { code: "not_found", message: "private", correlation_id: "synthetic" } }, { status });
  }));
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  await act(async () => undefined);
  expect(screen.queryByRole("button", { name: "구성원 권한 관리" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "구성원 권한 관리" })).not.toBeInTheDocument();
});

it("announces capability revalidation while opening the panel", async () => {
  let capabilityCalls = 0;
  let resolveRevalidation!: (response: Response) => void;
  const revalidation = new Promise<Response>((resolve) => { resolveRevalidation = resolve; });
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) {
      capabilityCalls += 1;
      return capabilityCalls === 1
        ? Response.json({ read: true, write: true, delete: true, manage_members: true })
        : revalidation;
    }
    return Response.json({ items: [], next_after: null });
  }));
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  expect(screen.getByRole("status")).toHaveTextContent("권한 확인 중");
  await act(async () => resolveRevalidation(Response.json({ read: true, write: true, delete: true, manage_members: true })));
  expect(await screen.findByRole("region", { name: "구성원 권한 관리" })).toBeVisible();
});

it("aborts opening capability revalidation on unmount before it can fetch members", async () => {
  let capabilityCalls = 0;
  let resolveRevalidation!: (response: Response) => void;
  const revalidation = new Promise<Response>((resolve) => { resolveRevalidation = resolve; });
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) {
      capabilityCalls += 1;
      return capabilityCalls === 1
        ? Response.json({ read: true, write: true, delete: true, manage_members: true })
        : revalidation;
    }
    return Response.json({ items: [member], next_after: null });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  const view = render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);
  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));

  view.unmount();
  await act(async () => resolveRevalidation(Response.json({ read: true, write: true, delete: true, manage_members: true })));

  expect(fetcher.mock.calls.filter(([input]) => String(input).includes("/members"))).toHaveLength(0);
});

it("never publishes a late capability result from a previous workspace", async () => {
  let resolveOld!: (response: Response) => void;
  const oldResponse = new Promise<Response>((resolve) => { resolveOld = resolve; });
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.includes("workspace-old")) return oldResponse;
    return Response.json({ read: true, write: true, delete: false, manage_members: false });
  }));
  const { rerender } = render(<WorkspaceMemberPermissions workspaceId="workspace-old" />);

  rerender(<WorkspaceMemberPermissions workspaceId="workspace-new" />);
  await act(async () => resolveOld(Response.json({ read: true, write: true, delete: true, manage_members: true })));

  expect(screen.queryByRole("button", { name: "구성원 권한 관리" })).not.toBeInTheDocument();
});

it("never publishes a late member page from a previous workspace", async () => {
  let resolveOldMembers!: (response: Response) => void;
  const oldMembers = new Promise<Response>((resolve) => { resolveOldMembers = resolve; });
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) {
      return Response.json({ read: true, write: true, delete: true, manage_members: path.includes("workspace-old") });
    }
    if (path.includes("workspace-old/members")) return oldMembers;
    throw new Error(`Unexpected request: ${path}`);
  }));
  const user = userEvent.setup();
  const { rerender } = render(<WorkspaceMemberPermissions workspaceId="workspace-old" />);
  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));

  rerender(<WorkspaceMemberPermissions workspaceId="workspace-new" />);
  await act(async () => resolveOldMembers(Response.json({ items: [member], next_after: null })));

  expect(screen.queryByText("김연구")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "구성원 권한 관리" })).not.toBeInTheDocument();
});

it("never publishes a late save result from a previous workspace", async () => {
  let resolveOldSave!: (response: Response) => void;
  const oldSave = new Promise<Response>((resolve) => { resolveOldSave = resolve; });
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) {
      return Response.json({ read: true, write: true, delete: true, manage_members: path.includes("workspace-old") });
    }
    if (init?.method === "PUT") return oldSave;
    if (path.includes("workspace-old/members")) return Response.json({ items: [member], next_after: null });
    throw new Error(`Unexpected request: ${path}`);
  }));
  const user = userEvent.setup();
  const { rerender } = render(<WorkspaceMemberPermissions workspaceId="workspace-old" />);
  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  await user.click(await screen.findByRole("checkbox", { name: "김연구 쓰기" }));
  await user.click(screen.getByRole("button", { name: "김연구 권한 저장" }));

  rerender(<WorkspaceMemberPermissions workspaceId="workspace-new" />);
  await act(async () => resolveOldSave(Response.json({ ...member, write: true, permission_revision: 8 })));

  expect(screen.queryByText("김연구 권한을 저장했습니다.")).not.toBeInTheDocument();
  expect(screen.queryByText("김연구")).not.toBeInTheDocument();
});

it("aborts and discards a late member page when the panel closes, then refetches access and members on reopen", async () => {
  let resolveFirstMembers!: (response: Response) => void;
  const firstMembers = new Promise<Response>((resolve) => { resolveFirstMembers = resolve; });
  let capabilityCalls = 0;
  let memberCalls = 0;
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) {
      capabilityCalls += 1;
      return Response.json({ read: true, write: true, delete: true, manage_members: true });
    }
    memberCalls += 1;
    return memberCalls === 1 ? firstMembers : Response.json({ items: [{ ...member, display_name: "새 목록" }], next_after: null });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  await user.click(screen.getByRole("button", { name: "구성원 권한 관리" }));
  await act(async () => resolveFirstMembers(Response.json({ items: [member], next_after: null })));
  expect(screen.queryByText("김연구")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "구성원 권한 관리" }));
  expect(await screen.findByText("새 목록")).toBeVisible();
  expect(capabilityCalls).toBe(3);
  expect(memberCalls).toBe(2);
});

it("discards a late save success after the panel closes", async () => {
  let resolveSave!: (response: Response) => void;
  const pendingSave = new Promise<Response>((resolve) => { resolveSave = resolve; });
  let memberCalls = 0;
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: true, manage_members: true });
    if (init?.method === "PUT") return pendingSave;
    memberCalls += 1;
    return Response.json({ items: [member], next_after: null });
  }));
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  await user.click(await screen.findByRole("checkbox", { name: "김연구 쓰기" }));
  await user.click(screen.getByRole("button", { name: "김연구 권한 저장" }));
  await user.click(screen.getByRole("button", { name: "구성원 권한 관리" }));
  await act(async () => resolveSave(Response.json({ ...member, write: true, permission_revision: 8 })));

  expect(screen.queryByText("김연구 권한을 저장했습니다.")).not.toBeInTheDocument();
  expect(screen.queryByText("김연구")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "구성원 권한 관리" }));
  expect(await screen.findByRole("checkbox", { name: "김연구 쓰기" })).not.toBeChecked();
  expect(memberCalls).toBe(2);
});

it("discards an unsaved draft on close and reloads the stored permissions on reopen", async () => {
  let capabilityCalls = 0;
  let memberCalls = 0;
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) {
      capabilityCalls += 1;
      return Response.json({ read: true, write: true, delete: true, manage_members: true });
    }
    memberCalls += 1;
    return Response.json({ items: [member], next_after: null });
  }));
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  await user.click(await screen.findByRole("checkbox", { name: "김연구 쓰기" }));
  expect(screen.getByRole("checkbox", { name: "김연구 쓰기" })).toBeChecked();
  await user.click(screen.getByRole("button", { name: "구성원 권한 관리" }));
  await user.click(screen.getByRole("button", { name: "구성원 권한 관리" }));

  expect(await screen.findByRole("checkbox", { name: "김연구 쓰기" })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "김연구 권한 저장" })).toBeDisabled();
  expect(capabilityCalls).toBe(3);
  expect(memberCalls).toBe(2);
});

it("keeps conflict refresh disabled while another row save is pending", async () => {
  let resolveSecondSave!: (response: Response) => void;
  const secondSave = new Promise<Response>((resolve) => { resolveSecondSave = resolve; });
  const second = { ...member, user_id: "member-2", display_name: "박연구", permission_revision: 4 };
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: true, manage_members: true });
    if (init?.method === "PUT" && path.endsWith("/member-2")) return secondSave;
    if (init?.method === "PUT") return Response.json({ error: { code: "workspace_member_revision_conflict", message: "private", correlation_id: "synthetic" } }, { status: 409 });
    return Response.json({ items: [member, second], next_after: null });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  await user.click(await screen.findByRole("checkbox", { name: "박연구 쓰기" }));
  await user.click(screen.getByRole("button", { name: "박연구 권한 저장" }));
  await user.click(screen.getByRole("checkbox", { name: "김연구 쓰기" }));
  await user.click(screen.getByRole("button", { name: "김연구 권한 저장" }));

  const refresh = await screen.findByRole("button", { name: "구성원 목록 새로고침" });
  expect(refresh).toBeDisabled();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(2);
  await act(async () => resolveSecondSave(Response.json({ ...second, write: true, permission_revision: 5 })));
  expect(refresh).toBeEnabled();
});

it("shows a retryable error without discarding rows or the cursor when pagination fails", async () => {
  let memberCalls = 0;
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: true, manage_members: true });
    memberCalls += 1;
    return memberCalls === 1
      ? Response.json({ items: [member], next_after: "next-page" })
      : Response.json({ error: { code: "temporary", message: "private", correlation_id: "synthetic" } }, { status: 500 });
  }));
  const user = userEvent.setup();
  render(<WorkspaceMemberPermissions workspaceId="workspace-1" />);

  await user.click(await screen.findByRole("button", { name: "구성원 권한 관리" }));
  await user.click(await screen.findByRole("button", { name: "구성원 더 보기" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("다음 구성원을 불러오지 못했습니다");
  expect(screen.getByText("김연구")).toBeVisible();
  expect(screen.getByRole("button", { name: "구성원 더 보기" })).toBeEnabled();
});
