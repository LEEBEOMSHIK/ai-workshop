"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { ApiError } from "../../shared/api/client";
import type {
  EvaluationRun,
  ExperimentFields,
  LearningDraft,
  LearningSummary,
  LearningTopic,
  ReferenceKey,
  ReferenceView,
  TroubleshootingFields,
} from "./api";
import styles from "./Learning.module.css";
import {
  emptyExperiment,
  emptyTroubleshooting,
  experimentStatusOptions,
  recordKindOptions,
} from "./registry";
import { useUnsavedChanges } from "./useUnsavedChanges";

interface ReferenceOption {
  key: ReferenceKey;
  label: string;
}

export interface LearningEditorProps {
  initialDraft: LearningDraft;
  topics: LearningTopic[];
  learningRecords: LearningSummary[];
  evaluations: EvaluationRun[];
  referenceViews?: ReferenceView[];
  datasetReferenceView?: ReferenceView | null;
  unavailableReferenceCount?: number;
  disabled?: boolean;
  externallyPending?: boolean;
  submitLabel: string;
  onDirtyChange?: (dirty: boolean) => void;
  onDraftChange?: (draft: LearningDraft) => void;
  onSaved?: () => void;
  onSubmit: (draft: LearningDraft) => Promise<void>;
}

export function LearningEditor({
  initialDraft,
  topics,
  learningRecords,
  evaluations,
  referenceViews = [],
  datasetReferenceView = null,
  unavailableReferenceCount = 0,
  disabled = false,
  externallyPending = false,
  submitLabel,
  onDirtyChange,
  onDraftChange,
  onSaved,
  onSubmit,
}: LearningEditorProps) {
  const [draft, setDraft] = useState(initialDraft);
  const [domainText, setDomainText] = useState(initialDraft.domain_labels.join(", "));
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState(false);
  const [hasInvalidMetric, setHasInvalidMetric] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const options = useMemo(
    () => referenceOptions(learningRecords, evaluations),
    [learningRecords, evaluations],
  );
  const allowSuccessfulNavigation = useUnsavedChanges(dirty);

  const change = (next: LearningDraft) => {
    setDraft(next);
    setDirty(true);
    onDirtyChange?.(true);
    onDraftChange?.(next);
    setError(null);
  };

  const handleKind = (kind: LearningDraft["kind"]) => {
    if (draft.kind === "note" && kind === "experiment") {
      if (!window.confirm("자유 메모를 구조화 실험으로 전환할까요? 원문과 참조는 그대로 유지됩니다.")) {
        return;
      }
      change({ ...draft, kind, experiment: emptyExperiment() });
      return;
    }
    if (kind === "note") setHasInvalidMetric(false);
    change({ ...draft, kind, experiment: kind === "experiment" ? draft.experiment ?? emptyExperiment() : null });
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (pending || externallyPending || disabled) return;
    if (!draft.title.trim() || !draft.body.trim()) {
      setError("제목과 본문은 공백만으로 저장할 수 없습니다.");
      return;
    }
    if (hasInvalidMetric) {
      setError("지표 값은 비워 둘 수 없습니다. 값을 입력하거나 지표를 삭제해 주세요.");
      return;
    }
    if (
      unavailableReferenceCount > 0 &&
      !window.confirm(`접근할 수 없는 참조 ${unavailableReferenceCount}개가 저장 시 제거됩니다. 계속할까요?`)
    ) return;
    setPending(true);
    setError(null);
    try {
      await onSubmit(draft);
      setDirty(false);
      onDirtyChange?.(false);
      allowSuccessfulNavigation();
      onSaved?.();
    } catch (caught) {
      if (!(caught instanceof ApiError && caught.status === 409)) {
        setError(caught instanceof ApiError ? caught.message : "기록을 저장하지 못했습니다.");
      }
    } finally {
      setPending(false);
    }
  };

  const experiment = draft.kind === "experiment" ? draft.experiment ?? emptyExperiment() : null;
  const updateExperiment = (next: ExperimentFields) => change({ ...draft, experiment: next });

  return (
    <form className={styles.editor} onSubmit={submit}>
      <div className={styles.formGrid}>
        <label>
          제목
          <input required disabled={disabled || pending || externallyPending} value={draft.title} onChange={(event) => change({ ...draft, title: event.target.value })} />
        </label>
        <label>
          기록 종류
          <select disabled={disabled || pending || externallyPending} value={draft.kind} onChange={(event) => handleKind(event.target.value as LearningDraft["kind"])}>
            {recordKindOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
      </div>
      <label>
        본문
        <textarea required rows={9} disabled={disabled || pending || externallyPending} value={draft.body} onChange={(event) => change({ ...draft, body: event.target.value })} />
      </label>

      <fieldset disabled={disabled || pending || externallyPending}>
        <legend>기술 주제</legend>
        <div className={styles.checkGrid}>
          {topics.map((topic) => (
            <label key={topic.key}>
              <input
                type="checkbox"
                checked={draft.topic_keys.includes(topic.key)}
                onChange={(event) => change({
                  ...draft,
                  topic_keys: event.target.checked
                    ? [...draft.topic_keys, topic.key]
                    : draft.topic_keys.filter((key) => key !== topic.key),
                })}
              />
              {topic.label}
            </label>
          ))}
        </div>
      </fieldset>
      <label>
        도메인 분류
        <input
          disabled={disabled || pending || externallyPending}
          value={domainText}
          placeholder="예: research, asset-management"
          onChange={(event) => {
            setDomainText(event.target.value);
            change({ ...draft, domain_labels: commaList(event.target.value) });
          }}
        />
      </label>

      {experiment ? (
        <ExperimentEditor
          disabled={disabled || pending || externallyPending}
          value={experiment}
          onChange={updateExperiment}
          referenceOptions={options}
          datasetReferenceView={datasetReferenceView}
          onMetricValidityChange={setHasInvalidMetric}
        />
      ) : null}

      <ReferenceEditor
        disabled={disabled || pending || externallyPending}
        options={options}
        value={draft.references}
        views={referenceViews}
        onChange={(references) => change({ ...draft, references })}
      />
      {unavailableReferenceCount > 0 ? (
        <p className={styles.warning} role="status">접근할 수 없는 참조 {unavailableReferenceCount}개</p>
      ) : null}
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {!disabled ? <button type="submit" disabled={pending || externallyPending}>{pending ? "저장 중…" : submitLabel}</button> : null}
    </form>
  );
}

function ExperimentEditor({
  value,
  onChange,
  disabled,
  referenceOptions,
  datasetReferenceView,
  onMetricValidityChange,
}: {
  value: ExperimentFields;
  onChange: (value: ExperimentFields) => void;
  disabled: boolean;
  referenceOptions: ReferenceOption[];
  datasetReferenceView: ReferenceView | null;
  onMetricValidityChange: (invalid: boolean) => void;
}) {
  const setText = (key: keyof ExperimentFields, text: string) => onChange({ ...value, [key]: text || null });
  const troubleshooting = value.troubleshooting;
  return (
    <section className={styles.experiment} aria-label="구조화 실험">
      <h2>구조화 실험</h2>
      <div className={styles.formGrid}>
        <label>실험 상태<select disabled={disabled} value={value.status} onChange={(event) => onChange({ ...value, status: event.target.value as ExperimentFields["status"] })}>{experimentStatusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label>목적<textarea disabled={disabled} value={value.purpose ?? ""} onChange={(event) => setText("purpose", event.target.value)} /></label>
        <label>가설<textarea disabled={disabled} value={value.hypothesis ?? ""} onChange={(event) => setText("hypothesis", event.target.value)} /></label>
        <ReferenceSelect label="데이터 snapshot" disabled={disabled} options={referenceOptions} value={value.dataset_snapshot ?? null} view={datasetReferenceView} onChange={(dataset_snapshot) => onChange({ ...value, dataset_snapshot })} />
        <ListField label="비교 구성" disabled={disabled} value={value.configurations} onChange={(configurations) => onChange({ ...value, configurations })} />
        <label>실행 환경<textarea disabled={disabled} value={value.environment ?? ""} onChange={(event) => setText("environment", event.target.value)} /></label>
        <label>절차<textarea disabled={disabled} value={value.procedure ?? ""} onChange={(event) => setText("procedure", event.target.value)} /></label>
        <label>관찰<textarea disabled={disabled} value={value.observations ?? ""} onChange={(event) => setText("observations", event.target.value)} /></label>
        <label>한계<textarea disabled={disabled} value={value.limitations ?? ""} onChange={(event) => setText("limitations", event.target.value)} /></label>
        <label>결론<textarea disabled={disabled} value={value.conclusion ?? ""} onChange={(event) => setText("conclusion", event.target.value)} /></label>
        <ListField label="다음 작업" disabled={disabled} value={value.next_steps} onChange={(next_steps) => onChange({ ...value, next_steps })} />
      </div>
      <MetricEditor disabled={disabled} value={value.metrics} onChange={(metrics) => onChange({ ...value, metrics })} onValidityChange={onMetricValidityChange} />
      <details>
        <summary>문제 해결 기록</summary>
        <label className={styles.inlineToggle}><input type="checkbox" disabled={disabled} checked={troubleshooting !== null && troubleshooting !== undefined} onChange={(event) => onChange({ ...value, troubleshooting: event.target.checked ? emptyTroubleshooting() : null })} />문제 해결 필드 사용</label>
        {troubleshooting ? <TroubleshootingEditor disabled={disabled} value={troubleshooting} onChange={(next) => onChange({ ...value, troubleshooting: next })} /> : null}
      </details>
    </section>
  );
}

function MetricEditor({ value, onChange, onValidityChange, disabled }: { value: ExperimentFields["metrics"]; onChange: (value: ExperimentFields["metrics"]) => void; onValidityChange: (invalid: boolean) => void; disabled: boolean }) {
  const [name, setName] = useState("");
  const [rawValue, setRawValue] = useState("");
  const [unit, setUnit] = useState("");
  const [savedRawValues, setSavedRawValues] = useState(() => value.map((metric) => String(metric.value)));
  const [invalidIndexes, setInvalidIndexes] = useState<Set<number>>(() => new Set());
  const numericValue = rawValue.trim() === "" ? null : Number(rawValue);
  const canAdd = name.trim().length > 0 && numericValue !== null && Number.isFinite(numericValue);
  return (
    <fieldset disabled={disabled}>
      <legend>평가 지표</legend>
      {value.map((metric, index) => (
        <div className={styles.metricRow} key={index}>
          <label>지표 이름<input value={metric.name} onChange={(event) => onChange(value.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} /></label>
          <label>값<input type="number" step="any" value={savedRawValues[index] ?? String(metric.value)} onChange={(event) => {
            const raw = event.target.value;
            setSavedRawValues((items) => items.map((item, itemIndex) => itemIndex === index ? raw : item));
            const numeric = raw.trim() === "" ? null : Number(raw);
            const nextInvalid = new Set(invalidIndexes);
            if (numeric === null || !Number.isFinite(numeric)) nextInvalid.add(index);
            else nextInvalid.delete(index);
            setInvalidIndexes(nextInvalid);
            onValidityChange(nextInvalid.size > 0);
            if (numeric !== null && Number.isFinite(numeric)) onChange(value.map((item, itemIndex) => itemIndex === index ? { ...item, value: numeric } : item));
          }} /></label>
          <label>단위<input value={metric.unit ?? ""} onChange={(event) => onChange(value.map((item, itemIndex) => itemIndex === index ? { ...item, unit: event.target.value || null } : item))} /></label>
          <button type="button" onClick={() => {
            setSavedRawValues((items) => items.filter((_, itemIndex) => itemIndex !== index));
            const nextInvalid = new Set([...invalidIndexes].filter((itemIndex) => itemIndex !== index).map((itemIndex) => itemIndex > index ? itemIndex - 1 : itemIndex));
            setInvalidIndexes(nextInvalid);
            onValidityChange(nextInvalid.size > 0);
            onChange(value.filter((_, itemIndex) => itemIndex !== index));
          }}>지표 삭제</button>
        </div>
      ))}
      <div className={styles.metricRow}>
        <label>새 지표 이름<input value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label>새 지표 값<input type="number" step="any" value={rawValue} onChange={(event) => setRawValue(event.target.value)} /></label>
        <label>새 지표 단위<input value={unit} onChange={(event) => setUnit(event.target.value)} /></label>
        <button
          type="button"
          disabled={!canAdd}
          onClick={() => {
            if (!canAdd || numericValue === null) return;
            setSavedRawValues((items) => [...items, String(numericValue)]);
            onChange([...value, { name: name.trim(), value: numericValue, unit: unit.trim() || null }]);
            setName("");
            setRawValue("");
            setUnit("");
          }}
        >지표 추가</button>
      </div>
    </fieldset>
  );
}

function TroubleshootingEditor({ value, onChange, disabled }: { value: TroubleshootingFields; onChange: (value: TroubleshootingFields) => void; disabled: boolean }) {
  const text = (key: keyof TroubleshootingFields, label: string) => <label>{label}<textarea disabled={disabled} value={(value[key] as string | null | undefined) ?? ""} onChange={(event) => onChange({ ...value, [key]: event.target.value || null })} /></label>;
  return <div className={styles.formGrid}>{text("symptom", "증상")}{text("reproduction", "재현 조건")}<ListField label="확인된 사실" disabled={disabled} value={value.facts} onChange={(facts) => onChange({ ...value, facts })} /><ListField label="원인 가설" disabled={disabled} value={value.hypotheses} onChange={(hypotheses) => onChange({ ...value, hypotheses })} />{text("confirmed_cause", "확정 원인")}{text("change", "변경 사항")}{text("verification", "재검증 결과")}<ListField label="미해결 항목" disabled={disabled} value={value.unresolved} onChange={(unresolved) => onChange({ ...value, unresolved })} /></div>;
}

function ListField({ label, value, onChange, disabled }: { label: string; value: string[]; onChange: (value: string[]) => void; disabled: boolean }) {
  const [rawValue, setRawValue] = useState(value.join("\n"));
  return <label>{label}<textarea disabled={disabled} value={rawValue} placeholder="한 줄에 하나씩 입력" onChange={(event) => { setRawValue(event.target.value); onChange(lineList(event.target.value)); }} /></label>;
}

function ReferenceEditor({ value, onChange, options, views, disabled }: { value: ReferenceKey[]; onChange: (value: ReferenceKey[]) => void; options: ReferenceOption[]; views: ReferenceView[]; disabled: boolean }) {
  const [selection, setSelection] = useState("");
  return (
    <fieldset disabled={disabled}>
      <legend>관련 참조</legend>
      <div className={styles.referenceAdd}>
        <label>참조 선택<select value={selection} onChange={(event) => setSelection(event.target.value)}><option value="">선택하세요</option>{options.map((option) => <option key={referenceValue(option.key)} value={referenceValue(option.key)}>{option.label}</option>)}</select></label>
        <button type="button" disabled={!selection} onClick={() => { const option = options.find((candidate) => referenceValue(candidate.key) === selection); if (option && !value.some((key) => referenceValue(key) === selection)) onChange([...value, option.key]); setSelection(""); }}>참조 추가</button>
      </div>
      <ul className={styles.referenceList}>
        {value.map((key, index) => {
          const indexedView = views[index];
          const view = views.find((candidate) => candidate.status === "available" && candidate.key && sameReference(candidate.key, key))
            ?? (indexedView?.status === "unavailable" ? indexedView : undefined);
          const label = (view?.status === "available" ? view.label : null)
            ?? options.find((option) => sameReference(option.key, key))?.label;
          const content = view?.status === "available" && view.href
            ? <Link href={view.href}>{label ?? view.label}</Link>
            : <span>{label ?? "확인 가능한 참조"}</span>;
          return <li key={`${referenceValue(key)}-${index}`}>{content}<button type="button" onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))}>참조 삭제</button></li>;
        })}
      </ul>
    </fieldset>
  );
}

