import Link from "next/link";
import { IssueHistoryPage } from "../../../../../features/issue-history/IssueHistoryPage";
import { loadIssueDetail, loadIssueDocument, loadIssueLedger } from "../../../../../features/issue-history/server-ledger";
import { requireOwner } from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import { captureServerRoute, ServerRouteFailure } from "../../../../../shared/ui/ServerRouteFailure";
export const dynamic = "force-dynamic";
type Params = Record<string, string | string[] | undefined>;
export default async function IssueHistoryRoute({searchParams}: {searchParams: Promise<Params>}) {
 const result = await captureServerRoute(async () => {
  await requireOwner(routes.adminSystemIssues);
  const raw = await searchParams;
  const param = (key: string) => typeof raw[key] === "string" ? raw[key] as string : undefined;
  const offset = Number(param("offset") ?? 0);
  const filters = {q: param("q"), status: param("status"), category_id: param("category_id"), parent_category_id: param("parent_category_id"), offset: Number.isSafeInteger(offset) && offset >= 0 ? offset : 0};
  const {list, categories} = await loadIssueLedger(filters);
  const requested = param("issue");
  const issueId = list.items.find(item => item.id === requested || item.issue_key === requested)?.id ?? (requested && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(requested) ? requested : list.items[0]?.id);
  const legacy = param("document") !== undefined;
  const document = !legacy && issueId && param("document_id") && param("version") ? await loadIssueDocument(issueId, param("document_id")!, param("version")!) : null;
  const selected = issueId && !document ? await loadIssueDetail(issueId) : null;
  return {list,categories,filters,selected,document,legacy,issueId};
 });
 if (!result.ok) return <ServerRouteFailure failure={result.failure}/>;
 const {document,issueId,...data} = result.value;
 if (document) return <main style={{maxWidth:"1120px",margin:"0 auto",padding:24}}>
  <Link href={`${routes.adminSystemIssues}?issue=${encodeURIComponent(issueId!)}`}>← 문제 이력으로 돌아가기</Link>
  <h1>{document.title}</h1><p>연결 버전 {document.version} · 현재 버전 {document.current_version}</p><p>{document.source_path}</p>
  <pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",lineHeight:1.7}}>{document.content}</pre>
 </main>;
 return <IssueHistoryPage {...data}/>;
}
