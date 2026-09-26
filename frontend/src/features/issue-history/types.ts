// API response aliases are generated from the backend OpenAPI contract.
import type { components } from "../../shared/api/schema";
export type IssueStatus = "open" | "implemented" | "verified";
export type Category = components["schemas"]["IssueCategoryView"];
export type Issue = components["schemas"]["IssueView"];
export type IssueDetail = components["schemas"]["IssueDetail"];
export type IssueDocument = components["schemas"]["IssueDocumentView"];
export type DocumentVersion = components["schemas"]["IssueDocumentVersionView"];
export interface IssueList {
    items: Issue[];
    total: number;
    status_counts: Record<IssueStatus, number>;
}
