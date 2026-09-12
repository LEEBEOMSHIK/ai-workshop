import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Link from "next/link";
import { afterEach, vi } from "vitest";

import { LearningEditor } from "./LearningEditor";
import { emptyExperiment } from "./registry";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("LearningEditor", () => {
  it.each(["제목", "본문"])("rejects a whitespace-only %s before calling the API", async (label) => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderEditor(onSubmit);

    const field = screen.getByRole("textbox", { name: label });
    await user.clear(field);
    await user.type(field, "   ");
    await user.click(screen.getByRole("button", { name: "변경 저장" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("제목과 본문");
  });

  it("adds a named metric only after the user supplies its value", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderEditor(onSubmit);

    const add = screen.getByRole("button", { name: "지표 추가" });
    expect(add).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "새 지표 이름" }), "Recall@10");
    expect(add).toBeDisabled();
    await user.type(screen.getByRole("spinbutton", { name: "새 지표 값" }), "0.82");
    await user.type(screen.getByRole("textbox", { name: "새 지표 단위" }), "ratio");
    await user.click(add);
    await user.click(screen.getByRole("button", { name: "변경 저장" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      experiment: expect.objectContaining({ metrics: [{ name: "Recall@10", value: 0.82, unit: "ratio" }] }),
    }));

    await user.type(screen.getByRole("textbox", { name: "새 지표 이름" }), "Error count");
    await user.type(screen.getByRole("spinbutton", { name: "새 지표 값" }), "0");
    await user.click(screen.getByRole("button", { name: "지표 추가" }));
    await user.click(screen.getByRole("button", { name: "변경 저장" }));
    expect(onSubmit).toHaveBeenLastCalledWith(expect.objectContaining({
      experiment: expect.objectContaining({ metrics: expect.arrayContaining([{ name: "Error count", value: 0, unit: null }]) }),
    }));
  });

  it("uses labeled allowed references and warns before leaving a dirty editor", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    renderEditor(vi.fn().mockResolvedValue(undefined));

    expect(screen.queryByText("22222222-2222-4222-8222-222222222222")).not.toBeInTheDocument();
    expect(screen.queryByText("33333333-3333-4333-8333-333333333333")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "참조 선택" }), "learning.record\u001f22222222-2222-4222-8222-222222222222\u001f");
    await user.click(screen.getByRole("button", { name: "참조 추가" }));
    expect(within(screen.getByRole("list")).getByText("학습 기록 · 재현 가능한 검색")).toBeVisible();
    await user.type(screen.getByRole("textbox", { name: "본문" }), " 수정");
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(fireEvent.click(screen.getByRole("link", { name: "테스트 이동" }))).toBe(false);
    expect(confirm).toHaveBeenCalled();
  });

  it("keeps collection and comma input raw while typing and parses it on save", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderEditor(onSubmit);

    await user.type(screen.getByRole("textbox", { name: "비교 구성" }), "BM25{enter}Hybrid");
    await user.type(screen.getByRole("textbox", { name: "도메인 분류" }), "research, asset-management");
    await user.click(screen.getByRole("button", { name: "변경 저장" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      domain_labels: ["research", "asset-management"],
      experiment: expect.objectContaining({ configurations: ["BM25", "Hybrid"] }),
    }));
  });

  it("does not turn a cleared saved metric into a fabricated zero", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderEditor(onSubmit, {
      ...emptyExperiment(),
      metrics: [{ name: "Recall@10", value: 0.82, unit: "ratio" }],
    });

    await user.clear(screen.getByRole("spinbutton", { name: "값" }));
    await user.click(screen.getByRole("button", { name: "변경 저장" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("spinbutton", { name: "값" })).toHaveValue(null);
    expect(screen.getByRole("alert")).toHaveTextContent("지표 값");
  });

  it("keeps the second metric blank and invalid after the first metric is removed, then accepts a genuine zero", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderEditor(onSubmit, {
      ...emptyExperiment(),
      metrics: [
        { name: "Recall@10", value: 0.82, unit: "ratio" },
        { name: "Error count", value: 3, unit: null },
      ],
    });

    await user.clear(screen.getAllByRole("spinbutton", { name: "값" })[1]);
    await user.click(screen.getAllByRole("button", { name: "지표 삭제" })[0]);
    expect(screen.getByRole("spinbutton", { name: "값" })).toHaveValue(null);
    expect(screen.getByRole("textbox", { name: "지표 이름" })).toHaveValue("Error count");
    await user.click(screen.getByRole("button", { name: "변경 저장" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("지표 값");

    await user.type(screen.getByRole("spinbutton", { name: "값" }), "0");
    await user.click(screen.getByRole("button", { name: "변경 저장" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      experiment: expect.objectContaining({ metrics: [{ name: "Error count", value: 0, unit: null }] }),
    }));
  });

  it("keeps unload, link, and back warnings active during save and releases them only before successful navigation", async () => {
    const saved = deferred<void>();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const historyGo = vi.spyOn(window.history, "go").mockImplementation(() => undefined);
    let successNavigationPrevented: boolean | null = null;
    const user = userEvent.setup();
    render(
      <>
        <Link href="/workshop/learning">테스트 이동</Link>
        <LearningEditor
          initialDraft={{ title: "메모", body: "본문", kind: "note", topic_keys: [], domain_labels: [], experiment: null, references: [] }}
          topics={[]}
          learningRecords={[]}
          evaluations={[]}
          submitLabel="변경 저장"
          onSubmit={() => saved.promise}
          onSaved={() => {
            const event = new Event("beforeunload", { cancelable: true });
            window.dispatchEvent(event);
            successNavigationPrevented = event.defaultPrevented;
          }}
        />
      </>,
    );

    await user.type(screen.getByRole("textbox", { name: "본문" }), " 수정");
    await user.click(screen.getByRole("button", { name: "변경 저장" }));
    const reload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(reload);
    expect(reload.defaultPrevented).toBe(true);
    expect(fireEvent.click(screen.getByRole("link", { name: "테스트 이동" }))).toBe(false);
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(historyGo).toHaveBeenCalledWith(1);
    expect(confirm).toHaveBeenCalledTimes(2);

    await act(async () => saved.resolve());
    await waitFor(() => expect(successNavigationPrevented).toBe(false));
  });

  it("renders only API-verified available reference hrefs as links", () => {
    render(
      <LearningEditor
        initialDraft={{ title: "메모", body: "본문", kind: "note", topic_keys: [], domain_labels: [], experiment: null, references: [
          { kind: "service", target: "rag.search", version: null },
          { kind: "rag.evaluation", target: "33333333-3333-4333-8333-333333333333", version: null },
        ] }}
        topics={[]}
        learningRecords={[]}
        evaluations={[]}
        referenceViews={[
          { status: "available", label: "RAG 검색", href: "/workshop/rag/search", key: { kind: "service", target: "rag.search", version: null } },
          { status: "available", label: "평가 완료", href: null, key: { kind: "rag.evaluation", target: "33333333-3333-4333-8333-333333333333", version: null } },
        ]}
        disabled
        submitLabel=""
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByRole("link", { name: "RAG 검색" })).toHaveAttribute("href", "/workshop/rag/search");
    expect(screen.getByText("평가 완료").closest("a")).toBeNull();
  });

  it("labels evaluation references with persisted Korean dates and adds helper numbers only for visible collisions", () => {
    const firstDate = "2019-03-04T05:06:07Z";
    const secondDate = "2020-04-05T06:07:08Z";
    const collidingDate = "2019-03-04T05:06:30Z";
    render(
      <LearningEditor
        initialDraft={{ title: "메모", body: "본문", kind: "note", topic_keys: [], domain_labels: [], experiment: null, references: [] }}
        topics={[]}
        learningRecords={[]}
        evaluations={[
          evaluationRun("11111111-1111-4111-8111-111111111111", firstDate),
          evaluationRun("22222222-2222-4222-8222-222222222222", secondDate),
          evaluationRun("33333333-3333-4333-8333-333333333333", collidingDate),
        ]}
        submitLabel="저장"
        onSubmit={vi.fn()}
      />,
    );

    const picker = screen.getByRole("combobox", { name: "참조 선택" });
    const firstLabel = `RAG 평가 · 완료 · ${formatEvaluationDate(firstDate)}`;
    expect(within(picker).getByRole("option", { name: `${firstLabel} · 1` })).toBeVisible();
    expect(within(picker).getByRole("option", { name: `RAG 평가 · 완료 · ${formatEvaluationDate(secondDate)}` })).toBeVisible();
    expect(within(picker).getByRole("option", { name: `${firstLabel} · 2` })).toBeVisible();
    expect(picker).not.toHaveTextContent("11111111-1111-4111-8111-111111111111");
  });
});

function renderEditor(onSubmit: (value: unknown) => Promise<void>, experiment = emptyExperiment()) {
  render(
    <>
      <Link href="/workshop/learning">테스트 이동</Link>
      <LearningEditor
        initialDraft={{ title: "실험", body: "본문", kind: "experiment", topic_keys: ["rag"], domain_labels: [], experiment, references: [] }}
        topics={[{ key: "rag", label: "RAG" }]}
        learningRecords={[{ id: "22222222-2222-4222-8222-222222222222", revision: 1, created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z", archived_at: null, title: "재현 가능한 검색", kind: "note", topic_keys: ["rag"] }]}
        evaluations={[{ id: "33333333-3333-4333-8333-333333333333", owner_id: "44444444-4444-4444-8444-444444444444", created_at: "2019-03-04T05:06:07Z", status: "completed", dataset_snapshot_id: "55555555-5555-4555-8555-555555555555", document_snapshot_sha256: "a".repeat(64), execution_snapshot_sha256: "b".repeat(64), fixture_sha256: "c".repeat(64), query_set_sha256: "d".repeat(64), evaluation_policy_version_id: null, metric_definition_version: 1, repetition_count: 2, retrieval_k: 10, runtime_environment: {}, worker_runtime_environment: null, failure: null, candidates: [] }]}
        submitLabel="변경 저장"
        onSubmit={onSubmit}
      />
    </>,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function evaluationRun(id: string, createdAt: string) {
  return { id, owner_id: "44444444-4444-4444-8444-444444444444", created_at: createdAt, status: "completed" as const, dataset_snapshot_id: "55555555-5555-4555-8555-555555555555", document_snapshot_sha256: "a".repeat(64), execution_snapshot_sha256: "b".repeat(64), fixture_sha256: "c".repeat(64), query_set_sha256: "d".repeat(64), evaluation_policy_version_id: null, metric_definition_version: 1 as const, repetition_count: 2, retrieval_k: 10, runtime_environment: {}, worker_runtime_environment: null, failure: null, candidates: [] };
}

function formatEvaluationDate(value: string): string {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
