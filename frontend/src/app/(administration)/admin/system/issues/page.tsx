import Link from "next/link";
import { IssueHistoryPage } from "../../../../../features/issue-history/IssueHistoryPage";
import { loadIssueDocument, loadIssueLedger } from "../../../../../features/issue-history/server-ledger";
import { requireOwner } from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import { captureServerRoute, ServerRouteFailure } from "../../../../../shared/ui/ServerRouteFailure";

export const dynamic = "force-dynamic";

export default async function IssueHistoryRoute({searchParams}: {searchParams: Promise<{issue?: string; document?: string}>}) {
  const result = await captureServerRoute(async () => {
    await requireOwner(routes.adminSystemIssues);
    const params = await searchParams;
    const ledger = await loadIssueLedger();
    const document = params.document !== undefined
      ? await loadIssueDocument(ledger, params.issue ?? "", params.document) : null;
    return {ledger, document, issueId: params.issue};
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  const {ledger, document, issueId} = result.value;
  if (document) return <main style={{maxWidth: "1120px", margin: "0 auto", padding: "24px", minWidth: 0}}>
    <Link href={`${routes.adminSystemIssues}?issue=${encodeURIComponent(issueId ?? "")}`}>← 문제 이력으로 돌아가기</Link>
    <h1>관련 기록</h1><p>{document.name}</p>
    <pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.7, maxWidth: "100%"}}>{document.content}</pre>
  </main>;
  return <IssueHistoryPage ledger={ledger} initialIssueId={issueId} />;
}
