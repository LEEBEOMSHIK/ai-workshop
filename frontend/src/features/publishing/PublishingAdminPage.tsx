"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../shared/api/client";
import { useUnsavedChanges } from "../learning/useUnsavedChanges";
import { publishingAdminApi, type PublishingAdminApi } from "./api";
import { StudyBody } from "./StudyBody";
import type {
  PublicationRequest,
  PublicPersona,
  StudyAdminView,
  StudyContent,
  StudyPreview,
} from "./types";
import styles from "./Publishing.module.css";

const pageSize = 20;
const emptyContent: StudyContent = {
  slug: "",
  title: "",
  summary: "",
  topic_keys: [],
  body: "",
  verification: "",
  limitations: "",
  persona: null,
};

type StatusFilter = "all" | "private" | "public" | "pending";
type CommandAction = "publish" | "withdraw";
interface RetryCommand {
  action: CommandAction;
  slug: string;
  request: PublicationRequest;
}

export function PublishingAdminPage({ api = publishingAdminApi }: { api?: PublishingAdminApi }) {
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<StudyAdminView[]>([]);
  const [personas, setPersonas] = useState<PublicPersona[]>([]);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [selected, setSelected] = useState<StudyAdminView | null>(null);
  const [creating, setCreating] = useState(false);
  const [content, setContent] = useState<StudyContent>(emptyContent);
  const [baseline, setBaseline] = useState("");
  const [preview, setPreview] = useState<StudyPreview | null>(null);
  const [previewInvalidated, setPreviewInvalidated] = useState(false);
  const [retryCommand, setRetryCommand] = useState<RetryCommand | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const contextVersion = useRef(0);
  const busyOperation = useRef(0);
  const dirty = (creating || selected !== null) && JSON.stringify(content) !== baseline;
  useUnsavedChanges(dirty);

  function beginBusy(): number {
    const operation = ++busyOperation.current;
    setBusy(true);
    return operation;
  }

  function finishBusy(operation: number) {
    if (busyOperation.current === operation) setBusy(false);
  }

  function resetBusy() {
    busyOperation.current += 1;
    setBusy(false);
  }

  const loadPage = useCallback(async (nextPage: number) => {
    const version = ++contextVersion.current;
    setLoading(true);
    setError(null);
    try {
      const response = await api.list(nextPage * pageSize, pageSize);
      if (contextVersion.current !== version) return;
      setPage(nextPage);
      setItems(response.items);
      setSelected(null);
      setCreating(false);
      setContent(emptyContent);
      setBaseline("");
      setPreview(null);
      setRetryCommand(null);
    } catch {
      if (contextVersion.current === version) setError("공개 연구 관리 목록을 불러오지 못했습니다.");
    } finally {
      if (contextVersion.current === version) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void Promise.resolve().then(() => loadPage(0));
    void api.personas().then((response) => setPersonas(response.items)).catch(() => {
      setError("승인된 공개 안내자 목록을 불러오지 못했습니다.");
    });
  }, [api, loadPage]);

  function canReplaceEditor(): boolean {
    if (retryCommand) return false;
    return !dirty || window.confirm("저장하지 않은 변경이 있습니다. 이 편집 내용을 버릴까요?");
  }

  function changePage(nextPage: number) {
    if (!canReplaceEditor()) return;
    void loadPage(nextPage);
  }

  function selectStudy(study: StudyAdminView) {
    if (!canReplaceEditor()) return;
    contextVersion.current += 1;
    resetBusy();
    setSelected(study);
    setCreating(false);
    setContent(study.snapshot.content);
    setBaseline(JSON.stringify(study.snapshot.content));
    setPreview(null);
    setPreviewInvalidated(false);
    setRetryCommand(retryFromStudy(study));
    setMessage(null);
    setError(null);
  }

  function beginCreate() {
    if (!canReplaceEditor()) return;
    contextVersion.current += 1;
    resetBusy();
    setSelected(null);
    setCreating(true);
    setContent(emptyContent);
    setBaseline(JSON.stringify(emptyContent));
    setPreview(null);
    setPreviewInvalidated(false);
    setRetryCommand(null);
    setMessage(null);
    setError(null);
  }

  function changeContent(next: StudyContent) {
    if (preview) {
      setPreview(null);
      setPreviewInvalidated(true);
    }
    setContent(next);
  }

  async function save() {
    if (!validContent(content)) {
      setError("모든 필수 항목과 하나 이상의 기술 주제 키를 입력해 주세요.");
      return;
    }
    const operation = beginBusy();
    setError(null);
    const version = contextVersion.current;
    try {
      const saved = creating
        ? await api.create(content)
        : await api.update(content.slug, selected!.snapshot.revision, content);
      if (contextVersion.current !== version) return;
      setSelected(saved);
      setCreating(false);
      setContent(saved.snapshot.content);
      setBaseline(JSON.stringify(saved.snapshot.content));
      setItems((current) => upsertStudy(current, saved));
      setRetryCommand(retryFromStudy(saved));
      setPreview(null);
      setPreviewInvalidated(false);
      setMessage(creating ? "비공개 초안으로 만들었습니다." : "변경을 저장했습니다. 기존 공개본은 다시 공개하기 전까지 유지됩니다.");
    } catch (caught) {
      if (contextVersion.current === version) handleMutationError(caught);
    } finally {
      finishBusy(operation);
    }
  }

  async function requestPreview() {
    if (!selected || dirty) return;
    const version = contextVersion.current;
    const slug = selected.snapshot.content.slug;
    const operation = beginBusy();
    setError(null);
    try {
      const response = await api.preview(slug);
      if (contextVersion.current !== version) return;
      setPreview(response);
      setPreviewInvalidated(false);
      setMessage(null);
    } catch {
      if (contextVersion.current === version) setError("서버 미리보기를 불러오지 못했습니다.");
    } finally {
      finishBusy(operation);
    }
  }

  async function startCommand(action: CommandAction) {
    if (!selected || dirty) return;
    const source = action === "publish" ? preview : { snapshot: selected.snapshot, digest: selected.digest };
    if (!source) return;
    const command: RetryCommand = {
      action,
      slug: selected.snapshot.content.slug,
      request: {
        expected_revision: source.snapshot.revision,
        expected_digest: source.digest,
        request_id: createRequestId(),
      },
    };
    setRetryCommand(command);
    await runCommand(command);
  }

  async function runCommand(command: RetryCommand) {
    const operation = beginBusy();
    setError(null);
    const version = contextVersion.current;
    try {
      const response = await api[command.action](command.slug, command.request);
      if (contextVersion.current !== version) return;
      setSelected(response);
      setContent(response.snapshot.content);
      setBaseline(JSON.stringify(response.snapshot.content));
      setItems((current) => upsertStudy(current, response));
      if (response.delivery_pending) {
        setRetryCommand(retryFromStudy(response) ?? command);
        setMessage("적용 대기: 공개 저장소 적용이 아직 확인되지 않았습니다.");
      } else {
        setRetryCommand(null);
        setPreview(
          preview &&
          preview.snapshot.revision === response.snapshot.revision &&
          preview.digest === response.digest
            ? preview
            : null,
        );
        setMessage(commandResultMessage(response));
      }
    } catch (caught) {
      if (contextVersion.current !== version) return;
      if (caught instanceof ApiError && caught.status === 409) {
        setError("다른 변경이 먼저 저장되었습니다. 편집 내용은 보존했습니다. 서버 버전을 다시 불러온 뒤 비교해 주세요.");
      } else {
        setError("요청 결과를 확인하지 못했습니다. 같은 요청을 다시 시도할 수 있습니다.");
      }
    } finally {
      finishBusy(operation);
    }
  }

  async function reloadSelected() {
    if (!selected || (dirty && !window.confirm("편집 내용을 버리고 서버 버전을 다시 불러올까요?"))) return;
    const version = ++contextVersion.current;
    const operation = beginBusy();
    try {
      const response = await api.detail(selected.snapshot.content.slug);
      if (contextVersion.current !== version) return;
      setSelected(response);
      setContent(response.snapshot.content);
      setBaseline(JSON.stringify(response.snapshot.content));
      setPreview(null);
      setPreviewInvalidated(false);
      setRetryCommand(retryFromStudy(response));
      setError(null);
    } catch {
      if (contextVersion.current === version) setError("서버 버전을 다시 불러오지 못했습니다.");
    } finally {
      finishBusy(operation);
    }
  }

  function handleMutationError(caught: unknown) {
    if (caught instanceof ApiError && caught.status === 409) {
      setError("다른 변경이 먼저 저장되었습니다. 편집 내용은 보존했습니다. 서버 버전을 다시 불러온 뒤 비교해 주세요.");
    } else {
      setError("변경을 저장하지 못했습니다. 입력 내용은 보존했습니다.");
    }
  }

  const filteredItems = useMemo(
    () => items.filter((item) => filter === "all" || studyStatus(item) === filter),
    [filter, items],
  );

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <p>ADMIN · PUBLISHING</p>
        <h1>공개 연구 관리</h1>
        <p>비공개 편집본을 저장하고, 서버 미리보기의 정확한 리비전을 확인한 뒤 공개합니다.</p>
        <p>공개 전 비공개 원문, 자격 증명, 개인정보를 직접 확인해 제외하세요. 이 절차는 자동 비식별화나 자동 삭제가 아닙니다.</p>
      </header>
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      <div className={styles.workspace}>
        <aside className={styles.panel} aria-label="공개 연구 목록">
          <div className={styles.controls}>
            <button type="button" disabled={busy || retryCommand !== null} onClick={beginCreate}>새 기록</button>
            <label>상태 필터
              <select value={filter} onChange={(event) => setFilter(event.target.value as StatusFilter)}>
                <option value="all">전체</option>
                <option value="private">비공개</option>
                <option value="public">공개</option>
                <option value="pending">적용 대기</option>
              </select>
            </label>
          </div>
          <p className={styles.help}>현재 페이지 기준으로 상태를 필터링합니다.</p>
          {loading ? <p role="status">목록을 불러오는 중입니다.</p> : null}
          <ul className={styles.list}>
            {filteredItems.map((item) => (
              <li key={item.snapshot.content.slug}>
                <button type="button" disabled={retryCommand !== null} onClick={() => selectStudy(item)}>
                  {item.snapshot.content.title} 편집 · 리비전 {item.snapshot.revision} · {statusLabel(item)}
                </button>
              </li>
            ))}
          </ul>
          {!loading && filteredItems.length === 0 ? <p>이 페이지에 해당하는 기록이 없습니다.</p> : null}
          <div className={styles.pager}>
            <button type="button" aria-label="이전 페이지" disabled={page === 0 || busy || retryCommand !== null} onClick={() => changePage(page - 1)}>이전</button>
            <span>{page + 1}페이지 · 페이지당 20개</span>
            <button type="button" aria-label="다음 페이지" disabled={items.length < pageSize || busy || retryCommand !== null} onClick={() => changePage(page + 1)}>다음</button>
          </div>
        </aside>

        <section className={styles.panel} aria-label="공개 연구 편집기">
          {!creating && !selected ? <p>편집할 기록을 선택하거나 새 기록을 만드세요.</p> : (
            <>
              <StudyForm
                content={content}
                creating={creating}
                disabled={busy}
                personas={personas}
                onChange={changeContent}
              />
              <div className={styles.actions}>
                <button type="button" disabled={busy || !dirty} onClick={() => void save()}>
                  {creating ? "비공개 기록 만들기" : "변경 저장"}
                </button>
                {selected ? <button type="button" disabled={busy || dirty} onClick={() => void requestPreview()}>서버 미리보기</button> : null}
                {preview && !dirty && !retryCommand ? <button type="button" disabled={busy} onClick={() => void startCommand("publish")}>미리보기와 같은 버전 공개</button> : null}
                {selected && !dirty && !retryCommand && selected.applied_action === "publish" ? <button type="button" disabled={busy} onClick={() => void startCommand("withdraw")}>비공개로 전환</button> : null}
                {selected ? <button type="button" disabled={busy} onClick={() => void reloadSelected()}>서버 버전 다시 불러오기</button> : null}
              </div>
              {previewInvalidated ? <p className={styles.help}>편집 후 미리보기가 무효화되었습니다.</p> : null}
              {message ? <p className={styles.status} role="status">{message}</p> : null}
              {retryCommand ? (
                <>
                  <button type="button" disabled={busy || dirty} onClick={() => void runCommand(retryCommand)}>
                    같은 {retryCommand.action === "publish" ? "공개" : "철회"} 요청 다시 시도
                  </button>
                  {dirty ? <p className={styles.help}>정확한 요청을 다시 시도하려면 편집 내용을 먼저 저장하거나 되돌려야 합니다.</p> : null}
                </>
              ) : null}
              {selected ? <PublicationState study={selected} /> : null}
              {preview ? (
                <section className={styles.preview} aria-label="서버 미리보기">
                  <h2>미리보기 리비전 {preview.snapshot.revision}</h2>
                  <StudyBody snapshot={preview.snapshot} />
                </section>
              ) : null}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function StudyForm({ content, creating, disabled, personas, onChange }: {
  content: StudyContent;
  creating: boolean;
  disabled: boolean;
  personas: PublicPersona[];
  onChange: (content: StudyContent) => void;
}) {
  const personaValue = content.persona ? `${content.persona.slug}\u001f${content.persona.label}` : "";
  return (
    <form className={styles.form} onSubmit={(event) => event.preventDefault()}>
      <label>공개 주소 슬러그<input disabled={disabled || !creating} value={content.slug} onChange={(event) => onChange({ ...content, slug: event.target.value })} /></label>
      <label>제목<input disabled={disabled} value={content.title} onChange={(event) => onChange({ ...content, title: event.target.value })} /></label>
      <label>요약<textarea disabled={disabled} value={content.summary} onChange={(event) => onChange({ ...content, summary: event.target.value })} /></label>
      <label>기술 주제 키<input disabled={disabled} value={content.topic_keys.join(", ")} onChange={(event) => onChange({ ...content, topic_keys: commaList(event.target.value) })} /></label>
      <label>본문<textarea name="body" disabled={disabled} value={content.body} onChange={(event) => onChange({ ...content, body: event.target.value })} /></label>
      <label>검증 기록<textarea disabled={disabled} value={content.verification} onChange={(event) => onChange({ ...content, verification: event.target.value })} /></label>
      <label>남은 한계<textarea disabled={disabled} value={content.limitations} onChange={(event) => onChange({ ...content, limitations: event.target.value })} /></label>
      <label>승인된 공개 안내자
        <select disabled={disabled} value={personaValue} onChange={(event) => onChange({ ...content, persona: personas.find((persona) => `${persona.slug}\u001f${persona.label}` === event.target.value) ?? null })}>
          <option value="">지정하지 않음</option>
          {personas.map((persona) => <option key={persona.slug} value={`${persona.slug}\u001f${persona.label}`}>{persona.label}</option>)}
        </select>
      </label>
    </form>
  );
}

function PublicationState({ study }: { study: StudyAdminView }) {
  return (
    <section aria-label="공개 적용 상태">
      <h2>현재 상태</h2>
      <p>편집본 리비전 {study.snapshot.revision}</p>
      {study.applied_action === "publish" ? <p>공개본 리비전 {study.applied_revision}</p> : <p>적용된 공개본 없음</p>}
      {study.delivery_pending ? <p>적용 대기</p> : null}
      {study.pending_command ? <p>{study.pending_command.action === "publish" ? "공개" : "철회"} 요청 리비전 {study.pending_command.expected_revision}</p> : null}
    </section>
  );
}

function validContent(content: StudyContent): boolean {
  return [content.slug, content.title, content.summary, content.body, content.verification, content.limitations]
    .every((value) => value.trim().length > 0) && content.topic_keys.length > 0;
}

function commaList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function studyStatus(study: StudyAdminView): Exclude<StatusFilter, "all"> {
  if (study.delivery_pending) return "pending";
  return study.applied_action === "publish" ? "public" : "private";
}

function statusLabel(study: StudyAdminView): string {
  if (study.delivery_pending) return "적용 대기";
  return study.applied_action === "publish" ? "공개" : "비공개";
}

function upsertStudy(items: StudyAdminView[], study: StudyAdminView): StudyAdminView[] {
  const without = items.filter((item) => item.snapshot.content.slug !== study.snapshot.content.slug);
  return [...without, study].sort((left, right) => left.snapshot.content.slug.localeCompare(right.snapshot.content.slug));
}

function createRequestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `publishing-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function retryFromStudy(study: StudyAdminView): RetryCommand | null {
  const pending = study.pending_command;
  if (!pending) return null;
  return {
    action: pending.action,
    slug: study.snapshot.content.slug,
    request: {
      expected_revision: pending.expected_revision,
      expected_digest: pending.expected_digest,
      request_id: pending.request_id,
    },
  };
}

function commandResultMessage(study: StudyAdminView): string {
  if (study.applied_action === "publish") {
    return `공개본 리비전 ${study.applied_revision ?? study.snapshot.revision}이 적용되었습니다.`;
  }
  return "비공개 전환이 적용되었습니다. 비공개 초안은 유지됩니다.";
}
