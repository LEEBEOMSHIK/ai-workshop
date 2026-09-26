import { apiRequest } from "../../shared/api/client";
export const issueApi = "/api/v1/admin/issue-history";
export interface IssueFilters {
    q?: string;
    status?: string;
    category_id?: string;
    parent_category_id?: string;
    offset?: number;
}
export function issueListPath(filters: IssueFilters) {
    const query = new URLSearchParams();
    for (const key of ["q", "status", "category_id", "parent_category_id"] as const)
        if (filters[key])
            query.set(key, filters[key]!);
    query.set("offset", String(filters.offset ?? 0));
    query.set("limit", "20");
    return `${issueApi}/issues?${query}`;
}
export function mutationRequest() {
    let previous = "";
    let id = "";
    return (payload: Record<string, unknown>) => {
        const value = JSON.stringify(payload);
        if (value !== previous) {
            previous = value;
            id = crypto.randomUUID();
        }
        return { ...payload, request_id: id };
    };
}
export function saveIssueHistory<T>(path: string, method: "POST" | "PUT", payload: Record<string, unknown>) {
    return apiRequest<T>(`${issueApi}/${path}`, { method, headers: { "x-publishing-request": "1" }, json: payload });
}
