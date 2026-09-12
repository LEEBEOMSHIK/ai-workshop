import type {
  AuthorityAudit,
  Capability,
  TechnologyCatalog,
  UserAuthority,
  UserRole,
} from "./api";
import { useEffect, useRef } from "react";
import styles from "./AccessManagement.module.css";

const capabilities: readonly Capability[] = ["view", "configure", "execute"];
const capabilityLabels: Record<Capability, string> = {
  view: "조회",
  configure: "설정",
  execute: "실행",
};
const eventLabels: Record<string, string> = {
  technology_grant_changed: "기술 권한 변경",
  user_status_changed: "계정 상태 변경",
  user_role_changed: "역할 변경",
  authorization_bootstrap: "권한 기반 초기화",
};

export type AccessDraft = Record<string, Capability[]>;
export type AccessConfirmation =
  | { kind: "grants" }
  | { kind: "status"; nextActive: boolean }
  | { kind: "role"; nextRole: UserRole };

function capabilityList(values: readonly Capability[]): string {
  const selected = new Set(values);
  const normalized = capabilities.filter((capability) => selected.has(capability));
  return normalized.length > 0
    ? normalized.map((capability) => capabilityLabels[capability]).join(", ")
    : "없음";
}

export function roleLabel(role: UserRole): string {
  return role === "owner" ? "마스터" : "일반 사용자";
}

function snapshotLine(
  snapshot: Record<string, unknown>,
  catalog: readonly TechnologyCatalog[],
): string {
  const values: string[] = [];
  if (snapshot.role === "owner" || snapshot.role === "member") {
    values.push(`역할 ${roleLabel(snapshot.role)}`);
  }
  if (typeof snapshot.is_active === "boolean") {
    values.push(`계정 ${snapshot.is_active ? "활성" : "비활성"}`);
  }
  if (typeof snapshot.revision === "number") values.push(`revision ${snapshot.revision}`);
  if (
    typeof snapshot.technologies === "object"
    && snapshot.technologies !== null
    && !Array.isArray(snapshot.technologies)
  ) {
    for (const [key, rawCapabilities] of Object.entries(snapshot.technologies)) {
      const label = catalog.find((technology) => technology.key === key)?.label ?? key;
      const known = Array.isArray(rawCapabilities)
        ? rawCapabilities.filter((value): value is Capability =>
          value === "view" || value === "configure" || value === "execute")
        : [];
      values.push(`${label}: ${capabilityList(known)}`);
    }
  }
  return values.join(" · ") || "기록된 권한 값 없음";
}

export function AccessDirectory({
  users,
  selectedId,
  loading,
  loadingMore,
  hasError,
  hasMore,
  submitting,
  onSelect,
  onLoadMore,
}: {
  users: UserAuthority[];
  selectedId: string | null;
  loading: boolean;
  loadingMore: boolean;
  hasError: boolean;
  hasMore: boolean;
  submitting: boolean;
  onSelect: (userId: string) => void;
  onLoadMore: () => void;
}) {
  return (
    <section className={styles.directory} aria-labelledby="access-users-title">
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.eyebrow}>기존 계정</p>
          <h2 id="access-users-title">사용자</h2>
        </div>
        <span>{users.length}명 표시</span>
      </div>
      {loading ? <p role="status">사용자 목록을 불러오는 중…</p> : null}
      {!loading && users.length === 0 && !hasError ? (
        <p className={styles.empty}>관리할 기존 사용자가 없습니다.</p>
      ) : null}
      <ul className={styles.userList}>
        {users.map((user) => (
          <li key={user.id}>
            <button
              type="button"
              className={selectedId === user.id ? styles.selectedUser : undefined}
              aria-pressed={selectedId === user.id}
              disabled={submitting}
              onClick={() => onSelect(user.id)}
            >
              <strong>{user.display_name}</strong>
              <span>{user.email}</span>
              <span>{roleLabel(user.role)} · {user.is_active ? "활성" : "비활성"}</span>
            </button>
          </li>
        ))}
      </ul>
      {hasMore ? (
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={loadingMore}
          onClick={onLoadMore}
        >
          {loadingMore ? "불러오는 중…" : "사용자 더 보기"}
        </button>
      ) : null}
    </section>
  );
}

