import { render, screen } from "@testing-library/react";

import { PublicNavigation } from "./PublicNavigation";

describe("PublicNavigation", () => {
  it("links public visitors to the Labs and private workshop entry", () => {
    render(<PublicNavigation />);

    expect(screen.getByRole("link", { name: "AI Workshop" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByRole("link", { name: "AI Labs" })).toHaveAttribute(
      "href",
      "/labs",
    );
    expect(screen.getByRole("link", { name: "비공개 작업소 입장" })).toHaveAttribute(
      "href",
      "/login?next=%2Fworkshop%2Fworkspaces",
    );
  });
});
