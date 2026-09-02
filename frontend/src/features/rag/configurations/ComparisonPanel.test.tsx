import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { ComparisonPanel } from "./ComparisonPanel";
import type { EvaluationRun, SavedConfiguration } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ComparisonPanel", () => {
  it("fixes BM25 first, selects only exact saved versions, and never renders missing metrics as zero", async () => {
    const user = userEvent.setup();
    render(
      <ComparisonPanel
        configurations={[baselineConfiguration(), savedConfiguration()]}
        initialRuns={[]}
        onConfigurationUpdated={() => undefined}
      />,
    );

    const baseline = screen.getByRole("checkbox", { name: /BM25 기준선/ });
    expect(baseline).toBeChecked();
    expect(baseline).toBeDisabled();
    expect(screen.getByText("평가 전")).toBeVisible();
    expect(screen.queryByText(/^0(?:\.0+)?$/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /운영 기본값으로 승격/ })).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: "내 E5 구성 v2" }));
    const savedResult = screen.getByRole("article", { name: "내 E5 구성 평가 결과" });
    expect(within(savedResult).queryByText("version-e5", { exact: false })).not.toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", { name: "데이터셋 스냅샷 ID" }),
      "11111111-1111-4111-8111-111111111111",
    );
    expect(screen.getByRole("button", { name: "평가 실행 시작" })).toBeEnabled();
  });

  it("starts a run without duplicating the automatic BM25 candidate", async () => {
    let requestBody: unknown;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (input === "/api/v1/rag/evaluation-runs") {
          requestBody = JSON.parse(String(init?.body)) as unknown;
          return jsonResponse(pendingRun(), 202);
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <ComparisonPanel
        configurations={[baselineConfiguration(), savedConfiguration()]}
        initialRuns={[]}
        onConfigurationUpdated={() => undefined}
      />,
    );

    await user.click(screen.getByRole("checkbox", { name: /내 E5 구성/ }));
    await user.type(
      screen.getByRole("textbox", { name: "데이터셋 스냅샷 ID" }),
      "11111111-1111-4111-8111-111111111111",
    );
    await user.click(screen.getByRole("button", { name: "평가 실행 시작" }));

    expect(requestBody).toEqual({
      dataset_snapshot_id: "11111111-1111-4111-8111-111111111111",
      evaluation_policy_version_id: null,
      configuration_version_ids: ["version-e5"],
      metric_definition_version: 1,
      retrieval_k: 10,
      repetition_count: 2,
    });
    expect(screen.getByRole("status")).toHaveTextContent("평가 대기");
  });

  it("allows an authoritative promotion attempt for a pending configuration with exact policy-backed completed evidence and resynchronizes every default", async () => {
    const promoted = savedConfiguration({ evaluation_state: "passed", is_default: true, experimental: false });
    const priorDefault = savedConfiguration({
      id: "configuration-prior",
      version_id: "version-prior",
      name: "이전 운영 구성",
      is_default: true,
      experimental: false,
    });
    const synchronized = [
      baselineConfiguration({ is_default: false }),
      { ...priorDefault, is_default: false },
      promoted,
    ];
    const onConfigurationUpdated = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (input === "/api/v1/rag/configurations/configuration-e5/default") {
          return jsonResponse(promoted);
        }
        if (input === "/api/v1/rag/configurations") return jsonResponse(synchronized);
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <ComparisonPanel
        configurations={[
          baselineConfiguration(),
          priorDefault,
          savedConfiguration(),
        ]}
        initialRuns={[completedRun()]}
        onConfigurationUpdated={onConfigurationUpdated}
      />,
    );

    const result = screen.getByRole("article", { name: /내 E5 구성 평가 결과/ });
    for (const label of [
      "Recall@K",
      "MRR",
      "nDCG",
      "SUPPORTED 정밀도",
      "잘못된 근거 비율",
      "하이라이트 IoU",
      "P50 지연",
      "P95 지연",
      "접근권한 누출",
      "재현 가능성",
    ]) {
      expect(within(result).getByText(label)).toBeVisible();
    }
    const failedCase = within(result).getByRole("link", { name: /case-failed/ });
    expect(failedCase).toHaveAttribute("href", "#case-case-failed");
    expect(failedCase.closest("li")).toHaveTextContent("evidence-expected-1");

    const promote = within(result).getByRole("button", { name: /운영 기본값으로 승격/ });
    expect(promote).toBeEnabled();
    await user.click(promote);
    await waitFor(() => expect(onConfigurationUpdated).toHaveBeenCalledTimes(3));
    expect(onConfigurationUpdated.mock.calls.map(([configuration]) => configuration)).toEqual(synchronized);
  });

  it.each([
    ["queued run", completedRun({ status: "pending" })],
    ["running run", completedRun({ status: "running" })],
    ["no policy", completedRun({ evaluation_policy_version_id: null })],
    ["running candidate", completedRun({ candidateStatus: "running" })],
    ["wrong version", completedRun({ candidateVersionId: "version-historical" })],
  ])("keeps promotion disabled for %s without exact completed policy evidence", (_label, run) => {
    render(
      <ComparisonPanel
        configurations={[baselineConfiguration(), savedConfiguration()]}
        initialRuns={[run]}
        onConfigurationUpdated={() => undefined}
      />,
    );

    for (const button of screen.getAllByRole("button", { name: /운영 기본값으로 승격/ })) {
      expect(button).toBeDisabled();
    }
  });

  it("does not import or submit a historical version from the latest run", async () => {
    let requestBody: EvaluationRunCreateBody | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (input === "/api/v1/rag/evaluation-runs") {
          requestBody = JSON.parse(String(init?.body)) as EvaluationRunCreateBody;
          return jsonResponse(pendingRun(), 202);
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const historicalRun = completedRun({ candidateVersionId: "version-historical" });
    const user = userEvent.setup();
    render(
      <ComparisonPanel
        configurations={[baselineConfiguration(), savedConfiguration()]}
        initialRuns={[historicalRun]}
        initialSelectedVersionIds={["version-historical"]}
        onConfigurationUpdated={() => undefined}
      />,
    );

    expect(screen.getByRole("checkbox", { name: /내 E5 구성/ })).not.toBeChecked();
    expect(screen.getByText(/현재 저장 목록에 없는 과거 후보 1개/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "평가 실행 시작" }));
    expect(requestBody?.configuration_version_ids).toEqual([]);
  });

  it("aborts and releases a refresh before starting a new run", async () => {
    const refresh = deferred<Response>();
    let refreshSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (input === "/api/v1/rag/evaluation-runs/run-completed") {
          refreshSignal = init?.signal as AbortSignal;
          return refresh.promise;
        }
        if (input === "/api/v1/rag/evaluation-runs") return jsonResponse(pendingRun(), 202);
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <ComparisonPanel
        configurations={[baselineConfiguration(), savedConfiguration()]}
        initialRuns={[completedRun()]}
        onConfigurationUpdated={() => undefined}
      />,
    );

    await user.click(screen.getByRole("button", { name: "현재 실행 새로고침" }));
    await waitFor(() => expect(refreshSignal).toBeDefined());
    await user.click(screen.getByRole("button", { name: "평가 실행 시작" }));
    expect(refreshSignal?.aborted).toBe(true);
    expect(await screen.findByRole("status")).toHaveTextContent("평가 대기");
    expect(screen.queryByRole("button", { name: "새로고침 중…" })).not.toBeInTheDocument();
  });

  it("serializes refresh behind a pending start even when the refresh handler is forced", async () => {
    const start = deferred<Response>();
    const refresh = deferred<Response>();
    let startSignal: AbortSignal | undefined;
    let refreshRequests = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (input === "/api/v1/rag/evaluation-runs") {
          startSignal = init?.signal as AbortSignal;
          return start.promise;
        }
        if (input === "/api/v1/rag/evaluation-runs/run-completed") {
          refreshRequests += 1;
          return refresh.promise;
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <ComparisonPanel
        configurations={[baselineConfiguration(), savedConfiguration()]}
        initialRuns={[completedRun()]}
        onConfigurationUpdated={() => undefined}
      />,
    );

    await user.click(screen.getByRole("button", { name: "평가 실행 시작" }));
    await waitFor(() => expect(startSignal).toBeDefined());
    const refreshButton = screen.getByRole("button", { name: "현재 실행 새로고침" });
    const refreshWasDisabled = refreshButton.hasAttribute("disabled");
    refreshButton.removeAttribute("disabled");
    fireEvent.click(refreshButton);
    await Promise.resolve();
    if (refreshRequests > 0) refresh.resolve(jsonResponse(completedRun()));
    start.resolve(jsonResponse(pendingRun(), 202));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("run-pending");
      expect(screen.getByRole("button", { name: "평가 실행 시작" })).toBeEnabled();
    });
    expect(refreshWasDisabled).toBe(true);
    expect(refreshRequests).toBe(0);
    expect(startSignal?.aborted).toBe(false);
  });

  it("keeps promotion independent through selection changes and a new run, then applies only the synchronized list", async () => {
    const promotion = deferred<Response>();
    const promoted = savedConfiguration({ evaluation_state: "passed", is_default: true });
    const synchronized = [baselineConfiguration({ is_default: false }), promoted];
    const onConfigurationUpdated = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (input === "/api/v1/rag/configurations/configuration-e5/default") return promotion.promise;
        if (input === "/api/v1/rag/evaluation-runs") return jsonResponse(pendingRun(), 202);
        if (input === "/api/v1/rag/configurations") return jsonResponse(synchronized);
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <ComparisonPanel
        configurations={[baselineConfiguration(), savedConfiguration()]}
        initialRuns={[completedRun()]}
        onConfigurationUpdated={onConfigurationUpdated}
      />,
    );

    const result = screen.getByRole("article", { name: /내 E5 구성 평가 결과/ });
    await user.click(within(result).getByRole("button", { name: /운영 기본값으로 승격/ }));
    expect(screen.getByRole("button", { name: "승격 중…" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /내 E5 구성/ }));
    await user.click(screen.getByRole("button", { name: "평가 실행 시작" }));
    promotion.resolve(jsonResponse(promoted));

    await waitFor(() => expect(onConfigurationUpdated).toHaveBeenCalledTimes(2));
    expect(onConfigurationUpdated.mock.calls.map(([configuration]) => configuration)).toEqual(synchronized);
    expect(screen.queryByRole("button", { name: "승격 중…" })).not.toBeInTheDocument();
  });

  it("aborts every operation on unmount and never applies their stale responses", async () => {
    const refresh = deferred<Response>();
    const promotion = deferred<Response>();
    const signals: AbortSignal[] = [];
    const onConfigurationUpdated = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        signals.push(init?.signal as AbortSignal);
        if (input === "/api/v1/rag/evaluation-runs/run-completed") return refresh.promise;
        if (input === "/api/v1/rag/configurations/configuration-e5/default") return promotion.promise;
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    const view = render(
      <ComparisonPanel
        configurations={[baselineConfiguration(), savedConfiguration()]}
        initialRuns={[completedRun()]}
        onConfigurationUpdated={onConfigurationUpdated}
      />,
    );
    await user.click(screen.getByRole("button", { name: "현재 실행 새로고침" }));
    const result = screen.getByRole("article", { name: /내 E5 구성 평가 결과/ });
    await user.click(within(result).getByRole("button", { name: /운영 기본값으로 승격/ }));
    await waitFor(() => expect(signals).toHaveLength(2));
    view.unmount();
    expect(signals.every((signal) => signal.aborted)).toBe(true);
    refresh.resolve(jsonResponse(completedRun()));
    promotion.resolve(jsonResponse(savedConfiguration({ evaluation_state: "passed", is_default: true })));
    await Promise.resolve();
    expect(onConfigurationUpdated).not.toHaveBeenCalled();
  });

  it("shows exact identities and observed zero signals for retrieval-only and highlight-only failures", () => {
    const run = completedRun({
      caseResults: [
        evaluationCase({
          evaluation_case_id: "case-retrieval-only",
          query_sha256: "query-retrieval",
          expected_evidence_ids: ["evidence-retrieval"],
          recall_at_k: 0,
          reciprocal_rank: 0,
          ndcg: 0,
        }),
        evaluationCase({
          evaluation_case_id: "case-highlight-only",
          query_sha256: "query-highlight",
          expected_evidence_ids: ["evidence-highlight"],
          highlight_iou: 0,
        }),
      ],
    });

    render(
      <ComparisonPanel
        configurations={[baselineConfiguration(), savedConfiguration()]}
        initialRuns={[run]}
        onConfigurationUpdated={() => undefined}
      />,
    );

    const retrieval = screen.getByRole("link", { name: /case-retrieval-only/ }).closest("li");
    expect(retrieval).toHaveTextContent("query-retrieval");
    expect(retrieval).toHaveTextContent("evidence-retrieval");
    expect(retrieval).toHaveTextContent("Recall@K=0");
    expect(retrieval).toHaveTextContent("Reciprocal Rank=0");
    expect(retrieval).toHaveTextContent("nDCG=0");
    const highlight = screen.getByRole("link", { name: /case-highlight-only/ }).closest("li");
    expect(highlight).toHaveTextContent("query-highlight");
    expect(highlight).toHaveTextContent("evidence-highlight");
    expect(highlight).toHaveTextContent("Highlight IoU=0");
  });

  it("aborts a stale manual refresh and releases its pending control when selection changes", async () => {
    const detail = deferred<Response>();
    let refreshSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (input === "/api/v1/rag/evaluation-runs/run-completed") {
          refreshSignal = init?.signal as AbortSignal;
          return detail.promise;
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <ComparisonPanel
        configurations={[baselineConfiguration(), savedConfiguration()]}
        initialRuns={[completedRun()]}
        onConfigurationUpdated={() => undefined}
      />,
    );

    await user.click(screen.getByRole("button", { name: "현재 실행 새로고침" }));
    await waitFor(() => expect(refreshSignal).toBeDefined());
    await user.click(screen.getByRole("checkbox", { name: /내 E5 구성/ }));

    expect(refreshSignal?.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "현재 실행 새로고침" })).toBeDisabled();
    detail.resolve(jsonResponse(completedRun()));
  });

  it.each([
    [401, "로그인이 필요합니다."],
    [404, "승격할 구성을 찾을 수 없습니다."],
    [409, "정책으로 검증된 평가 통과 근거가 없어 승격할 수 없습니다."],
    [422, "승격할 구성 상태를 확인해 주세요."],
    [503, "승격 서비스를 잠시 사용할 수 없습니다."],
  ])("handles a safe %i promotion failure without exposing backend detail", async (status, message) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (input === "/api/v1/rag/configurations/configuration-e5/default") {
          return jsonResponse(
            {
              error: {
                code: "private_backend_detail",
                message: "비공개 원문과 내부 스택 정보",
                correlation_id: "correlation-1",
              },
            },
            status,
          );
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <ComparisonPanel
        configurations={[
          baselineConfiguration(),
          savedConfiguration({ evaluation_state: "passed", experimental: false }),
        ]}
        initialRuns={[completedRun()]}
        onConfigurationUpdated={() => undefined}
      />,
    );

    const result = screen.getByRole("article", { name: /내 E5 구성 평가 결과/ });
    await user.click(within(result).getByRole("button", { name: /운영 기본값으로 승격/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText(/비공개 원문|내부 스택/)).not.toBeInTheDocument();
  });
});

