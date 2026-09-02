import { render, screen } from "@testing-library/react";

import LabsRoute from "./page";

describe("LabsRoute", () => {
  it("renders the public Lab scene synchronously without authentication setup", () => {
    render(LabsRoute());

    expect(screen.getByRole("heading", { name: "AI Lab" })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }),
    ).toBeVisible();
  });
});
