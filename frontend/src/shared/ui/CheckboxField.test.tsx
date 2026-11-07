import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";
import { CheckboxField } from "./CheckboxField";

afterEach(cleanup);

it("toggles with its label and Space while preserving native form semantics", async () => {
  const user = userEvent.setup();
  render(<form><CheckboxField label="긴 설명을 포함한 실험 항목" name="experiment" value="enabled" /></form>);
  const input = screen.getByRole("checkbox", { name: "긴 설명을 포함한 실험 항목" });
  await user.click(screen.getByText("긴 설명을 포함한 실험 항목"));
  expect(input).toBeChecked();
  expect(new FormData(input.closest("form")!).get("experiment")).toBe("enabled");
  input.focus();
  await user.keyboard(" ");
  expect(input).not.toBeChecked();
});

it("keeps disabled and fieldset-disabled checkboxes noninteractive", async () => {
  const user = userEvent.setup();
  render(<><CheckboxField label="직접 비활성" disabled defaultChecked /><fieldset disabled><CheckboxField label="그룹 비활성" /></fieldset></>);
  await user.click(screen.getByText("직접 비활성"));
  await user.click(screen.getByText("그룹 비활성"));
  expect(screen.getByRole("checkbox", { name: "직접 비활성" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "그룹 비활성" })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: "그룹 비활성" })).toBeDisabled();
});
