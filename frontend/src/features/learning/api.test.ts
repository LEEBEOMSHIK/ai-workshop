import { afterEach, vi } from "vitest";

import {
  archiveRecord,
  createRecord,
  getRecord,
  getRevision,
  listEvaluationOptions,
  listRecords,
  listTopics,
  restoreRecord,
  updateRecord,
  type LearningDraft,
} from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("learning API adapter", () => {
  it("encodes list filters and cursor without leaking them into the path", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ items: [], next_cursor: null }));
    vi.stubGlobal("fetch", fetch);

    await listRecords({ topicKey: "rag & ml", kind: "experiment", archived: true, cursor: "next/page", limit: 12 });

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/learning/records?topic_key=rag+%26+ml&kind=experiment&archived=true&cursor=next%2Fpage&limit=12",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("sends typed draft and revision requests to their exact endpoints", async () => {
    const fetch = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/topics") || String(input).includes("evaluation-runs")) {
        return jsonResponse([]);
      }
      return jsonResponse(recordResponse());
    });
    vi.stubGlobal("fetch", fetch);
    const draft = noteDraft();

    await createRecord(draft);
    await getRecord("record/id");
    await getRevision("record/id", 2);
    await updateRecord("record/id", 2, draft);
    await archiveRecord("record/id", 3);
    await restoreRecord("record/id", 4);
    await listTopics();
    await listEvaluationOptions();

    expect(fetch.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/learning/records",
      "/api/v1/learning/records/record%2Fid",
      "/api/v1/learning/records/record%2Fid/revisions/2",
      "/api/v1/learning/records/record%2Fid",
      "/api/v1/learning/records/record%2Fid/archive",
      "/api/v1/learning/records/record%2Fid/restore",
      "/api/v1/learning/topics",
      "/api/v1/rag/evaluation-runs?limit=20",
    ]);
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual(draft);
    expect(JSON.parse(String(fetch.mock.calls[3]?.[1]?.body))).toEqual({ expected_revision: 2, draft });
    expect(JSON.parse(String(fetch.mock.calls[4]?.[1]?.body))).toEqual({ expected_revision: 3 });
  });
});

function noteDraft(): LearningDraft {
  return {
    title: "청킹 메모",
    body: "구조 경계를 유지한다.",
    kind: "note",
    topic_keys: ["rag"],
    domain_labels: [],
    experiment: null,
    references: [],
  };
}

function recordResponse() {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    revision: 1,
    created_at: "2026-09-07T01:02:03Z",
    updated_at: "2026-09-07T01:02:03Z",
    archived_at: null,
    draft: noteDraft(),
    reference_views: [],
    dataset_reference_view: null,
    unavailable_reference_count: 0,
  };
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { "content-type": "application/json" } });
}
