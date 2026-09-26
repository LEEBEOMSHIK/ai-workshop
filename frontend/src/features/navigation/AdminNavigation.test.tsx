import { render, screen, within } from "@testing-library/react";

import { routes } from "../../shared/routing/routes";
import { AdminNavigation } from "./AdminNavigation";

describe("AdminNavigation", () => {
  it("links administration and the private workshop to canonical routes", () => {
    render(
      <AdminNavigation
        user={{
          id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
          display_name: "Owner",
          email: "owner@example.com",
          role: "owner",
        }}
      />,
    );

    expect(within(screen.getByRole("navigation", { name: "관리자 운영" })).getAllByRole("link")).toHaveLength(7);
    expect(screen.getByRole("link", { name: "문제 및 개선 이력" })).toHaveAttribute("href", "/admin/system/issues");
    expect(within(screen.getByRole("navigation", { name: "영역 이동" })).getByRole("link", { name: "비공개 작업소" })).toHaveAttribute("href", routes.workshopHome);
    expect(screen.getByRole("link", { name: "RAG 구성" })).toHaveAttribute(
      "href",
      routes.adminRagConfigurations,
    );
    expect(screen.getByRole("link", { name: "RAG 도메인" })).toHaveAttribute(
      "href",
      routes.adminRagDomains,
    );
    expect(screen.getByRole("link", { name: "RAG 모델" })).toHaveAttribute(
      "href",
      routes.adminRagModels,
    );
    expect(screen.getByRole("link", { name: "공개 연구 관리" })).toHaveAttribute(
      "href",
      routes.adminPublishing,
    );
    expect(screen.getByRole("link", { name: "런타임" })).toHaveAttribute(
      "href",
      routes.adminSystemRuntime,
    );
    expect(screen.getByRole("link", { name: "비공개 작업소" })).toHaveAttribute(
      "href",
      routes.workshopHome,
    );
  });
});
