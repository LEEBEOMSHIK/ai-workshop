import { render, screen } from "@testing-library/react";

import { ragDomainChatPath, ragDomainFilesPath } from "../../../shared/routing/routes";
import { DomainNavigation } from "./DomainNavigation";

it("keeps file and chat navigation inside the current domain", () => {
  render(<DomainNavigation slug="asset/manage" displayName="자산운용" current="files" />);

  expect(screen.getByText("자산운용")).toBeVisible();
  expect(screen.getByRole("link", { name: "파일함" })).toHaveAttribute("href", ragDomainFilesPath("asset/manage"));
  expect(screen.getByRole("link", { name: "대화" })).toHaveAttribute("href", ragDomainChatPath("asset/manage"));
  expect(screen.getByRole("link", { name: "파일함" })).toHaveAttribute("aria-current", "page");
});
