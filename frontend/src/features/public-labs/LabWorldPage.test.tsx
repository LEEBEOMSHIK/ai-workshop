import { render, screen } from "@testing-library/react";

import { listPublicLabs } from "./catalog";
import { LabWorldPage } from "./LabWorldPage";

describe("LabWorldPage", () => {
  it("renders one working station for each validated public Lab", () => {
    render(<LabWorldPage labs={listPublicLabs()} />);

    expect(screen.getByRole("heading", { name: "AI Lab" })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }),
    ).toBeVisible();
    expect(screen.getByText("RAG 기술 연구실")).toBeVisible();
    expect(screen.getByText("연구 중")).toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });
});
