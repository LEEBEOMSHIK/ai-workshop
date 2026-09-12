import { render, screen } from "@testing-library/react";

import type { GameStore } from "../features/office-game/gameStore";
import { loginPath, routes } from "../shared/routing/routes";
import HomeRoute, { metadata } from "./page";

// Canvas/WebGL and real keyboard movement belong to office.e2e.ts. Keep the
// actual React host, state bridge and public navigation under test here.
vi.mock("../features/office-game/PhaserGame", () => ({
  createPhaserGame: (_parent: HTMLDivElement, store: GameStore) => {
    store.getState().setStatus("ready");
    return { destroy() {} };
  },
}));

describe("HomeRoute", () => {
  it("opens the game campus with public navigation and an optional private-workshop entry", async () => {
    render(<HomeRoute />);

    expect(
      screen.getByRole("heading", { name: /연구소에 오신 것을.*환영합니다/ }),
    ).toBeVisible();
    expect(
      screen.getByRole("region", { name: "게임형 AI 연구소" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: /AI Labs/ }),
    ).toHaveAttribute("href", routes.labs);
    expect(
      screen.getByRole("link", { name: "내 작업소" }),
    ).toHaveAttribute("href", loginPath(routes.workshopHome));
    expect(await screen.findByRole("button", { name: "이동 키가 반응하지 않으면 여기를 클릭" })).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("declares the public entrance as the canonical route", () => {
    expect(metadata.alternates?.canonical).toBe("/");
  });
});
