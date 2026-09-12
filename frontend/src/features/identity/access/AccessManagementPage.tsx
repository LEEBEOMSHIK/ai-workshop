"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { SessionUser } from "../session";
import { ApiError } from "../../../shared/api/client";
import { routes } from "../../../shared/routing/routes";
import {
  getUserAuthority,
  listAuthorityAudit,
  listAuthorityUsers,
  listTechnologyCatalog,
  updateTechnologyGrant,
  updateUserRole,
  updateUserStatus,
  type AuthorityAudit,
  type Capability,
  type TechnologyCatalog,
  type UserAuthority,
  type UserAuthorityPage,
  type UserRole,
} from "./api";
import {
  AccessAuthorityDetail,
  AccessConfirmationDialog,
  AccessDirectory,
  type AccessConfirmation,
  type AccessDraft,
} from "./AccessManagementSections";
import styles from "./AccessManagement.module.css";

const capabilities: readonly Capability[] = ["view", "configure", "execute"];

function ordered(values: readonly Capability[]): Capability[] {
  const selected = new Set(values);
  return capabilities.filter((capability) => selected.has(capability));
}

function sameCapabilities(left: readonly Capability[], right: readonly Capability[]): boolean {
  const normalizedLeft = ordered(left);
  const normalizedRight = ordered(right);
  return normalizedLeft.length === normalizedRight.length
    && normalizedLeft.every((value, index) => value === normalizedRight[index]);
}