function ReferenceSelect({ label, value, onChange, options, view, disabled }: { label: string; value: ReferenceKey | null; onChange: (value: ReferenceKey | null) => void; options: ReferenceOption[]; view: ReferenceView | null; disabled: boolean }) {
  const current = value ? referenceValue(value) : "";
  const currentLabel = view?.status === "available" ? view.label : null;
  return <label>{label}<select disabled={disabled} aria-label={label} value={current} onChange={(event) => onChange(options.find((option) => referenceValue(option.key) === event.target.value)?.key ?? null)}><option value="">선택 안 함</option>{current && currentLabel && !options.some((option) => referenceValue(option.key) === current) ? <option value={current}>{currentLabel}</option> : null}{options.map((option) => <option key={referenceValue(option.key)} value={referenceValue(option.key)}>{option.label}</option>)}</select></label>;
}

function referenceOptions(records: LearningSummary[], evaluations: EvaluationRun[]): ReferenceOption[] {
  const evaluationBaseLabels = evaluations.map((run) => `RAG 평가 · ${evaluationStatusLabels[run.status]} · ${formatDate(run.created_at)}`);
  const evaluationLabelCounts = new Map<string, number>();
  for (const label of evaluationBaseLabels) evaluationLabelCounts.set(label, (evaluationLabelCounts.get(label) ?? 0) + 1);
  const evaluationLabelIndexes = new Map<string, number>();
  return [
    { key: { kind: "service", target: "rag.search", version: null }, label: "RAG 검색 서비스" },
    ...records.map((record) => ({ key: { kind: "learning.record", target: record.id, version: null }, label: `학습 기록 · ${record.title}` })),
    ...evaluations.map((run, index) => {
      const baseLabel = evaluationBaseLabels[index];
      const collisionIndex = (evaluationLabelIndexes.get(baseLabel) ?? 0) + 1;
      evaluationLabelIndexes.set(baseLabel, collisionIndex);
      return {
        key: { kind: "rag.evaluation" as const, target: run.id, version: null },
        label: evaluationLabelCounts.get(baseLabel) === 1 ? baseLabel : `${baseLabel} · ${collisionIndex}`,
      };
    }),
  ];
}

const evaluationStatusLabels: Record<EvaluationRun["status"], string> = {
  pending: "대기 중",
  running: "진행 중",
  completed: "완료",
  failed: "실패",
};

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function referenceValue(key: ReferenceKey): string { return `${key.kind}\u001f${key.target}\u001f${key.version ?? ""}`; }
function sameReference(left: ReferenceKey, right: ReferenceKey): boolean { return referenceValue(left) === referenceValue(right); }
function lineList(value: string): string[] { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
function commaList(value: string): string[] { return value.split(",").map((item) => item.trim()).filter(Boolean); }
