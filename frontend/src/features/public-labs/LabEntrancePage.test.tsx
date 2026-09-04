import { render, screen } from "@testing-library/react";

import { LabEntrancePage } from "./LabEntrancePage";

describe("LabEntrancePage", () => {
  it("keeps the public entrance useful when no Lab managers are published", () => {
    render(<LabEntrancePage catalog={{ status: "ready", labs: [] }} />);

    expect(
      screen.getByText("현재 공개된 기술 관리자를 준비하고 있습니다"),
    ).toBeVisible();
    expect(screen.getByRole("navigation", { name: "공개 전시실" })).toBeVisible();
  });

  it("shows an honest catalog error without inventing a fallback manager", () => {
    render(<LabEntrancePage catalog={{ status: "error", labs: [] }} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "연구소 입구 정보를 불러오지 못했습니다",
    );
    expect(screen.getByRole("navigation", { name: "공개 전시실" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /에게 말 걸기/u })).not.toBeInTheDocument();
  });
});
