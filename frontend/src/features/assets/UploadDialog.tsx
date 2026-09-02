import { type ChangeEvent, useRef, useState } from "react";

const accepted = ".pdf,.docx,.pptx,.xlsx,.txt,.md,.html,.htm";

interface UploadDialogProps {
  onUpload: (file: File) => Promise<void>;
}

export function UploadDialog({ onUpload }: UploadDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<string | null>(null);

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setStatus("업로드 중…");
    try {
      await onUpload(file);
      setStatus("저장 완료");
    } catch {
      setStatus("업로드 실패");
    } finally {
      event.target.value = "";
    }
  }

  return (
    <div className="upload-control">
      <button type="button" onClick={() => inputRef.current?.click()}>
        문서 올리기
      </button>
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept={accepted}
        onChange={handleFile}
      />
      {status ? <span role="status">{status}</span> : null}
    </div>
  );
}
