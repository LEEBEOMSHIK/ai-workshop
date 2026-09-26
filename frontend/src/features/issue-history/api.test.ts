import { expect, it } from "vitest";
import { issueListPath, mutationRequest } from "./api";
it("encodes server filters and pagination", () => {
    expect(issueListPath({ q: "검색 & 문서", status: "open", category_id: "cat", offset: 20 })).toBe("/api/v1/admin/issue-history/issues?q=%EA%B2%80%EC%83%89+%26+%EB%AC%B8%EC%84%9C&status=open&category_id=cat&offset=20&limit=20");
});
it("keeps a request id on unchanged retries and changes it for changed payload", () => {
    const retry = mutationRequest();
    const first = retry({ title: "a" });
    expect(retry({ title: "a" }).request_id).toBe(first.request_id);
    expect(retry({ title: "b" }).request_id).not.toBe(first.request_id);
});
it("sends a parent-only filter for aggregate searches", () => {
 expect(issueListPath({parent_category_id:"rag"})).toBe("/api/v1/admin/issue-history/issues?parent_category_id=rag&offset=0&limit=20");
});
