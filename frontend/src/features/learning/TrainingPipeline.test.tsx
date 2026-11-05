import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TrainingPipeline } from "./TrainingPipeline";

afterEach(cleanup);

describe("training pipeline", () => {
  const question = "점검 기한은 언제인가요?";
  const expected = "점검 요청 후 7일 이내입니다. [e8]";
  const body = [
    `1. 입력 — 공개 예제 2개 중 점검 예제 1개를 골랐다. “점검 기한은 요청 후 7일이다.”라는 규정과 “${question}”라는 질문을 함께 입력했다.`,
    `2. 정답 — “${expected}”를 정답으로 주었다. [e8]은 위 점검 규정을 가리킨다.`,
    "3. 학습 — 모델이 정답 문장을 차례로 예측하도록 했다. 정답 부분에서만 예측 오차를 계산하고, 원본 모델은 고정한 채 추가한 가중치(LoRA 어댑터)만 두 번 갱신했다.",
  ].join("\r\n");

  it("exposes the source-specific rule, question, cited target and steps in reading order", () => {
    const { container } = render(<TrainingPipeline body={body} comparison={{ question, expected }} />);
    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings.map(h => h.textContent)).toEqual(["입력", "정답", "학습"]);
    const [input, target, training] = headings.map(h => h.closest("li")!);
    expect(input).toHaveTextContent(question);
    expect(input).toHaveTextContent("점검 기한은 요청 후 7일이다.");
    expect(target).toHaveTextContent("점검 요청 후 7일 이내입니다.");
    expect(target).toHaveTextContent("[e8]");
    expect(training).toHaveTextContent(/LoRA/i);
    expect(training).not.toHaveTextContent("1회");
    expect(container).not.toHaveTextContent("[e1]");
    expect(container).not.toHaveTextContent("3영업일");
    expect(target.querySelector("a")).toBeNull();

    const disclosure = container.querySelector("details")!;
    expect(disclosure).not.toHaveAttribute("open");
    fireEvent.click(disclosure.querySelector("summary")!);
    expect(disclosure).toHaveAttribute("open");
    expect(disclosure.textContent).toContain(body);
  });

  it("preserves unstructured notes without inventing training stages or inferred values", () => {
    const note = "간단한 시행 기록\n검토 중이며 정답과 학습 조건은 미정이다.";
    const { container } = render(<TrainingPipeline body={note} comparison={{ question }} />);
    expect(container.textContent).toContain(note);
    expect(container).not.toHaveTextContent("STEP 01");
    expect(container).not.toHaveTextContent("LoRA");
    expect(container.querySelector("details")).toBeNull();
  });
});
