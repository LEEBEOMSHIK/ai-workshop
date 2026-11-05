import { render, screen } from "@testing-library/react";

import { RecordBody } from "./RecordBody";

describe("RecordBody", () => {
  it("renders hostile HTML and Markdown as plain text without active nodes", () => {
    const body = '<script>alert(1)</script> <a href="https://invalid.test">link</a> ![x](https://invalid.test/x)';
    const { container } = render(<RecordBody body={body} />);

    expect(screen.getByText(body)).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
  });

  it("groups consecutive numbered lines without dropping their spelling, spacing or surrounding text", () => {
    const body = "앞 문단\r\n\r\n03)  종이 접기\r\n04)\t모서리 맞추기\r\n\r\n뒤 문단\n1. 한 줄만\n3. 번호 건너뜀\n";
    const { container } = render(<RecordBody body={body} />);
    const list = screen.getByRole("list");
    expect(list.tagName).toBe("OL");
    expect(list).toHaveAttribute("start", "3");
    expect(screen.getAllByRole("listitem").map(item => item.textContent)).toEqual(["03)  종이 접기\r\n", "04)\t모서리 맞추기\r\n"]);
    expect(container.textContent).toBe(body);
  });

  it("marks explicit example paragraphs and leaves similar wording and code verbatim", () => {
    const body = [
      "여기에는 예시: 라는 말이 들어갑니다.", "예시(접는 법): 펼쳐 둡니다.", "다음 줄도 같은 예시입니다.", "",
      "예시: 다른 예시", "", "    1. 들여쓴 코드", "    2. 다음 줄", "    예시: 그대로",
      "````text", "```", "1. 코드", "2. 코드", "예시: 코드", "````", "~~~", "예시: 코드", "~~~",
      "1. 첫 단계", "2. 두 번째 단계",
    ].join("\n");
    const { container } = render(<RecordBody body={body} />);
    const examples = Array.from(container.querySelectorAll("p > strong"));
    expect(examples.map(label => label.textContent)).toEqual(["예시(접는 법):", "예시:"]);
    expect(examples[0].parentElement).toHaveTextContent("다음 줄도 같은 예시입니다.");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(container.textContent).toBe(body);
  });

  it("emphasizes the three training labels while preserving the authored text and ordinary lists", () => {
    const steps = ["1. 입력 — 질문을 넣는다.", "2. 정답 — 예시 답을 준다.", "3. 학습 — 오차를 계산한다."];
    const body = [...steps, "", "1. 입력 자료를 정리한다.", "2. 학습 결과를 읽는다.", "",
      "```text", ...steps, "```"].join("\r\n");
    const { container } = render(<RecordBody body={body} />);

    const [training, ordinary] = screen.getAllByRole("list");
    expect(Array.from(training.querySelectorAll("li strong"), element => element.textContent))
      .toEqual(["입력", "정답", "학습"]);
    expect(ordinary.querySelector("strong")).toBeNull();
    expect(container.querySelectorAll("strong")).toHaveLength(3);
    expect(container.textContent).toBe(body);
  });
});
