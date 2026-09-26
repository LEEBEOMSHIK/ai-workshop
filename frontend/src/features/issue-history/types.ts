export type IssueStatus = "open" | "implemented" | "verified";
export interface Issue {
  id: string;
  title: string;
  area: string;
  status: IssueStatus;
  symptom: string;
  cause: string;
  resolution: string;
  verification: string[];
  remaining: string[];
  evidence: string[];
  commits: string[];
  history: {date: string; event: string}[];
}
export interface IssueLedger {
  schema_version: number;
  updated_at: string;
  visibility: "internal";
  issues: Issue[];
}
