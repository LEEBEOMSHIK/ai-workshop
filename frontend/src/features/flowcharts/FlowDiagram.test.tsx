import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { FlowDiagram } from "./FlowDiagram";
import { projectAgentFlows } from "../project-agents/flows";
import { ragFlows } from "../rag/flows/catalog";

afterEach(cleanup);

function DiagramHarness() {
  const [selectedNodeId, select] = useState("request");
  return <FlowDiagram flow={projectAgentFlows[0]} selectedNodeId={selectedNodeId} onSelectNode={select} />;
}

it("labels conditional branches and follows a review loop to its exact target", async () => {
  const user = userEvent.setup();
  render(<DiagramHarness />);
  await user.click(screen.getByRole("button", { name: "결함 수정·재검증 → 구현·검증 증거 인계" }));
  expect(screen.getByRole("button", { name: "구현·검증 증거 인계 단계" })).toHaveAttribute("aria-pressed", "true");
  await user.click(screen.getByRole("button", { name: "범위 확장·역할 재선정 → 필수 역할·전문 역할 선정" }));
  expect(screen.getByRole("button", { name: "필수 역할·전문 역할 선정 단계" })).toHaveAttribute("aria-pressed", "true");
});

it("keeps distinct result paths and long conditional labels readable", () => {
  render(<FlowDiagram flow={ragFlows[1]} selectedNodeId="request" onSelectNode={() => {}} />);
  expect(screen.getByRole("button", { name: "답변·근거 표시 단계" })).toBeVisible();
  expect(screen.getByRole("button", { name: "근거 부족 단계" })).toBeVisible();
  expect(screen.getByRole("button", { name: "거절·실패·취소 단계" })).toBeVisible();
  expect(screen.getByRole("button", { name: "이전 대화 없음·문맥화 생략 → 권한 선필터·하이브리드 검색" })).toBeVisible();
});
