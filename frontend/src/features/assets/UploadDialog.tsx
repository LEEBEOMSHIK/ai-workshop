import { type ChangeEvent, useEffect, useRef, useState } from "react";

import { ApiError } from "../../shared/api/client";

const accepted = ".pdf,.docx,.pptx,.xlsx,.txt,.md,.html,.htm";

interface UploadDialogProps {
  onUpload: (file: File) => Promise<void>;
  buttonLabel?: string;
  inputLabel?: string;
  disabled?: boolean;
}

export function UploadDialog({
  onUpload,
  buttonLabel = "문서 올리기",
  inputLabel = "새 문서 파일",
  disabled = false,
}: UploadDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [retryFile, setRetryFile] = useState<File | null>(null);
  const busy = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  async function upload(file: File) {
    if (disabled || busy.current) return;
    busy.current = true;
    setPending(true);
    setRetryFile(null);
    setStatus("업로드 중…");
    try {
      await onUpload(file);
      if (mounted.current) setStatus("저장 완료 · 검색 준비 상태는 별도로 확인해 주세요.");
    } catch (error) {
      if (!mounted.current) return;
      if (!(error instanceof ApiError && ([401, 403, 404].includes(error.status) || error.code === "duplicate_document_content"))) setRetryFile(file);
      setStatus(
        error instanceof ApiError && error.code === "duplicate_document_content"
          ? "같은 내용의 문서가 이 지식 공간에 이미 있습니다."
          : "업로드 실패",
      );
    } finally {
      busy.current = false;
      if (mounted.current) setPending(false);
    }
  }

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void upload(file);
  }

  return (
    <div className="upload-control">
      <button type="button" disabled={disabled || pending} onClick={() => inputRef.current?.click()}>
        {buttonLabel}
      </button>
      <input
        ref={inputRef}
        aria-label={inputLabel}
        className="visually-hidden"
        type="file"
        disabled={disabled || pending}
        accept={accepted}
        onChange={handleFile}
      />
      {status ? <span role="status">{status}</span> : null}
      {retryFile ? <button type="button" disabled={disabled || pending} onClick={() => void upload(retryFile)}>업로드 다시 시도</button> : null}
    </div>
  );
}
