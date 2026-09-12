import { render, screen, within } from "@testing-library/react";

import { StudyBody } from "./StudyBody";
import { studySnapshot } from "./test-fixtures";

describe("StudyBody", () => {
  it("distinguishes explicit legacy subsection labels from their escaped body text", () => {
    render(<StudyBody snapshot={studySnapshot({ body: '초기 문제\r\n본문 첫 줄\r\n둘째 줄\r\n\r\n분리한 판단\n<img src=x onerror="alert(1)">' })} />);
    const body = screen.getByRole("region", { name: "연구 기록" });
    expect(within(body).getByRole("heading", { level: 3, name: "초기 문제" })).toBeVisible();
    expect(within(body).getByRole("heading", { level: 3, name: "분리한 판단" })).toBeVisible();
    expect(within(body).getAllByRole("paragraph").map((p) => p.textContent)).toEqual([
      "본문 첫 줄\r\n둘째 줄", '<img src=x onerror="alert(1)">',
    ]);
    expect(document.querySelector("img")).toBeNull();
  });

  it("does not guess headings from unknown first lines, inline labels, or standalone labels", () => {
    render(<StudyBody snapshot={studySnapshot({ body: "새로운 관점\n설명\n\n문제\n\n문제: 실제 문장\n다음 줄" })} />);
    const body = screen.getByRole("region", { name: "연구 기록" });
    expect(within(body).queryAllByRole("heading", { level: 3 })).toHaveLength(0);
    expect(within(body).getAllByRole("paragraph").map((p) => p.textContent)).toEqual([
      "새로운 관점\n설명", "문제", "문제: 실제 문장\n다음 줄",
    ]);
  });

  it("preserves repeated subsection labels without duplicate heading IDs and leaves other fields plain", () => {
    render(<StudyBody snapshot={studySnapshot({
      body: "문제\n첫 사례\n\n문제\n둘째 사례",
      verification: "문제\n검증 설명",
      limitations: "문제\n한계 설명",
    })} />);
    const body = screen.getByRole("region", { name: "연구 기록" });
    const headings = within(body).getAllByRole("heading", { level: 3, name: "문제" });
    expect(headings).toHaveLength(2);
    expect(headings.filter((heading) => heading.hasAttribute("id"))).toHaveLength(0);
    expect(within(body).getAllByRole("paragraph").map((p) => p.textContent)).toEqual(["첫 사례", "둘째 사례"]);
    expect(within(screen.getByRole("region", { name: "과거 검증 기록" })).queryAllByRole("heading", { level: 3 })).toHaveLength(0);
    expect(within(screen.getByRole("region", { name: "남은 한계" })).queryAllByRole("heading", { level: 3 })).toHaveLength(0);
  });

  it("separates blank-line paragraphs without interpreting headings or changing line text", () => {
    render(<StudyBody snapshot={studySnapshot({
      body: "첫 줄\r\n둘째 줄\r\n\r\n# 그대로인 제목\n다음 줄\n \n마지막 문단",
      verification: "검증 하나\n\n검증 둘",
      limitations: "한계 하나\n\n한계 둘",
    })} />);

    const body = screen.getByRole("region", { name: "연구 기록" });
    expect(within(body).getAllByRole("paragraph").map((p) => p.textContent)).toEqual([
      "첫 줄\r\n둘째 줄", "# 그대로인 제목\n다음 줄", "마지막 문단",
    ]);
    expect(within(body).getAllByRole("heading")).toHaveLength(1);
    expect(within(screen.getByRole("region", { name: "과거 검증 기록" })).getAllByRole("paragraph").slice(0, 2).map((p) => p.textContent)).toEqual(["검증 하나", "검증 둘"]);
    expect(within(screen.getByRole("region", { name: "남은 한계" })).getAllByRole("paragraph").map((p) => p.textContent)).toEqual(["한계 하나", "한계 둘"]);
  });

  it("does not create empty paragraphs for empty text or surrounding blank lines", () => {
    render(<StudyBody snapshot={studySnapshot({ body: "\n\n본문\n\n", verification: "", limitations: "\r\n \r\n" })} />);
    expect(within(screen.getByRole("region", { name: "연구 기록" })).getAllByRole("paragraph").map((p) => p.textContent)).toEqual(["본문"]);
    expect(within(screen.getByRole("region", { name: "남은 한계" })).queryAllByRole("paragraph")).toHaveLength(0);
    expect(within(screen.getByRole("region", { name: "과거 검증 기록" })).getAllByRole("paragraph")).toHaveLength(1);
  });

  it("renders unsafe-looking public text as escaped plain text", () => {
    render(<StudyBody snapshot={studySnapshot({ body: '<img src=x onerror="alert(1)"> **bold**' })} />);

    expect(screen.getByText('<img src=x onerror="alert(1)"> **bold**')).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("strong")).toBeNull();
  });

  it("labels verification as historical and limitations as remaining", () => {
    render(<StudyBody snapshot={studySnapshot()} />);

    expect(screen.getByRole("heading", { name: "과거 검증 기록" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "남은 한계" })).toBeVisible();
    expect(screen.getByText(/현재 서비스 가용성을 증명하지 않습니다/)).toBeVisible();
  });
});
