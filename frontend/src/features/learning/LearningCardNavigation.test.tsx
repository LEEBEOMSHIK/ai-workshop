import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { learningRecordPath } from "../../shared/routing/routes";
import type { LearningSummary } from "./api";
import { LearningSequenceList } from "./LearningSequence";

afterEach(cleanup);

describe("learning card navigation", () => {
  it.each(["note", "completed", "planned"] as const)("opens %s records from non-title content with one named keyboard link", async (kind) => {
    const record: LearningSummary = {
      id: "synthetic-card", title: "합성 기록", kind: kind === "note" ? "note" : "experiment",
      topic_keys: ["rag"], revision: 1, created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z", archived_at: null,
      experiment_status: kind === "note" ? null : kind, learning_sequence: null,
    };
    const user = userEvent.setup();
    render(<LearningSequenceList records={[record]} topics={[{ key: "rag", label: "RAG" }]} ordered />);
    const link = screen.getByRole("link", { name: record.title });
    expect(link).toHaveAttribute("href", learningRecordPath(record.id));
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(within(link).getByRole("group", { name: "기술 주제" })).toBeVisible();
    expect(within(link).getByText(/^수정 /)).toBeVisible();
    expect(link.querySelector("a, button, input, select, [tabindex]")).toBeNull();
    const activated = vi.fn((event: Event) => event.preventDefault());
    link.addEventListener("click", activated);
    await user.click(within(link).getByText("RAG"));
    expect(activated).toHaveBeenCalledTimes(1);
    await user.tab({ shift: true });
    await user.tab();
    expect(link).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(activated).toHaveBeenCalledTimes(2);
  });
});