function AuthorityAuditList({
  items,
  cursor,
  catalog,
  loadingMore,
  onLoadMore,
}: {
  items: AuthorityAudit[];
  cursor: number | null;
  catalog: TechnologyCatalog[];
  loadingMore: boolean;
  onLoadMore: () => void;
}) {
  return (
    <section className={styles.audit} aria-labelledby="authority-audit-title">
      <div className={styles.sectionHeading}>
        <div>
          <h3 id="authority-audit-title">변경 이력</h3>
          <p>감사 기록의 실제 저장 grant와 계정 상태를 표시합니다.</p>
        </div>
      </div>
      {items.length === 0 ? <p className={styles.empty}>기록된 변경이 없습니다.</p> : (
        <ol>
          {items.map((item) => (
            <li key={item.id}>
              <div>
                <strong>{eventLabels[item.event_type] ?? item.event_type}</strong>
                <time dateTime={item.created_at}>
                  {new Date(item.created_at).toLocaleString("ko-KR")}
                </time>
              </div>
              <p>변경 전 · {snapshotLine(item.before, catalog)}</p>
              <p>변경 후 · {snapshotLine(item.after, catalog)}</p>
            </li>
          ))}
        </ol>
      )}
      {cursor ? (
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={loadingMore}
          onClick={onLoadMore}
        >
          {loadingMore ? "불러오는 중…" : "이전 변경 더 보기"}
        </button>
      ) : null}
    </section>
  );
}

