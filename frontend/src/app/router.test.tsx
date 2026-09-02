import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routes } from "./router";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function installUnauthenticatedApi(setupRequired: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/auth/me") {
        return jsonResponse(
          {
            error: {
              code: "not_authenticated",
              message: "Authentication is required.",
              correlation_id: "test",
            },
          },
          401,
        );
      }
      if (path === "/api/v1/setup/status") {
        return jsonResponse({ setup_required: setupRequired });
      }
      throw new Error(`Unexpected request: ${path}`);
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("application access routing", () => {
  it("sends an uninitialized protected route to first setup", async () => {
    installUnauthenticatedApi(true);
    const router = createMemoryRouter(routes, { initialEntries: ["/rag/search"] });

    render(<RouterProvider router={router} />);

    expect(
      await screen.findByRole("heading", { name: "첫 관리자를 만듭니다." }),
    ).toBeVisible();
    expect(router.state.location.pathname).toBe("/setup");
  });

  it("sends an initialized protected route to login", async () => {
    installUnauthenticatedApi(false);
    const router = createMemoryRouter(routes, { initialEntries: ["/rag/search"] });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "다시 오셨군요." })).toBeVisible();
    expect(router.state.location.pathname).toBe("/login");
  });
});
