"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../../shared/api/client";
import { getWorkspaceCapabilities, listWorkspaceMembers, putWorkspaceMember, type WorkspaceMember } from "./api";
import styles from "./WorkspaceMemberPermissions.module.css";

type CapabilityState = "checking" | "allowed" | "denied" | "error";
type MembersState = "idle" | "loading" | "ready" | "error";
interface PermissionDraft { read: boolean; write: boolean; delete: boolean }
interface MemberEditor {
  member: WorkspaceMember;
  draft: PermissionDraft;
  saving: boolean;
  conflict: boolean;
  error: string;
  savedMessage: string;
}

export function WorkspaceMemberPermissions({ workspaceId }: { workspaceId: string }) {
  return <WorkspaceMemberPermissionsScope key={workspaceId} workspaceId={workspaceId} />;
}

function WorkspaceMemberPermissionsScope({ workspaceId }: { workspaceId: string }) {
  const capabilityController = useRef<AbortController | null>(null);
  const membersController = useRef<AbortController | null>(null);
  const saveControllers = useRef(new Map<string, AbortController>());
  const [capabilityState, setCapabilityState] = useState<CapabilityState>("checking");
  const [capabilityRetry, setCapabilityRetry] = useState(0);
  const [open, setOpen] = useState(false);
  const [opening, setOpening] = useState(false);
  const [membersState, setMembersState] = useState<MembersState>("idle");
  const [rows, setRows] = useState<MemberEditor[]>([]);
  const [nextAfter, setNextAfter] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState("");

  const abortMemberWork = useCallback(() => {
    membersController.current?.abort();
    membersController.current = null;
    saveControllers.current.forEach((controller) => controller.abort());
    saveControllers.current.clear();
  }, []);

  const hideManagement = useCallback(() => {
    abortMemberWork();
    setCapabilityState("denied");
    setOpen(false);
    setOpening(false);
    setMembersState("idle");
    setRows([]);
    setNextAfter(null);
    setLoadingMore(false);
    setMoreError("");
  }, [abortMemberWork]);

  useEffect(() => {
    const requestWorkspaceId = workspaceId;
    capabilityController.current?.abort();
    abortMemberWork();
    const controller = new AbortController();
    capabilityController.current = controller;
    void getWorkspaceCapabilities(requestWorkspaceId, controller.signal).then((capabilities) => {
      if (controller.signal.aborted || capabilityController.current !== controller) return;
      setCapabilityState(capabilities.manage_members ? "allowed" : "denied");
    }).catch((failure: unknown) => {
      if (controller.signal.aborted || capabilityController.current !== controller) return;
      setCapabilityState(isAuthorizationFailure(failure) ? "denied" : "error");
    });
    return () => {
      controller.abort();
      capabilityController.current?.abort();
      capabilityController.current = null;
      abortMemberWork();
    };
  }, [abortMemberWork, capabilityRetry, workspaceId]);

  const loadMembers = useCallback(async (after: string | null = null, append = false) => {
    const requestWorkspaceId = workspaceId;
    membersController.current?.abort();
    const controller = new AbortController();
    membersController.current = controller;
    if (append) setLoadingMore(true);
    else {
      setMembersState("loading");
      setRows([]);
      setNextAfter(null);
    }
    setMoreError("");
    try {
      const page = await listWorkspaceMembers(requestWorkspaceId, after, controller.signal);
      if (controller.signal.aborted || membersController.current !== controller) return;
      setRows((current) => append ? mergeMemberRows(current, page.items) : page.items.map(createEditor));
      setNextAfter(page.next_after ?? null);
      setMembersState("ready");
    } catch (failure) {
      if (controller.signal.aborted || membersController.current !== controller) return;
      if (isAuthorizationFailure(failure)) hideManagement();
      else if (append) setMoreError("다음 구성원을 불러오지 못했습니다. 다시 시도해 주세요.");
      else setMembersState("error");
    } finally {
      if (membersController.current === controller) {
        membersController.current = null;
        setLoadingMore(false);
      }
    }
  }, [hideManagement, workspaceId]);

  async function openPanel() {
    const requestWorkspaceId = workspaceId;
    capabilityController.current?.abort();
    const controller = new AbortController();
    capabilityController.current = controller;
    setOpening(true);
    try {
      const capabilities = await getWorkspaceCapabilities(requestWorkspaceId, controller.signal);
      if (controller.signal.aborted || capabilityController.current !== controller) return;
      if (!capabilities.manage_members) {
        hideManagement();
        return;
      }
      setCapabilityState("allowed");
      setOpen(true);
      setOpening(false);
      void loadMembers();
    } catch (failure) {
      if (controller.signal.aborted || capabilityController.current !== controller) return;
      if (isAuthorizationFailure(failure)) hideManagement();
      else setCapabilityState("error");
    } finally {
      if (capabilityController.current === controller) setOpening(false);
    }
  }

  function togglePanel() {
    if (capabilityState !== "allowed") return;
    if (!open) {
      if (!opening) void openPanel();
      return;
    }
    capabilityController.current?.abort();
    abortMemberWork();
    setOpen(false);
    setOpening(false);
    setMembersState("idle");
    setRows([]);
    setNextAfter(null);
    setLoadingMore(false);
    setMoreError("");
  }

  function updateDraft(userId: string, permission: keyof PermissionDraft, checked: boolean) {
    setRows((current) => current.map((row) => {
      if (row.member.user_id !== userId || isLocked(row)) return row;
      const draft = permission === "read" && !checked
        ? { read: false, write: false, delete: false }
        : { ...row.draft, [permission]: checked };
      return { ...row, draft, error: "", savedMessage: "" };
    }));
  }

  async function saveRow(userId: string) {
    const requestWorkspaceId = workspaceId;
    const row = rows.find((candidate) => candidate.member.user_id === userId);
    if (!row || isLocked(row) || !hasChanges(row) || saveControllers.current.has(userId)) return;
    const controller = new AbortController();
    saveControllers.current.set(userId, controller);
    setRows((current) => updateEditor(current, userId, (editor) => ({ ...editor, saving: true, error: "", savedMessage: "" })));
    try {
      const saved = await putWorkspaceMember(requestWorkspaceId, userId, {
        ...row.draft,
        expected_revision: row.member.permission_revision,
      }, controller.signal);
      if (controller.signal.aborted || saveControllers.current.get(userId) !== controller) return;
      setRows((current) => updateEditor(current, userId, () => ({
        member: saved,
        draft: permissionDraft(saved),
        saving: false,
        conflict: false,
        error: "",
        savedMessage: `${saved.display_name} 권한을 저장했습니다.`,
      })));
    } catch (failure) {
      if (controller.signal.aborted || saveControllers.current.get(userId) !== controller) return;
      if (isAuthorizationFailure(failure)) hideManagement();
      else if (failure instanceof ApiError && failure.status === 409) {
        setRows((current) => updateEditor(current, userId, (editor) => ({ ...editor, saving: false, conflict: true, error: "다른 변경이 먼저 저장되었습니다. 구성원 목록을 새로고침해 주세요." })));
      } else {
        setRows((current) => updateEditor(current, userId, (editor) => ({ ...editor, saving: false, error: "권한을 저장하지 못했습니다. 변경 내용을 확인한 뒤 다시 시도해 주세요." })));
      }
    } finally {
      if (saveControllers.current.get(userId) === controller) saveControllers.current.delete(userId);
    }
  }

  if (capabilityState === "error") return <div className={styles.capabilityError} role="alert"><span>구성원 관리 권한을 확인하지 못했습니다.</span><button type="button" onClick={() => { setCapabilityState("checking"); setCapabilityRetry((value) => value + 1); }}>권한 확인 다시 시도</button></div>;
  if (capabilityState !== "allowed") return null;
  const hasConflict = rows.some((row) => row.conflict);
  const hasSaving = rows.some((row) => row.saving);

  return <section className={styles.wrapper}>
    <button type="button" className={styles.trigger} aria-expanded={open} aria-controls="workspace-member-permissions" disabled={opening} onClick={togglePanel}>구성원 권한 관리</button>
    {opening ? <p className={styles.openingStatus} role="status">권한 확인 중…</p> : null}
    {open ? <section id="workspace-member-permissions" className={styles.panel} role="region" aria-label="구성원 권한 관리">
      <div className={styles.panelHeader}>
        <div><h2>구성원 권한 관리</h2><p>회사 공간의 기존 구성원에게 파일 읽기·쓰기·삭제 권한을 부여합니다.</p></div>
        {hasConflict ? <button type="button" disabled={hasSaving} onClick={() => void loadMembers()}>구성원 목록 새로고침</button> : null}
      </div>
      <p className={styles.notice}>삭제 권한은 저장만 되며 삭제·휴지통 기능은 아직 제공되지 않습니다.</p>
      {membersState === "loading" ? <p role="status">구성원을 불러오는 중…</p> : null}
      {membersState === "error" ? <div className={styles.error} role="alert"><p>구성원 목록을 불러오지 못했습니다.</p><button type="button" onClick={() => void loadMembers()}>다시 시도</button></div> : null}
      {membersState === "ready" && rows.length === 0 ? <p className={styles.empty}>표시할 구성원이 없습니다.</p> : null}
      {rows.length > 0 ? <ul className={styles.memberList}>{rows.map((row) => <MemberRow key={row.member.user_id} row={row} onChange={updateDraft} onSave={saveRow} />)}</ul> : null}
      {moreError ? <p className={styles.rowError} role="alert">{moreError}</p> : null}
      {membersState === "ready" && nextAfter ? <button type="button" disabled={loadingMore} onClick={() => void loadMembers(nextAfter, true)}>{loadingMore ? "구성원 불러오는 중…" : "구성원 더 보기"}</button> : null}
    </section> : null}
  </section>;
}