export function AccessAuthorityDetail({
  detail,
  draft,
  catalog,
  auditItems,
  auditCursor,
  loading,
  loadingMoreAudit,
  submitting,
  dirtyTechnologyKeys,
  prerequisiteError,
  selectedRoleChange,
  unsafeLastMaster,
  onToggleCapability,
  onConfirmStatus,
  onConfirmRole,
  onConfirmGrants,
  onCancelGrants,
  onLoadMoreAudit,
}: {
  detail: UserAuthority | null;
  draft: AccessDraft;
  catalog: TechnologyCatalog[];
  auditItems: AuthorityAudit[];
  auditCursor: number | null;
  loading: boolean;
  loadingMoreAudit: boolean;
  submitting: boolean;
  dirtyTechnologyKeys: string[];
  prerequisiteError: string | null;
  selectedRoleChange: UserRole | null;
  unsafeLastMaster: boolean;
  onToggleCapability: (technologyKey: string, capability: Capability, checked: boolean) => void;
  onConfirmStatus: (nextActive: boolean) => void;
  onConfirmRole: (nextRole: UserRole) => void;
  onConfirmGrants: () => void;
  onCancelGrants: () => void;
  onLoadMoreAudit: () => void;
}) {
  return (
    <section className={styles.detail} aria-live="polite">
      {loading ? <p role="status">선택한 사용자의 권한을 불러오는 중…</p> : null}
      {detail ? (
        <>
          <div className={styles.detailHeading}>
            <div>
              <p className={styles.eyebrow}>{roleLabel(detail.role)}</p>
              <h2 data-access-detail-focus-fallback tabIndex={-1}>{detail.display_name}</h2>
              <p>{detail.email} · revision {detail.revision}</p>
            </div>
            <span className={detail.is_active ? styles.active : styles.inactive}>
              {detail.is_active ? "활성 계정" : "비활성 계정"}
            </span>
          </div>

          {!detail.is_active ? (
            <aside className={styles.inactiveNote}>
              <strong>현재 접근 없음</strong>
              <p>
                비활성 계정은 현재 어떤 기술에도 접근할 수 없습니다. 아래 저장된 배정은
                재활성화 전에 검토하기 위한 값이며 현재 세션의 유효 권한이 아닙니다.
              </p>
            </aside>
          ) : null}

          <section className={styles.accountControls} aria-labelledby="account-controls-title">
            <div>
              <h3 id="account-controls-title">계정과 역할</h3>
              <p>기술 권한 저장과 별도의 확인 절차로 변경합니다.</p>
            </div>
            <div className={styles.buttonRow}>
              <button
                type="button"
                disabled={submitting || unsafeLastMaster}
                onClick={() => onConfirmStatus(!detail.is_active)}
              >
                {detail.is_active ? "계정 비활성화" : "계정 활성화"}
              </button>
              <button
                type="button"
                disabled={submitting || unsafeLastMaster || selectedRoleChange === null}
                onClick={() => selectedRoleChange && onConfirmRole(selectedRoleChange)}
              >
                {selectedRoleChange === "owner" ? "마스터로 변경" : "일반 사용자로 변경"}
              </button>
            </div>
            {unsafeLastMaster ? (
              <p className={styles.protection}>
                마지막 활성 마스터는 비활성화하거나 일반 사용자로 변경할 수 없습니다.
                서버도 동시 변경을 다시 검사합니다.
              </p>
            ) : null}
          </section>

          <section aria-labelledby="technology-grants-title">
            <div className={styles.sectionHeading}>
              <div>
                <h3 id="technology-grants-title">기술별 관리 권한</h3>
                <p>설정과 실행은 각각 조회 권한을 전제로 하며 서로를 포함하지 않습니다.</p>
              </div>
              {detail.role === "owner" ? <span className={styles.inherited}>마스터 상속</span> : null}
            </div>
            {prerequisiteError ? <p className={styles.inlineError} role="alert">{prerequisiteError}</p> : null}
            <div className={styles.technologyList}>
              {detail.technologies.map((technology) => {
                const selected = draft[technology.key] ?? [];
                const configured = detail.role === "owner"
                  ? technology.capabilities
                  : selected;
                return (
                  <fieldset key={technology.key} className={styles.technology}>
                    <legend>{technology.label} 권한</legend>
                    <div className={styles.technologyMeta}>
                      <span>{detail.role === "owner" ? "상속됨" : "저장됨"}</span>
                      <span>{technology.delegation_enabled ? "적용 가능" : "적용 준비 중"}</span>
                    </div>
                    <div className={styles.checkboxes}>
                      {capabilities.map((capability) => (
                        <label key={capability}>
                          <input
                            type="checkbox"
                            aria-label={capabilityLabels[capability]}
                            checked={configured.includes(capability)}
                            disabled={detail.role === "owner" || submitting}
                            onChange={(event) => onToggleCapability(
                              technology.key,
                              capability,
                              event.target.checked,
                            )}
                          />
                          {capabilityLabels[capability]}
                        </label>
                      ))}
                    </div>
                    {!technology.delegation_enabled ? (
                      <p className={styles.preparing}>
                        적용 준비 중 — 이 배정은 저장되지만 기존 RAG 관리 기능의 접근을
                        아직 허용하지 않습니다.
                      </p>
                    ) : null}
                  </fieldset>
                );
              })}
            </div>
            {detail.role === "owner" ? (
              <p className={styles.inheritedNote}>
                마스터 권한은 기술별 전체 관리 권한으로 상속되며 개별 grant로 편집하지 않습니다.
              </p>
            ) : (
              <div className={styles.buttonRow}>
                <button
                  type="button"
                  disabled={dirtyTechnologyKeys.length === 0 || submitting}
                  onClick={onConfirmGrants}
                >
                  권한 저장
                </button>
                <button
                  className={styles.secondaryButton}
                  type="button"
                  disabled={dirtyTechnologyKeys.length === 0 || submitting}
                  onClick={onCancelGrants}
                >
                  변경 취소
                </button>
              </div>
            )}
          </section>

          <AuthorityAuditList
            items={auditItems}
            cursor={auditCursor}
            catalog={catalog}
            loadingMore={loadingMoreAudit}
            onLoadMore={onLoadMoreAudit}
          />
        </>
      ) : null}
    </section>
  );
}

