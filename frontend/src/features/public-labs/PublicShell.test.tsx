import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";
import { LabEntrancePage } from "./LabEntrancePage";
import { LabWorldPage } from "./LabWorldPage";
import { RagLabOverviewPage } from "./RagLabOverviewPage";

vi.mock("../navigation/PublicNavigation", () => ({
  PublicNavigation: ({ children }: { children?: ReactNode }) => <div data-testid="public-shell"><nav aria-label="Shared public menu" />{children}</div>,
}));

it.each([
  ["entrance", <LabEntrancePage key="entrance" catalog={{ status: "ready", labs: [] }} />],
  ["directory", <LabWorldPage key="directory" catalog={{ status: "ready", labs: [] }} />],
  ["rag", <RagLabOverviewPage key="rag" />],
])("keeps %s content inside one public shell with navigation outside main", (_name, page) => {
  render(page);
  expect(screen.getByTestId("public-shell")).toContainElement(screen.getByRole("main"));
  expect(screen.getAllByRole("main")).toHaveLength(1);
  expect(screen.getByRole("main")).not.toContainElement(screen.getByRole("navigation"));
});
