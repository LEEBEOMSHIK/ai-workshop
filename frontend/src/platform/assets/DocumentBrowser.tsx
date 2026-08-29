import { useState } from "react";

import { type DocumentSummary, uploadDocument } from "./api";
import { UploadDialog } from "./UploadDialog";

interface DocumentBrowserProps {
  workspaceId?: string;
  workspaceName: string;
  initialDocuments?: DocumentSummary[];
}

const statusLabels: Record<DocumentSummary["status"], string> = {
  stored: "저장됨",
  processing: "처리 중",
  ready: "준비됨",
  failed: "실패",
};

export function DocumentBrowser({
  workspaceId = "",
  workspaceName,
  initialDocuments = [],
}: DocumentBrowserProps) {
  const [documents, setDocuments] = useState(initialDocuments);

  async function handleUpload(file: File) {
    if (!workspaceId) throw new Error("Workspace is required");
    const document = await uploadDocument(workspaceId, file);
    setDocuments((current) => [...current, document]);
  }

  return (
    <main className="document-shell">
      <header className="document-header">
        <div>
          <p className="eyebrow">DOCUMENT LIBRARY</p>
          <h1 className="document-title">{workspaceName}</h1>
          <p>원본과 모든 버전을 로컬에서 관리합니다.</p>
        </div>
        <UploadDialog onUpload={handleUpload} />
      </header>
      <section className="document-list" aria-label="문서 목록">
        {documents.map((document) => (
          <article className="document-row" key={document.id}>
            <div className="file-mark" aria-hidden="true">
              {document.name.split(".").pop()?.toUpperCase()}
            </div>
            <div className="document-meta">
              <h2>{document.name}</h2>
              <p>버전 {document.latest_version}</p>
            </div>
            <span className={`document-state ${document.status}`}>
              {statusLabels[document.status]}
            </span>
          </article>
        ))}
      </section>
    </main>
  );
}
