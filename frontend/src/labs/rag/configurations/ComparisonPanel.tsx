import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../../shared/api/client";
import type {
  EvaluationCandidate,
  EvaluationMetrics,
  EvaluationRun,
  EvaluationRunCreate,
  SavedConfiguration,
} from "./api";
import {
  loadConfigurations,
  loadEvaluationRun,
  promoteConfiguration,
  startEvaluationRun,
} from "./api";

interface ComparisonPanelProps {
  configurations: SavedConfiguration[];
  initialRuns: EvaluationRun[];
  initialSelectedVersionIds?: string[];
  onConfigurationUpdated: (configuration: SavedConfiguration) => void;
}

const runStatusLabels: Record<EvaluationRun["status"], string> = {
  pending: "평가 대기",
  running: "평가 실행 중",
  completed: "평가 완료",
  failed: "평가 실패",
};

const candidateStatusLabels: Record<EvaluationCandidate["status"], string> = {
  pending: "대기",
  running: "실행 중",
  completed: "완료",
  failed: "실패",
};

const metricRows: Array<{
  key: keyof EvaluationMetrics;
  label: string;
  format: (value: number) => string;
}> = [
  { key: "recall_at_k", label: "Recall@K", format: formatRatio },
  { key: "mrr", label: "MRR", format: formatRatio },
  { key: "ndcg", label: "nDCG", format: formatRatio },
  { key: "supported_precision", label: "SUPPORTED 정밀도", format: formatRatio },
  { key: "false_grounding_rate", label: "잘못된 근거 비율", format: formatRatio },
  { key: "highlight_iou", label: "하이라이트 IoU", format: formatRatio },
  { key: "p50_latency_ms", label: "P50 지연", format: formatMilliseconds },
  { key: "p95_latency_ms", label: "P95 지연", format: formatMilliseconds },
  { key: "access_leaks", label: "접근권한 누출", format: (value) => String(value) },
  { key: "reproducibility", label: "재현 가능성", format: formatRatio },
];

