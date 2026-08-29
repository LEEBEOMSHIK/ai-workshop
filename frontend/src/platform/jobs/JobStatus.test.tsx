import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { JobStatus } from "./JobStatus";

describe("JobStatus", () => {
  it("refreshes a queued job to its latest durable status", async () => {
    const user = userEvent.setup();
    render(
      <JobStatus
        jobId="job-1"
        initialStatus="queued"
        loadJob={async () => ({
          id: "job-1",
          type: "verify_asset",
          status: "succeeded",
          stage: "stored",
          attempt: 1,
          error_code: null,
          error_message: null,
          started_at: "2026-08-29T01:00:00Z",
          finished_at: "2026-08-29T01:01:00Z",
        })}
      />,
    );

    expect(screen.getByText("대기 중")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "상태 새로고침" }));

    expect(await screen.findByText("완료")).toBeVisible();
    expect(screen.getByText("저장 확인 완료")).toBeVisible();
  });
});