function baselineConfiguration(overrides: Partial<SavedConfiguration> = {}): SavedConfiguration {
  return savedConfiguration({
    id: "configuration-bm25",
    version_id: "version-bm25",
    name: "BM25 기준선",
    retrieval_profile_id: "retrieval-bm25",
    evaluation_state: "passed",
    is_system: true,
    is_default: true,
    experimental: false,
    ...overrides,
  });
}

function savedConfiguration(overrides: Partial<SavedConfiguration> = {}): SavedConfiguration {
  return {
    id: "configuration-e5",
    version_id: "version-e5",
    owner_id: "owner-1",
    name: "내 E5 구성",
    version: 2,
    indexing_profile_id: "indexing-e5",
    retrieval_profile_id: "retrieval-e5",
    generation_profile_id: null,
    answer_policy: {
      id: "policy-1",
      version: 1,
      mode: "extractive",
      min_semantic_score: 0.7,
      min_keyword_coverage: 0.5,
      require_complete_provenance: true,
      conflict_mode: "separate_sources",
    },
    workspace_ids: ["workspace-company"],
    evaluation_state: "pending",
    is_system: false,
    is_default: false,
    experimental: true,
    ...overrides,
  };
}

function pendingRun(): EvaluationRun {
  return {
    id: "run-pending",
    owner_id: "owner-1",
    dataset_snapshot_id: "11111111-1111-4111-8111-111111111111",
    evaluation_policy_version_id: null,
    status: "pending",
    fixture_sha256: "fixture",
    document_snapshot_sha256: "documents",
    query_set_sha256: "queries",
    execution_snapshot_sha256: "execution",
    runtime_environment: {},
    worker_runtime_environment: null,
    metric_definition_version: 1,
    retrieval_k: 10,
    repetition_count: 2,
    failure: null,
    candidates: [],
  };
}