export function ComparisonPanel({
  configurations,
  initialRuns,
  initialSelectedVersionIds = [],
  onConfigurationUpdated,
}: ComparisonPanelProps) {
  const baseline = configurations.find((configuration) => configuration.is_system);
  const selectableVersionIds = useMemo(
    () => new Set(
      configurations
        .filter((configuration) => !configuration.is_system)
        .map((configuration) => configuration.version_id),
    ),
    [configurations],
  );
  const initialRun = initialRuns[0] ?? null;
  const initialRunVersionIds = initialRun?.candidates
    .map((candidate) => candidate.configuration_version_id)
    .filter((versionId) => selectableVersionIds.has(versionId)) ?? [];
  const [selectedVersionIds, setSelectedVersionIds] = useState<string[]>(() =>
    unique([...initialSelectedVersionIds, ...initialRunVersionIds])
      .filter((versionId) => selectableVersionIds.has(versionId)),
  );
  const [datasetSnapshotId, setDatasetSnapshotId] = useState(
    initialRun?.dataset_snapshot_id ?? "",
  );
  const [evaluationPolicyVersionId, setEvaluationPolicyVersionId] = useState(
    initialRun?.evaluation_policy_version_id ?? "",
  );
  const [retrievalK, setRetrievalK] = useState(initialRun?.retrieval_k ?? 10);
  const [repetitionCount, setRepetitionCount] = useState(initialRun?.repetition_count ?? 2);
  const [activeRun, setActiveRun] = useState<EvaluationRun | null>(initialRun);
  const [starting, setStarting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [promotingId, setPromotingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const mounted = useRef(false);
  const runGeneration = useRef(0);
  const promotionGeneration = useRef(0);
  const startController = useRef<AbortController | null>(null);
  const refreshController = useRef<AbortController | null>(null);
  const promotionController = useRef<AbortController | null>(null);

  const orderedConfigurations = useMemo(() => {
    const selected = configurations.filter(
      (configuration) =>
        configuration.is_system || selectedVersionIds.includes(configuration.version_id),
    );
    return selected.sort((left, right) => {
      if (left.is_system !== right.is_system) return left.is_system ? -1 : 1;
      return left.name.localeCompare(right.name, "ko");
    });
  }, [configurations, selectedVersionIds]);

  const historicalCandidateCount = activeRun?.candidates.filter(
    (candidate) =>
      candidate.configuration_version_id !== baseline?.version_id &&
      !selectableVersionIds.has(candidate.configuration_version_id),
  ).length ?? 0;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      runGeneration.current += 1;
      promotionGeneration.current += 1;
      startController.current?.abort();
      refreshController.current?.abort();
      promotionController.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!activeRun || (activeRun.status !== "pending" && activeRun.status !== "running")) return;
    const controller = new AbortController();
    refreshController.current?.abort();
    refreshController.current = controller;
    const currentGeneration = runGeneration.current;
    const timeout = window.setTimeout(() => {
      void loadEvaluationRun(activeRun.id, controller.signal)
        .then((loaded) => {
          if (
            mounted.current &&
            runGeneration.current === currentGeneration &&
            !controller.signal.aborted
          ) {
            setActiveRun(loaded);
          }
        })
        .catch((caught: unknown) => {
          if (
            mounted.current &&
            runGeneration.current === currentGeneration &&
            !controller.signal.aborted
          ) {
            setError(evaluationErrorMessage(caught));
          }
        });
    }, 1500);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
      if (refreshController.current === controller) refreshController.current = null;
    };
  }, [activeRun]);

  function changeSelection(versionId: string, selected: boolean) {
    cancelRunOperations();
    setActiveRun(null);
    setError("");
    setSelectedVersionIds((current) =>
      selected ? unique([...current, versionId]) : current.filter((id) => id !== versionId),
    );
  }

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const snapshotId = datasetSnapshotId.trim();
    if (!snapshotId || starting) return;
    cancelRunOperations();
    const controller = new AbortController();
    startController.current = controller;
    const currentGeneration = runGeneration.current;
    const request: EvaluationRunCreate = {
      dataset_snapshot_id: snapshotId,
      evaluation_policy_version_id: evaluationPolicyVersionId.trim() || null,
      configuration_version_ids: selectedVersionIds.filter((versionId) =>
        selectableVersionIds.has(versionId)
      ),
      metric_definition_version: 1,
      retrieval_k: retrievalK,
      repetition_count: repetitionCount,
    };
    setStarting(true);
    setError("");
    try {
      const started = await startEvaluationRun(request, controller.signal);
      if (
        mounted.current &&
        runGeneration.current === currentGeneration &&
        startController.current === controller &&
        !controller.signal.aborted
      ) {
        setActiveRun(started);
      }
    } catch (caught) {
      if (
        mounted.current &&
        runGeneration.current === currentGeneration &&
        startController.current === controller &&
        !controller.signal.aborted
      ) {
        setError(evaluationErrorMessage(caught));
      }
    } finally {
      if (
        mounted.current &&
        runGeneration.current === currentGeneration &&
        startController.current === controller
      ) {
        startController.current = null;
        setStarting(false);
      }
    }
  }

  async function refreshRun() {
    if (!activeRun || starting || refreshing) return;
    refreshController.current?.abort();
    runGeneration.current += 1;
    const controller = new AbortController();
    refreshController.current = controller;
    const currentGeneration = runGeneration.current;
    setRefreshing(true);
    setError("");
    try {
      const loaded = await loadEvaluationRun(activeRun.id, controller.signal);
      if (
        mounted.current &&
        runGeneration.current === currentGeneration &&
        refreshController.current === controller &&
        !controller.signal.aborted
      ) {
        setActiveRun(loaded);
      }
    } catch (caught) {
      if (
        mounted.current &&
        runGeneration.current === currentGeneration &&
        refreshController.current === controller &&
        !controller.signal.aborted
      ) {
        setError(evaluationErrorMessage(caught));
      }
    } finally {
      if (
        mounted.current &&
        runGeneration.current === currentGeneration &&
        refreshController.current === controller
      ) {
        refreshController.current = null;
        setRefreshing(false);
      }
    }
  }

  async function promote(configuration: SavedConfiguration) {
    const candidate = activeRun?.candidates.find(
      (item) => item.configuration_version_id === configuration.version_id,
    );
    if (!hasAuthoritativePromotionEvidence(activeRun, configuration, candidate) || promotingId) {
      return;
    }
    promotionController.current?.abort();
    const controller = new AbortController();
    promotionController.current = controller;
    const currentGeneration = promotionGeneration.current + 1;
    promotionGeneration.current = currentGeneration;
    setPromotingId(configuration.id);
    setError("");
    try {
      const promoted = await promoteConfiguration(configuration.id, controller.signal);
      if (!isCurrentPromotion(currentGeneration, controller)) return;
      let synchronized: SavedConfiguration[];
      try {
        synchronized = await loadConfigurations(controller.signal);
      } catch {
        if (!isCurrentPromotion(currentGeneration, controller)) return;
        synchronized = configurations.map((current) => {
          if (current.id === promoted.id) return promoted;
          return current.is_default ? { ...current, is_default: false } : current;
        });
      }
      if (isCurrentPromotion(currentGeneration, controller)) {
        synchronized.forEach(onConfigurationUpdated);
      }
    } catch (caught) {
      if (isCurrentPromotion(currentGeneration, controller)) {
        setError(promotionErrorMessage(caught));
      }
    } finally {
      if (isCurrentPromotion(currentGeneration, controller)) {
        promotionController.current = null;
        setPromotingId(null);
      }
    }
  }

  function cancelRunOperations() {
    runGeneration.current += 1;
    startController.current?.abort();
    refreshController.current?.abort();
    startController.current = null;
    refreshController.current = null;
    setStarting(false);
    setRefreshing(false);
  }

  function isCurrentPromotion(currentGeneration: number, controller: AbortController) {
    return (
      mounted.current &&
      promotionGeneration.current === currentGeneration &&
      promotionController.current === controller &&
      !controller.signal.aborted
    );
  }

  return (
    <section className="comparison-panel" aria-labelledby="comparison-title">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">FROZEN EVALUATION</p>
          <h2 id="comparison-title">비교 실험</h2>
        </div>
        <p>가장 높은 단일 지표가 아니라 정책으로 검증된 평가 상태가 운영 승격을 결정합니다.</p>
      </div>

      <form className="evaluation-controls" onSubmit={handleStart}>
        <fieldset disabled={starting}>
          <legend>비교 후보</legend>
          {baseline ? (
            <label>
              <input type="checkbox" checked disabled readOnly />
              {baseline.name} v{baseline.version} · {baseline.version_id} (자동 포함)
            </label>
          ) : <p className="form-error" role="alert">서버가 제공한 BM25 시스템 기준선이 없습니다.</p>}
          {configurations.filter((configuration) => !configuration.is_system).map((configuration) => (
            <label key={configuration.version_id}>
              <input
                type="checkbox"
                checked={selectedVersionIds.includes(configuration.version_id)}
                onChange={(event) => changeSelection(configuration.version_id, event.target.checked)}
              />
              {configuration.name} v{configuration.version} · {configuration.version_id}
            </label>
          ))}
          {historicalCandidateCount > 0 ? (
            <p className="unmeasured-state">
              현재 저장 목록에 없는 과거 후보 {historicalCandidateCount}개는 읽기 전용이며 새 실행 선택에서 제외됩니다.
            </p>
          ) : null}
        </fieldset>
        <div className="evaluation-input-grid">
          <label>
            데이터셋 스냅샷 ID
            <input
              value={datasetSnapshotId}
              onChange={(event) => setDatasetSnapshotId(event.target.value)}
              required
            />
          </label>
          <label>
            평가 정책 버전 ID (선택)
            <input
              value={evaluationPolicyVersionId}
              onChange={(event) => setEvaluationPolicyVersionId(event.target.value)}
            />
          </label>
          <label>
            Retrieval K
            <input
              type="number"
              min="1"
              max="50"
              value={retrievalK}
              onChange={(event) => setRetrievalK(Number(event.target.value))}
            />
          </label>
          <label>
            반복 횟수
            <input
              type="number"
              min="2"
              max="5"
              value={repetitionCount}
              onChange={(event) => setRepetitionCount(Number(event.target.value))}
            />
          </label>
        </div>
        <div className="comparison-actions">
          <button type="submit" disabled={starting || !baseline || !datasetSnapshotId.trim()}>
            {starting ? "평가 실행 생성 중…" : "평가 실행 시작"}
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={!activeRun || starting || refreshing}
            onClick={() => void refreshRun()}
          >
            {refreshing ? "새로고침 중…" : "현재 실행 새로고침"}
          </button>
        </div>
      </form>

      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {activeRun ? (
        <div className="run-summary">
          <p role="status"><strong>{runStatusLabels[activeRun.status]}</strong> · 실행 {activeRun.id}</p>
          <p>데이터셋 {activeRun.dataset_snapshot_id} · 실행 스냅샷 {activeRun.execution_snapshot_sha256}</p>
          {activeRun.failure ? <p className="form-error">평가 실행에 실패했습니다.</p> : null}
        </div>
      ) : null}

      <div className="comparison-results">
        {orderedConfigurations.map((configuration) => {
          const candidate = activeRun?.candidates.find(
            (item) => item.configuration_version_id === configuration.version_id,
          );
          const canPromote = hasAuthoritativePromotionEvidence(
            activeRun,
            configuration,
            candidate,
          );
          return (
            <CandidateResult
              key={configuration.version_id}
              configuration={configuration}
              candidate={candidate}
              canPromote={canPromote}
              promoting={promotingId === configuration.id}
              onPromote={() => void promote(configuration)}
            />
          );
        })}
      </div>
    </section>
  );
}