function draftFrom(authority: UserAuthority): AccessDraft {
  return Object.fromEntries(
    authority.technologies.map((technology) => [
      technology.key,
      ordered(technology.capabilities),
    ]),
  );
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function fetchDirectory(
  signal: AbortSignal,
): Promise<[TechnologyCatalog[], UserAuthorityPage]> {
  return Promise.all([
    listTechnologyCatalog(signal),
    listAuthorityUsers(null, signal),
  ]);
}

export function AccessManagementPage({ currentUser }: { currentUser: SessionUser }) {
  const [catalog, setCatalog] = useState<TechnologyCatalog[]>([]);
  const [users, setUsers] = useState<UserAuthority[]>([]);
  const [usersCursor, setUsersCursor] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<UserAuthority | null>(null);
  const [draft, setDraft] = useState<AccessDraft>({});
  const [auditItems, setAuditItems] = useState<AuthorityAudit[]>([]);
  const [auditCursor, setAuditCursor] = useState<number | null>(null);
  const [loadingDirectory, setLoadingDirectory] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingMoreUsers, setLoadingMoreUsers] = useState(false);
  const [loadingMoreAudit, setLoadingMoreAudit] = useState(false);
  const [detailRequestVersion, setDetailRequestVersion] = useState(0);
  const [confirmation, setConfirmation] = useState<AccessConfirmation | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [prerequisiteError, setPrerequisiteError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const submitPending = useRef(false);
  const directoryRequest = useRef<AbortController | null>(null);
  const selectedIdRef = useRef<string | null>(null);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  const denyPrivilegedView = useCallback(() => {
    setForbidden(true);
    setUsers([]);
    setSelectedId(null);
    setDetail(null);
    setDraft({});
    setAuditItems([]);
    setConfirmation(null);
    setNotice(null);
    setError("권한 관리 접근이 거절되었습니다. 현재 계정으로는 이 정보를 볼 수 없습니다.");
  }, []);

  const replaceDirectoryUser = useCallback((authority: UserAuthority) => {
    setUsers((current) => current.map((user) =>
      user.id === authority.id ? authority : user));
  }, []);

  const requireFreshAuthority = useCallback((message: string) => {
    setDetail(null);
    setDraft({});
    setAuditItems([]);
    setAuditCursor(null);
    setConfirmation(null);
    setNotice(null);
    setPrerequisiteError(null);
    setError(message);
  }, []);

  const receiveDirectory = useCallback((
    [technologyItems, page]: [TechnologyCatalog[], UserAuthorityPage],
  ) => {
    setCatalog(technologyItems);
    setUsers(page.items);
    setUsersCursor(page.next_cursor);
    const firstUserId = page.items[0]?.id ?? null;
    selectedIdRef.current = firstUserId;
    setLoadingDetail(firstUserId !== null);
    setSelectedId(firstUserId);
    if (page.items.length === 0) {
      setDetail(null);
      setDraft({});
      setAuditItems([]);
    }
  }, []);

  const handleDirectoryFailure = useCallback((failure: unknown) => {
    if (isAbort(failure)) return;
    if (failure instanceof ApiError && failure.status === 403) {
      denyPrivilegedView();
    } else {
      setError("권한 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
    }
  }, [denyPrivilegedView]);

  useEffect(() => {
    const controller = new AbortController();
    directoryRequest.current = controller;
    void fetchDirectory(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) receiveDirectory(result);
      })
      .catch(handleDirectoryFailure)
      .finally(() => {
        if (!controller.signal.aborted) setLoadingDirectory(false);
      });
    return () => controller.abort();
  }, [handleDirectoryFailure, receiveDirectory]);

  function startDirectoryLoad() {
    directoryRequest.current?.abort();
    const controller = new AbortController();
    directoryRequest.current = controller;
    setLoadingDirectory(true);
    setForbidden(false);
    setError(null);
    setNotice(null);
    void fetchDirectory(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) receiveDirectory(result);
      })
      .catch(handleDirectoryFailure)
      .finally(() => {
        if (!controller.signal.aborted) setLoadingDirectory(false);
      });
  }

  const applyAuthority = useCallback((authority: UserAuthority, audits: AuthorityAudit[], nextAuditCursor: number | null) => {
    if (selectedIdRef.current !== authority.id) return;
    setDetail(authority);
    setDraft(draftFrom(authority));
    setAuditItems(audits);
    setAuditCursor(nextAuditCursor);
    replaceDirectoryUser(authority);
    setPrerequisiteError(null);
  }, [replaceDirectoryUser]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    void Promise.all([
      getUserAuthority(selectedId, controller.signal),
      listAuthorityAudit(selectedId, null, controller.signal),
    ]).then(([authority, auditPage]) => {
      if (!controller.signal.aborted) {
        applyAuthority(authority, auditPage.items, auditPage.next_cursor);
      }
    }).catch((failure: unknown) => {
      if (controller.signal.aborted || selectedIdRef.current !== selectedId) return;
      if (isAbort(failure)) return;
      if (failure instanceof ApiError && failure.status === 403) {
        denyPrivilegedView();
      } else {
        setError("선택한 사용자의 권한을 불러오지 못했습니다. 다시 시도해 주세요.");
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingDetail(false);
    });
    return () => controller.abort();
  }, [applyAuthority, denyPrivilegedView, detailRequestVersion, selectedId]);

  const dirtyTechnologyKeys = useMemo(() => {
    if (!detail || detail.role === "owner") return [];
    return detail.technologies
      .filter((technology) =>
        !sameCapabilities(technology.capabilities, draft[technology.key] ?? []))
      .map((technology) => technology.key);
  }, [detail, draft]);

  function selectUser(userId: string) {
    if (userId === selectedId || submitting) return;
    selectedIdRef.current = userId;
    setLoadingDetail(true);
    setSelectedId(userId);
    setDetail(null);
    setDraft({});
    setAuditItems([]);
    setConfirmation(null);
    setPrerequisiteError(null);
    setError(null);
    setNotice(null);
  }

  function retrySelectedUser() {
    if (!selectedId) return;
    setLoadingDetail(true);
    setDetail(null);
    setDraft({});
    setAuditItems([]);
    setError(null);
    setNotice(null);
    setPrerequisiteError(null);
    setConfirmation(null);
    setDetailRequestVersion((version) => version + 1);
  }

  function toggleCapability(
    technologyKey: string,
    capability: Capability,
    checked: boolean,
  ) {
    if (!detail || detail.role === "owner" || submitting) return;
    const current = new Set(draft[technologyKey] ?? []);
    if (!checked && capability === "view"
      && (current.has("configure") || current.has("execute"))) {
      setPrerequisiteError(
        "설정 또는 실행 권한에는 조회 권한이 필요합니다. 먼저 의존 권한을 해제해 주세요.",
      );
      return;
    }
    if (checked) {
      current.add(capability);
      if (capability === "configure" || capability === "execute") current.add("view");
    } else {
      current.delete(capability);
    }
    setPrerequisiteError(null);
    setNotice(null);
    setDraft((value) => ({ ...value, [technologyKey]: ordered([...current]) }));
  }

  async function refreshAuthority(userId: string): Promise<void> {
    const [authority, auditPage] = await Promise.all([
      getUserAuthority(userId),
      listAuthorityAudit(userId),
    ]);
    applyAuthority(authority, auditPage.items, auditPage.next_cursor);
  }

  async function handleMutationFailure(failure: unknown, userId: string) {
    setNotice(null);
    if (failure instanceof ApiError && failure.status === 403) {
      denyPrivilegedView();
      return;
    }
    if (failure instanceof ApiError && failure.status === 409) {
      try {
        await refreshAuthority(userId);
        setError("다른 변경이 먼저 저장되었습니다. 최신 권한을 다시 불러왔으니 검토 후 저장해 주세요.");
      } catch (refreshFailure) {
        if (refreshFailure instanceof ApiError && refreshFailure.status === 403) {
          denyPrivilegedView();
        } else {
          requireFreshAuthority(
            "권한이 충돌했고 최신 권한을 다시 불러오지 못했습니다. 선택한 사용자를 명시적으로 다시 불러와야 편집할 수 있습니다.",
          );
        }
      }
      return;
    }
    setError("변경을 저장하지 못했습니다. 현재 상태를 확인한 뒤 다시 시도해 주세요.");
  }

  async function confirmMutation() {
    if (!detail || !confirmation || submitPending.current) return;
    const targetId = detail.id;
    const action = confirmation;
    submitPending.current = true;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      if (action.kind === "grants") {
        let revision = detail.revision;
        for (const technologyKey of dirtyTechnologyKeys) {
          const updated = await updateTechnologyGrant(
            targetId,
            technologyKey,
            revision,
            ordered(draft[technologyKey] ?? []),
          );
          revision = updated.revision;
        }
      } else if (action.kind === "status") {
        await updateUserStatus(targetId, detail.revision, action.nextActive);
      } else {
        await updateUserRole(targetId, detail.revision, action.nextRole);
      }
      try {
        await refreshAuthority(targetId);
      } catch (refreshFailure) {
        if (refreshFailure instanceof ApiError && refreshFailure.status === 403) {
          denyPrivilegedView();
        } else {
          requireFreshAuthority(
            "변경은 제출되었지만 최신 상태를 확인하지 못했습니다. 성공으로 판단하지 않으며, 선택한 사용자를 명시적으로 다시 불러와야 편집할 수 있습니다.",
          );
        }
        return;
      }
      setConfirmation(null);
      setNotice("저장했습니다. 서버의 최신 권한과 변경 이력을 다시 확인했습니다.");
    } catch (failure) {
      setConfirmation(null);
      await handleMutationFailure(failure, targetId);
    } finally {
      submitPending.current = false;
      setSubmitting(false);
    }
  }

  async function loadMoreUsers() {
    if (!usersCursor || loadingMoreUsers) return;
    setLoadingMoreUsers(true);
    setError(null);
    try {
      const page = await listAuthorityUsers(usersCursor);
      setUsers((current) => {
        const known = new Set(current.map((user) => user.id));
        return [...current, ...page.items.filter((user) => !known.has(user.id))];
      });
      setUsersCursor(page.next_cursor);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 403) denyPrivilegedView();
      else setError("사용자 목록의 다음 페이지를 불러오지 못했습니다.");
    } finally {
      setLoadingMoreUsers(false);
    }
  }

  async function loadMoreAudit() {
    if (!detail || !auditCursor || loadingMoreAudit) return;
    const targetId = detail.id;
    setLoadingMoreAudit(true);
    setError(null);
    try {
      const page = await listAuthorityAudit(targetId, auditCursor);
      if (selectedIdRef.current !== targetId) return;
      setAuditItems((current) => [...current, ...page.items]);
      setAuditCursor(page.next_cursor);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 403) denyPrivilegedView();
      else setError("이전 변경 이력을 불러오지 못했습니다.");
    } finally {
      setLoadingMoreAudit(false);
    }
  }

  const selectedRoleChange: UserRole | null = detail
    ? detail.role === "owner" ? "member" : "owner"
    : null;
  const unsafeLastMaster = Boolean(detail?.is_last_active_master);

  return (
    <div className={styles.root}>
    <main className={styles.shell} inert={confirmation ? true : undefined}>
      <header className={styles.hero}>
        <p className={styles.eyebrow}>시스템 · 접근 제어</p>
        <h1>권한 관리</h1>
        <p>
          기존 사용자의 계정 상태, 마스터 역할, 기술별 관리 권한을 분리해 관리합니다.
          현재 관리자: {currentUser.display_name} · 마스터
        </p>
        <p className={styles.boundary}>
          이 화면의 기술 권한은 관리 기능을 위한 배정입니다. 문서·공간·외부 전송 승인을
          우회하지 않으며, 일반 RAG 검색 이용 권한과도 다릅니다.
        </p>
      </header>

      {error ? (
        <div className={styles.alert} role="alert">
          <p>{error}</p>
          {forbidden ? (
            <Link href={routes.workshopHome}>작업소로 이동</Link>
          ) : users.length === 0 ? (
            <button type="button" onClick={startDirectoryLoad}>다시 시도</button>
          ) : detail === null && selectedId ? (
            <button type="button" onClick={retrySelectedUser}>선택 다시 불러오기</button>
          ) : null}
        </div>
      ) : null}
      {notice ? <p className={styles.notice} role="status">{notice}</p> : null}

      {!forbidden ? (
        <div className={styles.layout}>
          <AccessDirectory
            users={users}
            selectedId={selectedId}
            loading={loadingDirectory}
            loadingMore={loadingMoreUsers}
            hasError={error !== null}
            hasMore={usersCursor !== null}
            submitting={submitting}
            onSelect={selectUser}
            onLoadMore={() => void loadMoreUsers()}
          />
          <AccessAuthorityDetail
            detail={detail}
            draft={draft}
            catalog={catalog}
            auditItems={auditItems}
            auditCursor={auditCursor}
            loading={loadingDetail}
            loadingMoreAudit={loadingMoreAudit}
            submitting={submitting}
            dirtyTechnologyKeys={dirtyTechnologyKeys}
            prerequisiteError={prerequisiteError}
            selectedRoleChange={selectedRoleChange}
            unsafeLastMaster={unsafeLastMaster}
            onToggleCapability={toggleCapability}
            onConfirmStatus={(nextActive) => setConfirmation({ kind: "status", nextActive })}
            onConfirmRole={(nextRole) => setConfirmation({ kind: "role", nextRole })}
            onConfirmGrants={() => setConfirmation({ kind: "grants" })}
            onCancelGrants={() => {
              if (!detail) return;
              setDraft(draftFrom(detail));
              setPrerequisiteError(null);
            }}
            onLoadMoreAudit={() => void loadMoreAudit()}
          />
        </div>
      ) : null}

    </main>
      <AccessConfirmationDialog
        confirmation={confirmation}
        detail={detail}
        draft={draft}
        dirtyTechnologyKeys={dirtyTechnologyKeys}
        submitting={submitting}
        onConfirm={() => void confirmMutation()}
        onCancel={() => setConfirmation(null)}
      />
    </div>
  );
}
