import type { DocumentSummary } from "./api";
import { DocumentBrowser } from "./DocumentBrowser";

interface DocumentPageProps {
  workspaceId: string;
  initialDocuments: DocumentSummary[];
}

export function DocumentPage({ workspaceId, initialDocuments }: DocumentPageProps) {
  return (
    <DocumentBrowser
      workspaceId={workspaceId}
      workspaceName="문서 라이브러리"
      initialDocuments={initialDocuments}
    />
  );
}
