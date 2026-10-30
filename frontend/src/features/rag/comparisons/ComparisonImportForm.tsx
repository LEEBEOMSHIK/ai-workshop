import Link from "next/link";
import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { ApiError } from "../../../shared/api/client";
import { comparisonPath } from "../../../shared/routing/routes";
import { Button } from "../../../shared/ui/Button";
import { importComparisonReport, type ComparisonDetail } from "./api";
import styles from "./Comparisons.module.css";

const MAX_IMPORT_BYTES = 2 * 1024 * 1024;
type ImportPreview = { payload: unknown; title: string; models: string[]; requestCount: number };
function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function preview(value: unknown): ImportPreview | null {
  if (!record(value) || value.schema_version !== 1 || typeof value.title !== "string" || !value.title.trim() || value.title.length > 180
    || !Array.isArray(value.requests) || value.requests.length < 2 || value.requests.length > 40) return null;
  const models: string[] = [];
  for (const request of value.requests) {
    if (!record(request) || typeof request.model !== "string" || !request.model.trim() || request.model.length > 180) return null;
    models.push(request.model);
  }
  return { payload: value, title: value.title, models: [...new Set(models)], requestCount: value.requests.length };
}

export function ComparisonImportForm({ onImported }: { onImported: (detail: ComparisonDetail) => void }) {
  const [selected, setSelected] = useState<ImportPreview | null>(null);
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedId, setSavedId] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const intent = useRef(0);
  const active = useRef(true);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => { active.current = true; return () => { active.current = false; pending.current?.abort(); }; }, []);
  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    const current = ++intent.current;
    setSelected(null); setSavedId(null); setError(""); setReading(false);
    if (!file) return;
    if (file.size > MAX_IMPORT_BYTES) { setError("2MiB 이하의 비교 결과 JSON 파일을 선택해 주세요."); return; }
    setReading(true);
    try {
      const text = await file.text();
      if (!active.current || current !== intent.current) return;
      if (new TextEncoder().encode(text).byteLength > MAX_IMPORT_BYTES) throw new Error("file_too_large");
      const parsed: unknown = JSON.parse(text);
      const value = preview(parsed);
      if (!value) throw new Error("invalid_preview");
      setSelected(value);
    } catch {
      if (active.current && current === intent.current) setError("비교 결과 JSON 형식을 확인해 주세요. 파일 내용을 표시하거나 저장하지 않았습니다.");
    } finally {
      if (active.current && current === intent.current) setReading(false);
    }
  }
  async function save() {
    if (!selected || pending.current) return;
    const controller = new AbortController(); pending.current = controller;
    setSaving(true); setError(""); setSavedId(null);
    try {
      const result = await importComparisonReport(selected.payload, controller.signal);
      if (!active.current || controller.signal.aborted) return;
      if (!result.id || result.record_kind !== "imported_comparison") throw new Error("invalid_import_result");
      setSavedId(result.id); setSelected(null);
      if (fileInput.current) fileInput.current.value = "";
      onImported(result);
    } catch (cause) {
      if (!active.current || controller.signal.aborted) return;
      setSelected(null);
      if (fileInput.current) fileInput.current.value = "";
      setError(cause instanceof ApiError && cause.status === 409
        ? "같은 수입 키에 다른 내용이 이미 저장되어 있습니다. 원본 파일을 확인해 주세요."
        : cause instanceof ApiError && [401, 403, 404].includes(cause.status)
          ? "저장 권한 또는 현재 원문 접근 권한을 확인해 주세요. 선택한 내용은 화면에서 제거했습니다."
          : "비교 결과를 저장하지 못했습니다. 파일 형식·수치·인용 관계와 연결 상태를 확인해 주세요.");
    } finally {
      if (pending.current === controller) pending.current = null;
      if (active.current && !controller.signal.aborted) setSaving(false);
    }
  }
  return <details className={styles.panel}>
    <summary>결과 파일 가져오기</summary>
    <form className={styles.importForm} onSubmit={event => { event.preventDefault(); void save(); }}>
      <p className={styles.muted}>완료된 비교 결과 JSON을 비공개 기록으로 저장합니다. 모델을 실행하지 않으며, 저장 시 원문 권한과 자료 관계를 확인합니다. 같은 내용의 재전송은 중복 기록을 만들지 않습니다.</p>
      <label>비교 결과 JSON 파일<input ref={fileInput} type="file" accept=".json,application/json" disabled={saving} onChange={event => { void selectFile(event); }} /></label>
      <p className={styles.muted}>파일당 최대 2MiB · 지원 형식 버전 1</p>
      {reading ? <p role="status">파일 형식을 확인하고 있습니다…</p> : null}
      {selected ? <div className={styles.preview} aria-label="저장 전 비교 파일 확인"><p>제목: {selected.title}</p><p>모델: {selected.models.join(" · ")}</p><p>완료 요청: {selected.requestCount}회</p></div> : null}
      {error ? <p role="alert">{error}</p> : null}
      {savedId ? <p role="status">비교 기록을 저장했습니다. <Link className={styles.navigationLink} href={comparisonPath(savedId)}>저장된 비교 결과 열기</Link></p> : null}
      <div><Button type="submit" variant="primary" disabled={!selected || reading || saving}>{saving ? "비교 결과 저장 중…" : "비교 결과 저장"}</Button></div>
    </form>
  </details>;
}
