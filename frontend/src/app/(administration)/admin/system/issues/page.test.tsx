import {beforeEach,expect,it,vi} from "vitest";
import {requireOwner} from "../../../../../shared/auth/server-session";
import {loadIssueLedger,loadIssueDocument,loadIssueDetail} from "../../../../../features/issue-history/server-ledger";
import IssueHistoryRoute from "./page";
import {ApiError} from "../../../../../shared/api/client";
import type {IssueDetail} from "../../../../../features/issue-history/types";
const detail: IssueDetail = {
 id:"canonical-id", issue_key:"ISSUE-00001", legacy_keys:["RAG-0001"],
 category_id:"category-id", title:"Example issue", status:"open", symptom:"", cause:"", resolution:"",
 revision:1, created_at:"2026-09-27T00:00:00Z", updated_at:"2026-09-27T00:00:00Z", events:[], documents:[],
};
vi.mock("../../../../../features/issue-history/IssueHistoryPage",()=>({IssueHistoryPage:vi.fn(()=>null)}));
vi.mock("../../../../../features/issue-history/server-ledger",()=>({loadIssueLedger:vi.fn(),loadIssueDocument:vi.fn(),loadIssueDetail:vi.fn()}));
vi.mock("../../../../../shared/auth/server-session",()=>({requireOwner:vi.fn()}));
beforeEach(()=>vi.resetAllMocks());
it("blocks database reads until owner authorization",async()=>{
 vi.mocked(requireOwner).mockRejectedValue(new Error("redirect"));
 await expect(IssueHistoryRoute({searchParams:Promise.resolve({})})).rejects.toThrow("redirect");expect(loadIssueLedger).not.toHaveBeenCalled();expect(loadIssueDocument).not.toHaveBeenCalled();
});
it("does not interpret old document indexes as database versions",async()=>{
 vi.mocked(loadIssueLedger).mockResolvedValue({list:{items:[],total:0,status_counts:{open:0,implemented:0,verified:0}},categories:[]});
 vi.mocked(loadIssueDetail).mockResolvedValue(detail);
 const result=await IssueHistoryRoute({searchParams:Promise.resolve({issue:"RAG-0001",document:"0",q:"no matching issue"})});
 expect(loadIssueDetail).toHaveBeenCalledWith("RAG-0001");
 expect(result.props.selected.id).toBe("canonical-id");
 expect(result.props.legacy).toBe(true);expect(loadIssueDocument).not.toHaveBeenCalled();expect(vi.mocked(requireOwner)).toHaveBeenCalledBefore(vi.mocked(loadIssueLedger));
});
it("resolves legacy references outside the current page before reading a pinned document",async()=>{
 vi.mocked(loadIssueLedger).mockResolvedValue({list:{items:[],total:0,status_counts:{open:0,implemented:0,verified:0}},categories:[]});
 vi.mocked(loadIssueDetail).mockResolvedValue(detail);
 await IssueHistoryRoute({searchParams:Promise.resolve({issue:"RAG-0001",document_id:"doc-id",version:"2",offset:"40",q:"unrelated"})});
 expect(loadIssueDetail).toHaveBeenCalledWith("RAG-0001");
 expect(loadIssueDocument).toHaveBeenCalledWith("canonical-id","doc-id","2");
});
it("shows a missing-issue error instead of silently selecting a different issue",async()=>{
 vi.mocked(loadIssueLedger).mockResolvedValue({list:{items:[],total:0,status_counts:{open:0,implemented:0,verified:0}},categories:[]});
 vi.mocked(loadIssueDetail).mockRejectedValue(new ApiError("Issue not found",404,"issue_not_found"));
 const result=await IssueHistoryRoute({searchParams:Promise.resolve({issue:"RAG-missing"})});
 expect(loadIssueDetail).toHaveBeenCalledWith("RAG-missing");
 expect(result.props.failure).toBeDefined();
});
