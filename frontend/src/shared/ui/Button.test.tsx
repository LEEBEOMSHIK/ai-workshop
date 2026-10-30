import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { Button } from "./Button";

it("does not submit its parent form unless explicitly requested", () => {
  const submit = vi.fn(event => event.preventDefault());
  render(<form onSubmit={submit}><Button>취소</Button><Button type="submit">저장</Button></form>);
  fireEvent.click(screen.getByRole("button", { name: "취소" }));
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  expect(submit).toHaveBeenCalledTimes(1);
});

it("preserves native disabled, accessible attributes, event and focus ref", () => {
  const ref = createRef<HTMLButtonElement>();
  const clicked = vi.fn();
  const view = render(<><p id="help">설명</p><Button ref={ref} aria-describedby="help" aria-label="원문 열기" onClick={clicked} variant="quiet">열기</Button></>);
  const button = screen.getByRole("button", { name: "원문 열기" });
  expect(button).toHaveAccessibleDescription("설명");
  ref.current?.focus();
  expect(button).toHaveFocus();
  fireEvent.click(button);
  expect(clicked).toHaveBeenCalledTimes(1);
  view.rerender(<Button disabled onClick={clicked}>열기</Button>);
  fireEvent.click(screen.getByRole("button", { name: "열기" }));
  expect(clicked).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button")).toBeDisabled();
});

it("supports native submitter name and value without replacing caller classes", () => {
  render(<Button name="action" value="save" className="caller" variant="danger" form="target" type="submit">삭제</Button>);
  const button = screen.getByRole("button", { name: "삭제" });
  expect(button).toHaveAttribute("name", "action");
  expect(button).toHaveAttribute("value", "save");
  expect(button).toHaveAttribute("form", "target");
  expect(button).toHaveClass("caller");
});
