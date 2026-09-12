import type { WorkspaceSummary } from "../workspaces/api";
import type { DocumentSummary, LibraryPage } from "./api";
import { DocumentBrowser } from "./DocumentBrowser";

interface DocumentPageProps {
  workspaceId: string;
  initialLibrary: LibraryPage;
  initialRoot: LibraryPage;
  initialWorkspaces: WorkspaceSummary[];
  initialDocument: DocumentSummary | null;
  initialVersionId: string | null;
}

export function DocumentPage({ workspaceId, initialLibrary, initialRoot, initialWorkspaces, initialDocument, initialVersionId }: DocumentPageProps) {
  return (
    <DocumentBrowser
      workspaceId={workspaceId}
      initialLibrary={initialLibrary}
      initialRoot={initialRoot}
      initialWorkspaces={initialWorkspaces}
      initialDocument={initialDocument}
      initialVersionId={initialVersionId}
      showMemberManagement
    />
  );
}
