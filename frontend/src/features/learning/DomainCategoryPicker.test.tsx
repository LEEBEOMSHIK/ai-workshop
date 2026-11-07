import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { DomainCategoryPicker } from "./DomainCategoryPicker";

afterEach(cleanup);

it("keeps IME composition intact and only adds the completed category on Enter", async () => {
  const onChange = vi.fn();
  const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
  render(<form onSubmit={onSubmit}><DomainCategoryPicker value={[]} onChange={onChange} /><button type="submit">저장</button></form>);
  const input = screen.getByRole("textbox", { name: "새 업무 분야" });
  fireEvent.change(input, { target: { value: "합성 업무" } });
  fireEvent.keyDown(input, { key: "Enter", isComposing: true });
  expect(input).toHaveValue("합성 업무");
  expect(onChange).not.toHaveBeenCalled();
  input.focus();
  await userEvent.setup().keyboard("{Enter}");
  expect(onChange).toHaveBeenCalledWith(["합성 업무"]);
  expect(input).toHaveValue("");
  expect(onSubmit).not.toHaveBeenCalled();
});

it("preserves existing labels verbatim and allows keyboard deselection and reselection", async () => {
  const onChange = vi.fn();
  const initial = ["custom / legacy, label", "research"];
  function Example() {
    const [value, setValue] = useState(initial);
    return <DomainCategoryPicker value={value} onChange={(next) => { setValue(next); onChange(next); }} />;
  }
  render(<Example />);
  expect(onChange).not.toHaveBeenCalled();
  const user = userEvent.setup();
  const legacy = screen.getByRole("checkbox", { name: initial[0] });
  legacy.focus();
  await user.keyboard(" ");
  expect(onChange).toHaveBeenLastCalledWith(["research"]);
  expect(legacy).not.toBeChecked();
  await user.click(legacy);
  expect(onChange).toHaveBeenLastCalledWith(["research", initial[0]]);
});

it("does not duplicate existing labels and disables additions and category changes", async () => {
  const onChange = vi.fn();
  const user = userEvent.setup();
  const { rerender } = render(<DomainCategoryPicker value={["research"]} onChange={onChange} />);
  await user.type(screen.getByRole("textbox", { name: "새 업무 분야" }), " research ");
  await user.click(screen.getByRole("button", { name: "분야 추가" }));
  expect(onChange).not.toHaveBeenCalled();
  expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  rerender(<DomainCategoryPicker disabled value={["research"]} onChange={onChange} />);
  expect(screen.getByRole("textbox")).toBeDisabled();
  expect(screen.getByRole("checkbox")).toBeDisabled();
  await user.click(screen.getByRole("checkbox"));
  expect(onChange).not.toHaveBeenCalled();
});
