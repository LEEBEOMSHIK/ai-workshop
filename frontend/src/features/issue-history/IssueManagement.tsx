"use client";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, apiRequest } from "../../shared/api/client";
import { issueApi, mutationRequest, saveIssueHistory } from "./api";
import type { Category, DocumentVersion, IssueDetail, IssueDocument } from "./types";
import styles from "./IssueHistoryPage.module.css";
const labels = { open: "진행 중", implemented: "구현됨 · 검증 남음", verified: "검증 완료" };
const value = (data: FormData, name: string) => String(data.get(name) ?? "");
const lines = (data: FormData, name: string) => value(data, name).split("\n").map(s => s.trim()).filter(Boolean);
function Field({ name, label, initial = "", large = false, required = false, type = "text", max = 20000 }: {
    name: string;
    label: string;
    initial?: string;
    large?: boolean;
    required?: boolean;
    type?: string;
    max?: number;
}) { return <label>{label}{large ? <textarea name={name} defaultValue={initial} required={required} maxLength={max} rows={5}/> : <input name={name} type={type} defaultValue={initial} required={required} maxLength={max}/>}</label>; }
function SaveForm({ title, path, method = "POST", payload, onSaved, children }: {
    title: string;
    path: string;
    method?: "POST" | "PUT";
    payload: (data: FormData) => Record<string, unknown>;
    onSaved: () => void;
    children: ReactNode;
}) {
    const retry = useRef(mutationRequest());
    const revision = payload(new FormData()).expected_revision;
    const expectedRevision = useRef(revision);
    const savedRevision = useRef(false);
    useEffect(() => { if (savedRevision.current && revision !== expectedRevision.current) {
        expectedRevision.current = revision;
        savedRevision.current = false;
    } }, [revision]);
    const [pending, setPending] = useState(false);
    const [message, setMessage] = useState("");
    const [failed, setFailed] = useState(false);
    async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = event.currentTarget; setPending(true); setMessage(""); try {
        const result = await saveIssueHistory<{version?: number}>(path, method, retry.current({ ...payload(new FormData(form)), ...(expectedRevision.current !== undefined ? { expected_revision: expectedRevision.current } : {}) }));
        savedRevision.current = true;
        setFailed(false);
        setMessage(result?.version ? `저장했습니다. 반환된 문서 버전은 ${result.version}입니다. 이 버전을 선택해 문제에 연결하세요.` : "저장했습니다.");
        onSaved();
    }
    catch (error) {
        setFailed(true);
        setMessage(error instanceof ApiError && error.status === 409 ? "다른 변경과 충돌했습니다. 입력은 유지됩니다. 최신 내용을 새로고침한 뒤 비교해 주세요." : error instanceof Error ? error.message : "저장하지 못했습니다. 다시 시도해 주세요.");
    }
    finally {
        setPending(false);
    } }
    return <details className={styles.editor}><summary>{title}</summary><form onSubmit={submit}><fieldset disabled={pending}>{children}<button type="submit">{pending ? "저장 중…" : "저장"}</button></fieldset>{message && <p role={failed ? "alert" : "status"}>{message}</p>}{failed && <button type="button" onClick={() => window.location.reload()}>최신 내용 다시 열기 (입력 초기화)</button>}</form></details>;
}
export function IssueManagement({ categories, issue, onSaved }: {
    categories: Category[];
    issue: IssueDetail | null;
    onSaved: () => void;
}) {
    const [categoryId, setCategoryId] = useState("");
    const category = categories.find(c => c.id === categoryId);
    const [documents, setDocuments] = useState<IssueDocument[]>([]);
    const [documentId, setDocumentId] = useState("");
    const document = documents.find(d => d.id === documentId);
    const [error, setError] = useState("");
    const [generation, setGeneration] = useState(0);
    const [preview, setPreview] = useState<DocumentVersion | null>(null);
    useEffect(() => { let active = true; apiRequest<{
        items: IssueDocument[];
    }>(`${issueApi}/documents`).then(data => { if (active) {
        setDocuments(data.items);
        setError("");
    } }).catch(() => { if (active)
        setError("문서 목록을 불러오지 못했습니다."); }); return () => { active = false; }; }, [generation]);
    const saved = () => { setGeneration(n => n + 1); onSaved(); };
    const categoryOptions = (current?: string) => categories.filter(c => c.is_active || c.id === current).map(c => <option key={c.id} value={c.id}>{c.name}{!c.is_active ? " (비활성)" : ""}</option>);
    function issueFields(current: IssueDetail | null) { return <>{!current && <Field name="issue_key" label="문제 번호" required max={80}/>}<Field name="title" label="문제 제목" initial={current?.title} required max={200}/><label>분류<select name="category_id" defaultValue={current?.category_id} required>{categoryOptions(current?.category_id)}</select></label><label>상태<select name="status" defaultValue={current?.status ?? "open"}>{Object.entries(labels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>{([['symptom', '증상'], ['cause', '원인'], ['resolution', '수정 내용']] as const).map(([key, label]) => <Field key={key} name={key} label={label} initial={current?.[key]} large/>)}{([['verification', '검증 기록'], ['remaining', '남은 작업'], ['commits', '커밋']] as const).map(([key, label]) => <Field key={key} name={key} label={`${label} (한 줄에 하나)`} initial={current?.[key]?.join("\n")} large/>)}</>; }
    const issuePayload = (data: FormData) => ({ title: value(data, "title"), category_id: value(data, "category_id"), status: value(data, "status"), symptom: value(data, "symptom"), cause: value(data, "cause"), resolution: value(data, "resolution"), verification: lines(data, "verification"), remaining: lines(data, "remaining"), commits: lines(data, "commits") });
    return <section className={styles.management} aria-label="이력 관리">
 <h2>이력 관리</h2><p>변경 사항과 진행 기록은 DB에 보존됩니다. 문서의 새 버전은 기존 문제 연결을 바꾸지 않습니다.</p>
 <SaveForm title="문제 등록" path="issues" payload={data => ({ ...issuePayload(data), issue_key: value(data, "issue_key") })} onSaved={saved}>{issueFields(null)}</SaveForm>
 {issue && <><SaveForm key={`edit-${issue.id}`} title="선택한 문제 편집" path={`issues/${issue.id}`} method="PUT" payload={data => ({ ...issuePayload(data), expected_revision: issue.revision })} onSaved={saved}>{issueFields(issue)}</SaveForm>
 <SaveForm key={`event-${issue.id}`} title="진행 이력 추가" path={`issues/${issue.id}/events`} payload={data => ({ expected_revision: issue.revision, event_date: value(data, "event_date"), description: value(data, "description") })} onSaved={saved}><Field name="event_date" label="진행 날짜" type="date" required/><Field name="description" label="진행 내용" large required/></SaveForm></>}
 <details className={styles.editor}><summary>카테고리 관리</summary><label>편집할 카테고리<select value={categoryId} onChange={e => setCategoryId(e.target.value)}><option value="">새 카테고리</option>{categories.map(c => <option value={c.id} key={c.id}>{c.name}{!c.is_active ? " (비활성)" : ""}</option>)}</select></label>
 <SaveForm key={categoryId} title={category ? "카테고리 편집" : "카테고리 등록"} path={category ? `categories/${category.id}` : "categories"} method={category ? "PUT" : "POST"} payload={data => ({ ...(category ? { expected_revision: category.revision } : { code: value(data, "code") }), name: value(data, "name"), sort_order: Number(value(data, "sort_order")), is_active: data.has("is_active") })} onSaved={saved}>{!category && <Field name="code" label="고유 코드" required max={80}/>}<Field name="name" label="카테고리 이름" initial={category?.name} required max={200}/><Field name="sort_order" label="정렬 순서" type="number" initial={String(category?.sort_order ?? 0)}/><label><input type="checkbox" name="is_active" defaultChecked={category?.is_active ?? true}/>사용</label></SaveForm></details>
 <details className={styles.editor}><summary>문서 관리·연결</summary>{error && <p role="alert">{error}<button onClick={() => setGeneration(n => n + 1)}>다시 불러오기</button></p>}
 <SaveForm title="문서 등록" path="documents" payload={data => ({ title: value(data, "title"), content: value(data, "content"), source_path: value(data, "source_path") || null })} onSaved={saved}><Field name="title" label="문서 제목" required max={200}/><Field name="content" label="Markdown 본문" large required max={524288}/><Field name="source_path" label="출처 (선택)"/></SaveForm>
 <label>관리할 문서<select value={documentId} onChange={e => { setDocumentId(e.target.value); setPreview(null); }}><option value="">문서 선택</option>{documents.map(d => <option value={d.id} key={d.id}>{d.title} · 현재 버전 {d.current_version}</option>)}</select></label>
 {document && <><SaveForm key={`title-${document.id}`} title="문서 제목 편집" path={`documents/${document.id}`} method="PUT" payload={data => ({ expected_revision: document.revision, title: value(data, "title") })} onSaved={saved}><Field name="title" label="문서 제목" initial={document.title} required max={200}/></SaveForm>
 <SaveForm key={`version-${document.id}`} title="문서 새 버전 추가" path={`documents/${document.id}/versions`} payload={data => ({ expected_revision: document.revision, content: value(data, "content"), source_path: value(data, "source_path") || null })} onSaved={saved}><Field name="content" label="새 Markdown 본문" required large max={524288}/><Field name="source_path" label="출처 (선택)"/></SaveForm>
 <form onSubmit={async (e) => { e.preventDefault(); setError(""); const version = value(new FormData(e.currentTarget), "version"); try {
            setPreview(await apiRequest<DocumentVersion>(`${issueApi}/documents/${document.id}/versions/${encodeURIComponent(version)}`));
        }
        catch {
            setPreview(null);
            setError("해당 문서 버전을 읽지 못했습니다.");
        } }}><Field name="version" label="열어볼 버전" initial={String(document.current_version)} type="number" required/><button>버전 열기</button></form>
 {preview?.document_id === document.id && <details open><summary>{preview.title} · 버전 {preview.version}</summary><pre className={styles.documentBody}>{preview.content}</pre></details>}
 {issue && <SaveForm key={`link-${document.id}-${issue.id}`} title="선택한 문제에 문서 버전 연결" path={`issues/${issue.id}/links`} method="PUT" payload={data => ({ expected_revision: issue.revision, links: [...issue.documents.filter(d => d.document_id !== document.id || d.version !== Number(value(data, "version"))).map(d => ({ document_id: d.document_id, version: d.version })), { document_id: document.id, version: Number(value(data, "version")) }] })} onSaved={saved}><Field name="version" label="연결할 정확한 버전" type="number" initial={String(document.current_version)} required/></SaveForm>}</>}
 {issue && issue.documents.length > 0 && <SaveForm key={`unlink-${issue.id}`} title="문서 연결 해제" path={`issues/${issue.id}/links`} method="PUT" payload={data => ({ expected_revision: issue.revision, links: issue.documents.filter(d => data.getAll("keep").includes(`${d.document_id}:${d.version}`)).map(d => ({ document_id: d.document_id, version: d.version })) })} onSaved={saved}><p>유지할 연결만 선택하세요. 문서와 이전 진행 기록은 보존됩니다.</p>{issue.documents.map(d => <label key={`${d.document_id}:${d.version}`}><input type="checkbox" name="keep" value={`${d.document_id}:${d.version}`} defaultChecked/>{d.title} · 버전 {d.version}</label>)}</SaveForm>}
 </details></section>;
}
