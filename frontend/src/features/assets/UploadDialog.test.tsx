import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { UploadDialog } from "./UploadDialog";

it("blocks duplicate file submissions while pending and explicitly retries the failed file", async () => {
  let reject!: (reason: Error) => void;
  const upload = vi.fn().mockImplementationOnce(() => new Promise<void>((_resolve, fail) => { reject = fail; })).mockResolvedValue(undefined);
  render(<UploadDialog onUpload={upload} />);
  const file = new File(["synthetic"], "sample.txt", { type: "text/plain" });
  fireEvent.change(screen.getByLabelText("새 문서 파일"), { target: { files: [file] } });
  fireEvent.change(screen.getByLabelText("새 문서 파일"), { target: { files: [file] } });
  expect(upload).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "문서 올리기" })).toBeDisabled();
  await act(async () => reject(new Error("offline")));
  await userEvent.click(screen.getByRole("button", { name: "업로드 다시 시도" }));
  expect(await screen.findByText(/저장 완료/)).toBeVisible();
  expect(upload).toHaveBeenLastCalledWith(file);
});
