import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import {
  ServerRouteFailure,
  captureServerRoute,
  toServerRouteFailure,
} from "./ServerRouteFailure";

const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

describe("ServerRouteFailure", () => {
  it("keeps the captured FastAPI failure serializable and offers a retry", async () => {
    const error = new ApiError(
      "Upstream unavailable",
      503,
      "request_failed",
      "correlation-503",
    );
    const result = await captureServerRoute(async () => {
      throw error;
    });
    expect(result).toEqual({
      ok: false,
      failure: toServerRouteFailure(error),
    });
    if (result.ok) throw new Error("Expected a captured route failure.");
    const failure = result.failure;
    const serialized = JSON.parse(JSON.stringify(failure)) as typeof failure;

    render(<ServerRouteFailure failure={serialized} />);

    expect(screen.getByRole("alert")).toHaveAttribute("data-upstream-status", "503");
    expect(screen.getByText("오류 참조: correlation-503")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(refresh).toHaveBeenCalledOnce();
  });
});
