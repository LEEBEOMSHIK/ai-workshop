import { describe, expect, it } from "vitest";

import { RouteError } from "../../../shared/ui/RouteError";
import WorkshopRouteError from "./error";

describe("WorkshopRouteError", () => {
  it("default exports the shared RouteError adapter", () => {
    expect(WorkshopRouteError).toBe(RouteError);
  });
});
