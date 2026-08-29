import { useLoaderData, useParams } from "react-router-dom";

import type { DocumentSummary } from "./api";
import { DocumentBrowser } from "./DocumentBrowser";

export function DocumentPage() {
  const { workspaceId = "" } = useParams();
  const documents = useLoaderData() as DocumentSummary[];
  return (
    <DocumentBrowser
      workspaceId={workspaceId}
      workspaceName="문서 라이브러리"
      initialDocuments={documents}
    />
  );
}