function completedRun(overrides: {
  status?: EvaluationRun["status"];
  evaluation_policy_version_id?: string | null;
  candidateStatus?: EvaluationRun["candidates"][number]["status"];
  candidateVersionId?: string;
  caseResults?: EvaluationRun["candidates"][number]["case_results"];
} = {}): EvaluationRun {
  return {
    ...pendingRun(),
    id: "run-completed",
    status: overrides.status ?? "completed",
    evaluation_policy_version_id:
      overrides.evaluation_policy_version_id === undefined
        ? "policy-version-1"
        : overrides.evaluation_policy_version_id,
    candidates: [
      {
        id: "candidate-bm25",
        configuration_version_id: "version-bm25",
        ordinal: 0,
        status: "completed",
        failure: null,
        metrics: null,
        case_results: [],
      },
      {
        id: "candidate-e5",
        configuration_version_id: overrides.candidateVersionId ?? "version-e5",
        ordinal: 1,
        status: overrides.candidateStatus ?? "completed",
        failure: null,
        metrics: {
          recall_at_k: 0.81,
          mrr: 0.72,
          ndcg: 0.7,
          supported_precision: 0.91,
          false_grounding_rate: 0.03,
          highlight_iou: 0.77,
          p50_latency_ms: 18.4,
          p95_latency_ms: 41.2,
          access_leaks: 0,
          reproducibility: 1,
        },
        case_results: overrides.caseResults ?? [
          evaluationCase({
            evaluation_case_id: "case-failed",
            ordinal: 3,
            query_sha256: "query-sha",
            expected_evidence_ids: ["evidence-expected-1"],
            duration_ms: 19,
            recall_at_k: 0,
            reciprocal_rank: 0,
            ndcg: 0,
            correct_supported: false,
            false_grounding: true,
            highlight_iou: 0,
            access_leaks: 0,
            reproducible: true,
          }),
        ],
      },
    ],
  };
}

function evaluationCase(
  overrides: Partial<EvaluationRun["candidates"][number]["case_results"][number]> = {},
): EvaluationRun["candidates"][number]["case_results"][number] {
  return {
    evaluation_case_id: "case-passing",
    ordinal: 1,
    query_sha256: "query-passing",
    expected_evidence_ids: [],
    duration_ms: 10,
    recall_at_k: 1,
    reciprocal_rank: 1,
    ndcg: 1,
    correct_supported: true,
    false_grounding: false,
    highlight_iou: 1,
    access_leaks: 0,
    reproducible: true,
    raw_observations: [],
    ...overrides,
  };
}

interface EvaluationRunCreateBody {
  configuration_version_ids: string[];
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}
