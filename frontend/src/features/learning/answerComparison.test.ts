import { describe, expect, it } from "vitest";

import { readAnswerComparison } from "./answerComparison";

describe("stored answer comparisons", () => {
  const observations = [
    "같은 질문의 실제 답변 비교",
    "질문  어느 문장에 근거하나요?",
    "학습 전(원본)  첫 번째 답변",
    "학습 후(어댑터 적용)  두 번째 답변",
    "",
    "추가 관찰",
  ].join("\r\n");

  it.each(["학습 정답: ", "학습에 사용한 정답  "])("recovers the recorded target from an older %s body line", label => {
    expect(readAnswerComparison(observations, `질문 원문\n${label}예문 [e1]\n별도 메모`)).toEqual({
      question: "어느 문장에 근거하나요?", expected: "예문 [e1]",
      before: "첫 번째 답변", after: "두 번째 답변", notes: "추가 관찰",
    });
  });

  it("leaves an incomplete comparison in the ordinary observation view", () => {
    expect(readAnswerComparison(observations.replace("학습 후(어댑터 적용)  두 번째 답변", ""))).toBeNull();
  });
});
