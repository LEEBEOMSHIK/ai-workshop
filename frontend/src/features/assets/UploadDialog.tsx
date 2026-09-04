import { type ChangeEvent, useRef, useState } from "react";

import { ApiError } from "../../shared/api/client";

const accepted = ".pdf,.docx,.pptx,.xlsx,.txt,.md,.html,.htm";

interface UploadDialogProps {
  onUpload: (file: File) => Promise<void>;
  buttonLabel?: string;
  inputLabel?: string;
}

export function UploadDialog({
  onUpload,
  buttonLabel = "문서 올리기",
  inputLabel = "새 문서 파일",
}: UploadDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<string | null>(null);

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setStatus("업로드 중…");
    try {
      await onUpload(file);
      setStatus("저장 완료");
    } catch (error) {
      setStatus(
        error instanceof ApiError && error.code === "duplicate_document_content"
          ? "같은 내용의 문서가 이 지식 공간에 이미 있습니다."
          : "업로드 실패",
      );
    } finally {
      event.target.value = "";
    }
  }

  return (
    <div className="upload-control">
      <button type="button" onClick={() => inputRef.current?.click()}>
        {buttonLabel}
      </button>
      <input
        ref={inputRef}
        aria-label={inputLabel}
        className="visually-hidden"
        type="file"
        accept={accepted}
        onChange={handleFile}
      />
      {status ? <span role="status">{status}</span> : null}
    </div>
  );
}
