import { serverApiRequest } from "../../shared/api/server-client";
import { incomingCookieHeader } from "../../shared/auth/server-session";
import { issueApi, issueListPath, type IssueFilters } from "./api";
import type { Category, IssueList, IssueDetail, DocumentVersion } from "./types";
export async function loadIssueLedger(filters: IssueFilters = {}) {
    const cookie = await incomingCookieHeader();
    const [list, categories] = await Promise.all([
        serverApiRequest<IssueList>(issueListPath(filters), {}, cookie),
        serverApiRequest<{
            items: Category[];
        }>(`${issueApi}/categories`, {}, cookie),
    ]);
    return { list, categories: categories.items };
}
export async function loadIssueDetail(id: string) {
    return serverApiRequest<IssueDetail>(`${issueApi}/issues/${encodeURIComponent(id)}`, {}, await incomingCookieHeader());
}
export async function loadIssueDocument(issue: string, document: string, version: string) {
    return serverApiRequest<DocumentVersion>(`${issueApi}/issues/${encodeURIComponent(issue)}/documents/${encodeURIComponent(document)}/versions/${encodeURIComponent(version)}`, {}, await incomingCookieHeader());
}
