import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AnswerComparisonView } from "./AnswerComparisonView";

afterEach(cleanup);

function compare(before: string, after: string, expected?: string, notes = "") {
  render(<AnswerComparisonView comparison={{
    question: "근거는 무엇인가요?", before, after, expected, notes,
  }} />);
}

function card(name: "학습 전" | "학습 후" | "학습 정답") {
  return screen.getByRole("article", { name });
}

describe("answer comparison dashboard", () => {
  it("preserves both literal answers and separates identical output from missing citations", () => {
    compare("3영업일 후 지급합니다.", "3영업일 후 지급합니다.", "3영업일 뒤 지급합니다. [e1]");
    expect(card("학습 정답")).toHaveTextContent("3영업일 뒤 지급합니다. [e1]");
    for (const name of ["학습 전", "학습 후"] as const) {
      expect(card(name)).toHaveTextContent("3영업일 후 지급합니다.");
      expect(card(name)).toHaveTextContent("[e1]");
      expect(card(name)).toHaveTextContent("누락");
      expect(card(name)).toHaveTextContent("미평가");
      expect(card(name)).not.toHaveTextContent("오답");
    }
    const summary = within(screen.getByRole("group", { name: "결과 요약" }));
    expect(summary.getByText("답변 변화 없음")).toBeVisible();
    expect(summary.getByText("[e1] 전후 모두 누락")).toBeVisible();
    expect(screen.queryByRole("complementary", { name: "변화 요약" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "인용 변화" })).not.toBeInTheDocument();
  });

  it("distinguishes e10 from e1 when the new answer supplies only part of the reference", () => {
    compare("근거 없음", "문장 [e10]", "문장 [e1] [e10]");
    expect(card("학습 후")).toHaveTextContent("문장 [e10]");
    expect(card("학습 후")).toHaveTextContent("[e1]");
    expect(card("학습 후")).toHaveTextContent("누락");
  });

  it("separates citation recovery from semantic improvement", () => {
    compare("이전 답", "새 답 [e1]", "참고 답 [e1]");
    expect(card("학습 전")).toHaveTextContent("누락");
    expect(card("학습 후")).not.toHaveTextContent("누락");
    expect(card("학습 후")).toHaveTextContent("미평가");
  });

  it("preserves a wrong answer with grouped references without mislabelling those references as missing", () => {
    const answer = "11월 3일입니다 [e1, e2].";
    compare(answer, answer, "11월 6일입니다 [e1] [e2]",
      "학습 전 의미 평가: 오답\n학습 후 의미 평가: 오답");
    for (const name of ["학습 전", "학습 후"] as const) {
      expect(card(name)).toHaveTextContent(answer);
      expect(card(name)).toHaveTextContent("의미 평가 · 오답");
      expect(card(name)).toHaveTextContent("포함된 번호 [e1] [e2]");
      expect(card(name)).not.toHaveTextContent("누락");
    }
    expect(screen.getByRole("group", { name: "결과 요약" })).toHaveTextContent("답변 변화 없음");
    expect(screen.getByRole("group", { name: "결과 요약" })).not.toHaveTextContent("누락");
  });

  it("puts mixed changes next to the new answer, including IDs missing both times", () => {
    compare("첫 답 [e1]", "새 답 [e2]", "참고 답 [e1] [e2] [e3]");
    const delta = within(card("학습 후")).getByRole("group", { name: "인용 변화" });
    expect(delta).toHaveTextContent("[e2] 새로 포함");
    expect(delta).toHaveTextContent("[e1] 학습 후 누락");
    expect(delta).toHaveTextContent("[e3] 계속 누락");
    expect(within(card("학습 전")).queryByRole("group", { name: "인용 변화" })).toBeNull();
  });

  it("shows an explicitly evaluated decline without losing a very long answer", () => {
    const after = "한글로길게기록한답변".repeat(300);
    compare("맞는 답 [e3]", after, "맞는 답 [e3]",
      "학습 전 의미 평가: 정확\n학습 후 의미 평가: 오답");
    expect(card("학습 전")).toHaveTextContent("정확");
    expect(card("학습 후")).toHaveTextContent("오답");
    expect(card("학습 후")).toHaveTextContent(after);
    expect(card("학습 후")).toHaveTextContent("누락");
  });

  it.each([undefined, "인용 번호 없는 정답"])("does not infer failure without a comparison target citation (%s)", expected => {
    compare("첫 답", "다음 답", expected);
    expect(card("학습 후")).toHaveTextContent("미평가");
    expect(card("학습 후")).not.toHaveTextContent("누락");
    expect(card("학습 후")).not.toHaveTextContent("오답");
  });
});
