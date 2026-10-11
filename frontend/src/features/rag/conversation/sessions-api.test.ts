import { afterEach, expect, it, vi } from "vitest";
import { abandonAttachmentDraft, createAttachmentDraft, excludeDraftAttachment, getAttachmentDraft, getAttachmentOptions, getConversationStart, getDraftAttachmentOptions, listDraftAttachments, restoreConversationDraft, sendConversationTurn, startConversation, uploadDraftAttachment, type AttachmentDraft, type StartRequest } from "./sessions-api";

afterEach(()=>vi.unstubAllGlobals());
const draft:AttachmentDraft={id:"draft/a",revision:4,state:"open",bound_conversation_id:null,legacy_conversation_id:null,created_at:"2026-09-30",updated_at:"2026-09-30",expires_at:"2026-10-01"};
it("keeps first-start and subsequent-turn paths, replay fields and Codex consent header distinct",async()=>{
  const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{void input;void init;return new Response("{}",{headers:{"content-type":"application/json"}});});vi.stubGlobal("fetch",fetcher);
  const request:StartRequest={connection_version_id:"connection",query:"synthetic question",workspace_ids:["workspace"],folder_ids:[],document_ids:["document"],request_id:"request",draft_id:"draft",draft_revision:4,top_k:10,include_diagnostics:true,codex_input_approval:{classification:"synthetic",consented:true,disclosure_version:"v1"}};
  await startConversation("example",request);await getConversationStart("example","request");
  await sendConversationTurn("example","accepted",{...request,expected_revision:2});
  expect(fetcher.mock.calls.map(args=>String(args[0]))).toEqual(["/api/v1/rag/domains/example/conversations/start","/api/v1/rag/domains/example/conversations/starts/request","/api/v1/rag/domains/example/conversations/accepted/turns"]);
  const options=fetcher.mock.calls.map(args=>args[1] as RequestInit);
  expect(options[0]).toMatchObject({method:"POST",credentials:"include",cache:"no-store"});
  expect(new Headers(options[0].headers).get("x-codex-request")).toBe("1");
  expect(JSON.parse(String(options[0].body))).toEqual(request);
  expect(JSON.parse(String(options[0].body))).not.toHaveProperty("expected_revision");
  expect(options[1].method).toBeUndefined();expect(JSON.parse(String(options[2].body)).expected_revision).toBe(2);
});

it("reads options without mutations and uses draft manifest revision for multipart upload, exclusion and abandon",async()=>{
  const calls:Array<{path:string;init:RequestInit}>=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{calls.push({path:String(input),init:init??{}});return new Response("{}",{headers:{"content-type":"application/json"}});}));
  await getAttachmentOptions("domain/a");expect(calls).toHaveLength(1);expect(calls[0].init.method).toBeUndefined();
  await createAttachmentDraft("domain/a","draft-key");await getAttachmentDraft("domain/a",draft.id);
  await getDraftAttachmentOptions("domain/a",draft.id);await listDraftAttachments("domain/a",draft.id);
  const file=new File(["synthetic"],"synthetic.txt");await uploadDraftAttachment("domain/a",draft,"space/a",file);
  await excludeDraftAttachment("domain/a",draft,"attachment/a");await abandonAttachmentDraft("domain/a",draft);await restoreConversationDraft("domain/a","legacy/a");
  expect(calls.map(call=>call.path)).toEqual([
    "/api/v1/rag/domains/domain%2Fa/attachment-options",
    "/api/v1/rag/domains/domain%2Fa/attachment-drafts",
    "/api/v1/rag/domains/domain%2Fa/attachment-drafts/draft%2Fa",
    "/api/v1/rag/domains/domain%2Fa/attachment-drafts/draft%2Fa/attachment-options",
    "/api/v1/rag/domains/domain%2Fa/attachment-drafts/draft%2Fa/attachments",
    "/api/v1/rag/domains/domain%2Fa/attachment-drafts/draft%2Fa/attachments?workspace_id=space%2Fa&expected_revision=4",
    "/api/v1/rag/domains/domain%2Fa/attachment-drafts/draft%2Fa/attachments/attachment%2Fa?expected_revision=4",
    "/api/v1/rag/domains/domain%2Fa/attachment-drafts/draft%2Fa?expected_revision=4",
    "/api/v1/rag/domains/domain%2Fa/conversations/legacy%2Fa/restore-draft",
  ]);
  expect(JSON.parse(String(calls[1].init.body))).toEqual({request_id:"draft-key"});
  expect((calls[5].init.body as FormData).get("file")).toBe(file);
  expect(calls[6].init.method).toBe("DELETE");expect(calls[7].init.method).toBe("DELETE");
  expect(calls.every(call=>call.init.cache==="no-store"&&call.init.credentials==="include")).toBe(true);
});
