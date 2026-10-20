import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { ChoiceGroup } from "./ChoiceGroup";
import styles from "./ChoiceGroup.module.css";

const options = [{ value: "saved", label: "저장 자료" }, { value: "create", label: "새 자료" }] as const;
describe.each(["default", "segmented"] as const)("%s choice presentation", variant => {
function Controlled({ legend = "준비 방식" }: { legend?: string }) {
  const [value, setValue] = useState<"saved" | "create">("saved");
  return <ChoiceGroup variant={variant} legend={legend} description="선택한 방식으로 준비합니다." options={options} value={value} onChange={setValue} />;
}

it("exposes a named native group with connected description and labelled radio inputs", () => {
  render(<Controlled />);
  const group = screen.getByRole("group", { name: "준비 방식" });
  expect(group.tagName).toBe("FIELDSET");
  expect(group).toHaveAccessibleDescription("선택한 방식으로 준비합니다.");
  expect(within(group).getByRole("radio", { name: "저장 자료" })).toBeChecked();
  expect(within(group).getByRole("radio", { name: "새 자료" })).not.toBeChecked();
  const inputs = within(group).getAllByRole("radio") as HTMLInputElement[];
  expect(inputs[0].type).toBe("radio");
  expect(inputs[0].name).toBeTruthy();
  expect(inputs[0].name).toBe(inputs[1].name);
});

it("changes a controlled choice by clicking its full text label", async () => {
  render(<Controlled />);
  await userEvent.setup().click(screen.getByText("새 자료"));
  expect(screen.getByRole("radio", { name: "새 자료" })).toBeChecked();
  expect(screen.getByRole("radio", { name: "저장 자료" })).not.toBeChecked();
});

it("reports the requested value and leaves selection controlled by the caller", async () => {
  const onChange = vi.fn();
  const view = render(<ChoiceGroup variant={variant} legend="방식" options={options} value="saved" onChange={onChange} />);
  await userEvent.setup().click(screen.getByRole("radio", { name: "새 자료" }));
  expect(onChange).toHaveBeenCalledExactlyOnceWith("create");
  expect(screen.getByRole("radio", { name: "저장 자료" })).toBeChecked();
  view.rerender(<ChoiceGroup variant={variant} legend="방식" options={options} value="create" onChange={onChange} />);
  expect(screen.getByRole("radio", { name: "새 자료" })).toBeChecked();
});

it("keeps keyboard navigation inside each separately named group", async () => {
  render(<form><Controlled legend="첫 선택" /><Controlled legend="다음 선택" /></form>);
  const first = within(screen.getByRole("group", { name: "첫 선택" }));
  const second = within(screen.getByRole("group", { name: "다음 선택" }));
  const user = userEvent.setup();
  await user.tab();
  expect(first.getByRole("radio", { name: "저장 자료" })).toHaveFocus();
  await user.keyboard("{ArrowRight}");
  expect(first.getByRole("radio", { name: "새 자료" })).toHaveFocus();
  expect(first.getByRole("radio", { name: "새 자료" })).toBeChecked();
  expect(second.getByRole("radio", { name: "저장 자료" })).toBeChecked();
  await user.tab();
  expect(second.getByRole("radio", { name: "저장 자료" })).toHaveFocus();
  await user.keyboard("{ArrowRight}");
  expect(second.getByRole("radio", { name: "새 자료" })).toBeChecked();
  expect((first.getByRole("radio", { name: "새 자료" }) as HTMLInputElement).name)
    .not.toBe((second.getByRole("radio", { name: "새 자료" }) as HTMLInputElement).name);
});

it("disables the group without clearing its current selection or emitting changes", async () => {
  const onChange = vi.fn();
  render(<ChoiceGroup variant={variant} legend="비활성 선택" options={options} value="create" onChange={onChange} disabled />);
  for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
  expect(screen.getByRole("radio", { name: "새 자료" })).toBeChecked();
  await userEvent.setup().click(screen.getByText("저장 자료"));
  expect(onChange).not.toHaveBeenCalled();
});

it("preserves a disabled option's selected value until the caller chooses another enabled option", async () => {
  const onChange = vi.fn();
  render(<ChoiceGroup variant={variant} legend="옵션별 상태" options={[options[0], { ...options[1], disabled: true }]} value="create" onChange={onChange} />);
  expect(screen.getByRole("radio", { name: "새 자료" })).toBeChecked();
  expect(screen.getByRole("radio", { name: "새 자료" })).toBeDisabled();
  await userEvent.setup().click(screen.getByText("새 자료"));
  expect(onChange).not.toHaveBeenCalled();
  await userEvent.setup().click(screen.getByText("저장 자료"));
  expect(onChange).toHaveBeenCalledExactlyOnceWith("saved");
});

});

it("applies connected segment styling only when explicitly selected", () => {
  const view = render(<ChoiceGroup legend="Choices" options={options} value="saved" onChange={vi.fn()} />);
  expect(screen.getByRole("group", { name: "Choices" })).not.toHaveClass(styles.segmented);
  view.rerender(<ChoiceGroup variant="segmented" legend="Choices" options={options} value="saved" onChange={vi.fn()} />);
  expect(screen.getByRole("group", { name: "Choices" })).toHaveClass(styles.segmented);
  for (const radio of screen.getAllByRole("radio")) {
    expect(radio).not.toHaveAttribute("aria-hidden");
    expect(radio).not.toHaveAttribute("tabindex", "-1");
  }
});