function MemberRow({ row, onChange, onSave }: { row: MemberEditor; onChange: (userId: string, permission: keyof PermissionDraft, checked: boolean) => void; onSave: (userId: string) => void }) {
  const { member, draft } = row;
  const locked = isLocked(row);
  const owner = member.role === "owner";
  return <li className={styles.memberRow}>
    <div className={styles.memberIdentity}><strong>{member.display_name}</strong><span>{owner ? "소유자" : "구성원"}</span>{!member.is_active ? <span className={styles.inactive}>비활성 계정</span> : null}</div>
    {owner ? <p className={styles.rowNote}>소유자 권한은 변경할 수 없습니다.</p> : null}
    <fieldset className={styles.permissions} disabled={locked}>
      <legend className={styles.visuallyHidden}>{member.display_name} 권한</legend>
      <label><input type="checkbox" aria-label={`${member.display_name} 읽기`} checked={draft.read} onChange={(event) => onChange(member.user_id, "read", event.target.checked)} /> 읽기</label>
      <label><input type="checkbox" aria-label={`${member.display_name} 쓰기`} checked={draft.write} disabled={locked || !draft.read} onChange={(event) => onChange(member.user_id, "write", event.target.checked)} /> 쓰기</label>
      <label><input type="checkbox" aria-label={`${member.display_name} 삭제`} checked={draft.delete} disabled={locked || !draft.read} onChange={(event) => onChange(member.user_id, "delete", event.target.checked)} /> 삭제</label>
    </fieldset>
    <button type="button" disabled={locked || !hasChanges(row)} onClick={() => onSave(member.user_id)}>{member.display_name} 권한 저장</button>
    {row.error ? <p className={styles.rowError} role="alert">{row.error}</p> : null}
    {row.savedMessage ? <p className={styles.saved} role="status">{row.savedMessage}</p> : null}
  </li>;
}

function permissionDraft(member: WorkspaceMember): PermissionDraft { return { read: member.read, write: member.write, delete: member.delete }; }
function createEditor(member: WorkspaceMember): MemberEditor { return { member, draft: permissionDraft(member), saving: false, conflict: false, error: "", savedMessage: "" }; }
function mergeMemberRows(current: MemberEditor[], additions: WorkspaceMember[]): MemberEditor[] {
  const existing = new Set(current.map((row) => row.member.user_id));
  return [...current, ...additions.filter((member) => !existing.has(member.user_id)).map(createEditor)];
}
function updateEditor(rows: MemberEditor[], userId: string, update: (row: MemberEditor) => MemberEditor): MemberEditor[] { return rows.map((row) => row.member.user_id === userId ? update(row) : row); }
function hasChanges(row: MemberEditor): boolean { return row.draft.read !== row.member.read || row.draft.write !== row.member.write || row.draft.delete !== row.member.delete; }
function isLocked(row: MemberEditor): boolean { return row.member.role === "owner" || !row.member.is_active || row.saving || row.conflict; }
function isAuthorizationFailure(failure: unknown): boolean { return failure instanceof ApiError && (failure.status === 401 || failure.status === 403 || failure.status === 404); }
