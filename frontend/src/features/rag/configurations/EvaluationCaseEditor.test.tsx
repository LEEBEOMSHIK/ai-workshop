import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EvaluationCaseEditor } from "./EvaluationCaseEditor";
import type { AuthoringCase, AuthoringEvidence } from "./api";

const evidence: AuthoringEvidence = { id: "unit", document_id: "doc", asset_version_id: "asset", projection_id: "projection", index_build_id: "build", element_id: "element", text: "가😀나", start_char: 10, end_char: 13, page: null, bounding_boxes: [] };
function Editor() {
  const [value, setValue] = useState<AuthoringCase>({ id: "case", query: "", expected_answer_status: "supported", expected_evidence_ids: [], expected_highlight: null });
  return <><EvaluationCaseEditor value={value} index={0} evidence={[evidence]} documents={[]} onChange={setValue} onRemove={() => {}} /><output aria-label="작성된 사례">{JSON.stringify(value)}</output></>;
}
it("rejects a split surrogate selection and keeps insufficient labels empty", async () => {
  const user = userEvent.setup(); render(<Editor />);
  await user.click(screen.getByRole("checkbox", { name: "정답 근거 1" }));
  const text = screen.getByRole("textbox", { name: "근거 원문 1" }) as HTMLTextAreaElement;
  text.setSelectionRange(1, 2); fireEvent.select(text);
  await user.click(screen.getByRole("button", { name: "선택 구간을 기대 하이라이트로 지정" }));
  expect(screen.getByRole("alert")).toHaveTextContent("문자 구간");
  text.setSelectionRange(1, 3); fireEvent.select(text);
  await user.click(screen.getByRole("button", { name: "선택 구간을 기대 하이라이트로 지정" }));
  expect(JSON.parse(screen.getByLabelText("작성된 사례").textContent!).expected_highlight.spans).toEqual([[11, 12]]);
  await user.selectOptions(screen.getByRole("combobox", { name: "기대 결과 1" }), "insufficient_evidence");
  expect(JSON.parse(screen.getByLabelText("작성된 사례").textContent!)).toMatchObject({ expected_answer_status: "insufficient_evidence", expected_evidence_ids: [], expected_highlight: null });
  expect(screen.queryByRole("checkbox", { name: "정답 근거 1" })).not.toBeInTheDocument();
});

it("does not invent a highlight without a selected expected source", async () => {
  const user = userEvent.setup(); render(<Editor />);
  const text = screen.getByRole("textbox", { name: "근거 원문 1" }) as HTMLTextAreaElement;
  text.setSelectionRange(0, 1);
  await user.click(screen.getByRole("button", { name: "선택 구간을 기대 하이라이트로 지정" }));
  expect(screen.getByRole("alert")).toHaveTextContent("먼저");
  expect(JSON.parse(screen.getByLabelText("작성된 사례").textContent!).expected_highlight).toBeNull();
});