function CandidateResult({
  configuration,
  candidate,
  canPromote,
  promoting,
  onPromote,
}: {
  configuration: SavedConfiguration;
  candidate: EvaluationCandidate | undefined;
  canPromote: boolean;
  promoting: boolean;
  onPromote: () => void;
}) {
  const failedCases = candidate?.case_results.filter(isFailedCase) ?? [];
  return (
    <article className="candidate-result" aria-label={`${configuration.name} 평가 결과`}>
      <div className="candidate-heading">
        <div>
          <h3>{configuration.name} v{configuration.version}</h3>
          <p>{configuration.version_id}</p>
        </div>
        <span>{candidate ? candidateStatusLabels[candidate.status] : "선택됨"}</span>
      </div>
      {candidate?.failure ? <p className="form-error">후보 평가에 실패했습니다.</p> : null}
      {candidate?.metrics ? (
        <table>
          <caption>반환된 평가 지표</caption>
          <tbody>
            {metricRows.map((row) => (
              <tr key={row.key}>
                <th scope="row">{row.label}</th>
                <td>{row.format(candidate.metrics![row.key])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="unmeasured-state">평가 전</p>}

      {failedCases.length > 0 ? (
        <section className="failed-cases" aria-label="실패 사례">
          <h4>실패 사례</h4>
          <ul>
            {failedCases.map((evaluationCase) => (
              <li id={`case-${evaluationCase.evaluation_case_id}`} key={evaluationCase.evaluation_case_id}>
                <a href={`#case-${evaluationCase.evaluation_case_id}`}>
                  사례 {evaluationCase.evaluation_case_id}
                </a>
                <span>질의 해시 {evaluationCase.query_sha256}</span>
                <span>기대 근거 {evaluationCase.expected_evidence_ids.join(", ") || "없음"}</span>
                <span>관찰된 실패 신호 {failureSignals(evaluationCase).join(" · ")}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p>평가 상태: {configuration.evaluation_state}</p>
      {canPromote ? <p>정책 근거 확인됨 · 서버 최종 판정 필요</p> : null}
      <button
        type="button"
        disabled={
          !canPromote ||
          configuration.is_default ||
          promoting
        }
        onClick={onPromote}
      >
        {promoting ? "승격 중…" : "운영 기본값으로 승격"}
      </button>
    </article>
  );
}

function isFailedCase(evaluationCase: EvaluationCandidate["case_results"][number]): boolean {
  return failureSignals(evaluationCase).length > 0;
}

function failureSignals(
  evaluationCase: EvaluationCandidate["case_results"][number],
): string[] {
  const signals: string[] = [];
  if (evaluationCase.recall_at_k === 0) signals.push("Recall@K=0");
  if (evaluationCase.reciprocal_rank === 0) signals.push("Reciprocal Rank=0");
  if (evaluationCase.ndcg === 0) signals.push("nDCG=0");
  if (evaluationCase.highlight_iou === 0) signals.push("Highlight IoU=0");
  if (evaluationCase.correct_supported === false) signals.push("SUPPORTED 판정=false");
  if (evaluationCase.false_grounding === true) signals.push("잘못된 근거=true");
  if (evaluationCase.access_leaks > 0) {
    signals.push(`접근권한 누출=${evaluationCase.access_leaks}`);
  }
  if (!evaluationCase.reproducible) signals.push("재현 가능=false");
  return signals;
}

function hasAuthoritativePromotionEvidence(
  run: EvaluationRun | null,
  configuration: SavedConfiguration,
  candidate: EvaluationCandidate | undefined,
): boolean {
  return Boolean(
    !configuration.is_system &&
    run?.status === "completed" &&
    run.evaluation_policy_version_id &&
    !run.failure &&
    candidate?.configuration_version_id === configuration.version_id &&
    candidate.status === "completed" &&
    !candidate.failure,
  );
}

function formatRatio(value: number): string {
  return value.toLocaleString("ko-KR", { maximumFractionDigits: 6 });
}

function formatMilliseconds(value: number): string {
  return `${value.toLocaleString("ko-KR", { maximumFractionDigits: 3 })} ms`;
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

function evaluationErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "평가 실행을 처리하지 못했습니다.";
  if (error.status === 401) return "로그인이 필요합니다.";
  if (error.status === 404) return "데이터셋, 구성 버전 또는 평가 실행을 찾을 수 없습니다.";
  if (error.status === 409) return "선택한 평가 입력의 현재 상태가 실행과 호환되지 않습니다.";
  if (error.status === 422) return "스냅샷 ID와 평가 입력을 확인해 주세요.";
  if (error.status === 503) return "평가 서비스를 잠시 사용할 수 없습니다.";
  return "평가 실행을 처리하지 못했습니다.";
}

function promotionErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "운영 기본값으로 승격하지 못했습니다.";
  if (error.status === 401) return "로그인이 필요합니다.";
  if (error.status === 404) return "승격할 구성을 찾을 수 없습니다.";
  if (error.status === 409) return "정책으로 검증된 평가 통과 근거가 없어 승격할 수 없습니다.";
  if (error.status === 422) return "승격할 구성 상태를 확인해 주세요.";
  if (error.status === 503) return "승격 서비스를 잠시 사용할 수 없습니다.";
  return "운영 기본값으로 승격하지 못했습니다.";
}