export function AccessConfirmationDialog({
  confirmation,
  detail,
  draft,
  dirtyTechnologyKeys,
  submitting,
  onConfirm,
  onCancel,
}: {
  confirmation: AccessConfirmation | null;
  detail: UserAuthority | null;
  draft: AccessDraft;
  dirtyTechnologyKeys: string[];
  submitting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!confirmation || !detail) return null;
  return (
    <OpenAccessConfirmationDialog
      confirmation={confirmation}
      detail={detail}
      draft={draft}
      dirtyTechnologyKeys={dirtyTechnologyKeys}
      submitting={submitting}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
}

function canRestoreFocus(element: HTMLElement | null): element is HTMLElement {
  return Boolean(
    element?.isConnected
    && !element.matches(":disabled, [aria-disabled='true']")
    && !element.closest("[inert]"),
  );
}

function restoreDialogFocus(opener: HTMLElement | null) {
  const detailFallback = document.querySelector<HTMLElement>(
    "[data-access-detail-focus-fallback]",
  );
  const target = canRestoreFocus(opener)
    ? opener
    : canRestoreFocus(detailFallback)
      ? detailFallback
      : null;
  target?.focus();
}

function OpenAccessConfirmationDialog({
  confirmation,
  detail,
  draft,
  dirtyTechnologyKeys,
  submitting,
  onConfirm,
  onCancel,
}: {
  confirmation: AccessConfirmation;
  detail: UserAuthority;
  draft: AccessDraft;
  dirtyTechnologyKeys: string[];
  submitting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const primaryActionRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    primaryActionRef.current?.focus();
    return () => restoreDialogFocus(opener);
  }, []);

  const label = confirmation.kind === "grants"
    ? "기술 권한 변경 확인"
    : confirmation.kind === "status"
      ? "계정 상태 변경 확인"
      : "역할 변경 확인";
  return (
    <div
      ref={dialogRef}
      className={styles.dialogBackdrop}
      role="dialog"
      aria-modal="true"
      aria-label={label}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          if (!submitting) {
            event.preventDefault();
            onCancel();
          }
          return;
        }
        if (event.key !== "Tab") return;
        const focusable = Array.from(
          dialogRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled)") ?? [],
        );
        if (focusable.length === 0) {
          event.preventDefault();
          return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
    >
      <section className={styles.dialog}>
        <h2>{label}</h2>
        <p>{detail.display_name} · expected revision {detail.revision}</p>
        {confirmation.kind === "grants" ? (
          <ul className={styles.changeList}>
            {detail.technologies
              .filter((technology) => dirtyTechnologyKeys.includes(technology.key))
              .map((technology) => (
                <li key={technology.key}>
                  <strong>{technology.label}</strong>
                  <span>변경 전: {capabilityList(technology.capabilities)}</span>
                  <span>변경 후: {capabilityList(draft[technology.key] ?? [])}</span>
                </li>
              ))}
          </ul>
        ) : confirmation.kind === "status" ? (
          <p>
            {confirmation.nextActive
              ? "계정을 활성화하면 저장된 기술 권한이 잠재적으로 다시 적용됩니다. 먼저 배정을 확인하세요."
              : "계정을 비활성화하면 저장된 배정은 남지만 모든 현재 접근이 즉시 거절됩니다."}
          </p>
        ) : (
          <p>
            {confirmation.nextRole === "owner"
              ? "마스터로 변경하면 개별 grant가 제거되고 전체 관리 권한을 상속합니다."
              : "일반 사용자로 변경하면 상속 권한이 사라지며 기술 권한 없음에서 시작합니다."}
          </p>
        )}
        <div className={styles.buttonRow}>
          <button
            ref={primaryActionRef}
            type="button"
            disabled={submitting}
            onClick={onConfirm}
          >
            {submitting ? "저장 중…" : confirmation.kind === "grants" ? "변경 저장" : "변경 확인"}
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            disabled={submitting}
            onClick={onCancel}
          >
            취소
          </button>
        </div>
      </section>
    </div>
  );
}
