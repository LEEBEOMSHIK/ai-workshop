import {beforeEach,expect,it,vi} from "vitest";
import {requireOwner} from "../../../../../shared/auth/server-session";
import {loadIssueLedger,loadIssueDocument,loadIssueDetail} from "../../../../../features/issue-history/server-ledger";
import IssueHistoryRoute from "./page";
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
 const result=await IssueHistoryRoute({searchParams:Promise.resolve({issue:"RAG-0001",document:"0",q:"no matching issue"})});
 expect(loadIssueDetail).not.toHaveBeenCalled();
 expect(result.props.legacy).toBe(true);expect(loadIssueDocument).not.toHaveBeenCalled();expect(vi.mocked(requireOwner)).toHaveBeenCalledBefore(vi.mocked(loadIssueLedger));
});
