import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { EvidencePanel } from "./EvidencePanel";
import type { Evidence } from "./api";

vi.mock("../search/SourceViewer", () => ({ SourceViewer: () => <button>원문 내부 동작</button> }));

it("traps focus and restores it after closing the source dialog", async () => {
  const evidence = { source: { asset_version_id: "asset", projection_id: "projection", location: { page: 1 } }, highlights: [] } as unknown as Evidence;
  function Harness() {
    const [open, setOpen] = useState(false);
    return <><button onClick={() => setOpen(true)}>근거 열기</button>{open ? <EvidencePanel evidence={evidence} onClose={() => setOpen(false)} /> : null}</>;
  }
  render(<Harness />);
  const user = userEvent.setup();
  await user.click(screen.getByText("근거 열기"));
  expect(screen.getByText("원문 닫기")).toHaveFocus();
  await user.tab({ shift: true });
  expect(screen.getByText("원문 내부 동작")).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.getByText("근거 열기")).toHaveFocus();
});
