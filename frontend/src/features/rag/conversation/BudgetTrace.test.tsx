import { render, screen } from "@testing-library/react";
import type { components } from "../../../shared/api/schema";
import { BudgetTrace } from "./BudgetTrace";

const accepted: NonNullable<components["schemas"]["CandidateDiagnosticResponse"]["budget_trace"]> = {
  incoming_units: 4, incoming_characters: 100, before_groups: 0, before_units: 0,
  before_characters: 0, group_limit: 8, unit_limit: 32, character_limit: 12000, violated: [],
};

it("leaves accepted candidates concise when no constraint was exceeded", () => {
  const { container } = render(<BudgetTrace trace={accepted} reason="selected" />);
  expect(container).toBeEmptyDOMElement();
});

it("distinguishes final conflict cancellation from the successful admission check", () => {
  render(<BudgetTrace trace={accepted} reason="conflict_context_budget_exceeded" />);
  expect(screen.getByText("선택 검사 후 상충 근거 보존을 위해 전달 취소")).toBeVisible();
  expect(screen.queryByText(/전체 한도/)).not.toBeInTheDocument();
  expect(screen.queryByText(/예산 미기록/)).not.toBeInTheDocument();
});

it("does not reconstruct absent historical counts from current configuration", () => {
  render(<BudgetTrace reason="budget_exceeded" />);
  expect(screen.getByText("세부 예산 미기록")).toBeVisible();
  expect(screen.queryByText(/남은|전체 한도/)).not.toBeInTheDocument();
});

it("does not claim an unchecked candidate passed the budget", () => {
  render(<BudgetTrace trace={null} reason="below_threshold" />);
  expect(screen.getByText("예산 검사 전 제외")).toBeVisible();
  expect(screen.queryByText(/남은|전체 한도/)).not.toBeInTheDocument();
});

it("uses captured character counts rather than treating them as tokens or serialized bytes", () => {
  render(<BudgetTrace reason="budget_exceeded" trace={{ ...accepted,
    incoming_characters: 12001, violated: ["characters"],
  }} />);
  expect(screen.getByText("문자 12001자 / 남은 12000자 (전체 한도 12000자)")).toBeVisible();
  expect(screen.queryByText(/토큰|bytes|원문 단위/)).not.toBeInTheDocument();
});
