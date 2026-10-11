import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CalculationProofReview } from "./CalculationProofReview";

const operand = { evidence_id: "e1", document_id: "d1", asset_version_id: "v1", projection_id: "p1", chunk_id: "c1", element_id: "el1", token_start: 2, token_end: 7, char_start: 12, char_end: 17, page: 3, unit: "%" as const };
const proof = { operation: "percentage_point_difference" as const, result_start: 5, result_end: 11, operands: [operand, { ...operand, evidence_id: "e2", token_start: 9, token_end: 14, char_start: 19, char_end: 24 }], policy_ref: "source-numeric-proof-v1" as const };
const sources = [{ evidence_id: "e1", document_id: "d1", asset_version_id: "v1", projection_id: "p1", title: "공개 합성 자료", page: 3 }];

describe("CalculationProofReview", () => {
  it("opens a compact review and uses Unicode code-point offsets", async () => {
    render(<CalculationProofReview claimText={"😀 차이 0.10%p\n다음"} calculations={[proof]} sources={sources} />);
    const details = screen.getByText("계산 근거").closest("details")!;
    expect(details).not.toHaveAttribute("open");
    await userEvent.click(screen.getByText("계산 근거"));
    expect(details).toHaveAttribute("open");
    expect(screen.getByText("퍼센트포인트 차이 · 결과 0.10%p")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /공개 합성 자료/ })).toHaveAttribute("href", expect.stringContaining("v1"));
    expect(screen.getByText(/피연산자 2.*현재 원문 접근 불가/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("계산 근거"));
    expect(details).not.toHaveAttribute("open");
  });
  it("does not invent arithmetic proof for legacy or empty claims", () => {
    const view = render(<CalculationProofReview claimText="old" calculations={null} sources={[]} />);
    expect(screen.getByText("계산 근거 미기록")).toBeInTheDocument();
    expect(screen.queryByText("계산 근거")).not.toBeInTheDocument();
    view.rerender(<CalculationProofReview claimText="direct" calculations={[]} sources={[]} />);
    expect(screen.getByText("이 주장에는 계산이 없습니다.")).toBeInTheDocument();
  });
  it("never links an operand whose source identity differs", () => {
    render(<CalculationProofReview claimText="😀 차이 0.10%p" calculations={[proof]} sources={[{ ...sources[0], asset_version_id: "other" }]} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
