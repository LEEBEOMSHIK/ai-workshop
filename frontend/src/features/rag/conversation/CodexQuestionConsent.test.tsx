import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { CodexQuestionConsent } from "./CodexQuestionConsent";

it("keeps classification and explicit consent visible while collapsing detailed guidance", () => {
  const onConsent = vi.fn();
  render(<CodexQuestionConsent classification="synthetic" consented={false} disabled={false} onClassification={vi.fn()} onConsent={onConsent} />);
  expect(screen.getByLabelText("이번 질문과 전송 이력의 분류")).toBeVisible();
  const checkbox = screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" });
  expect(checkbox).not.toBeChecked();
  const detail = screen.getByText("외부 처리 안내").closest("details");
  expect(detail).not.toHaveAttribute("open");
  expect(screen.getByText(/현재 질문과 이번 요청에 포함될 이전 대화/)).not.toBeVisible();
  fireEvent.click(checkbox);
  expect(onConsent).toHaveBeenCalledWith(true);
});
