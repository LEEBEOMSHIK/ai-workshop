import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "./router";

describe("AI Workshop application shell", () => {
  it("shows the workshop heading on the home route", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });

    render(<RouterProvider router={router} />);

    expect(
      await screen.findByRole("heading", { name: "AI Workshop" }),
    ).toBeVisible();
  });
});
