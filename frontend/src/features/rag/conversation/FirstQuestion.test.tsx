import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { StrictMode } from "react";
import { ConversationPage } from "./ConversationPage";
import type { Domain } from "../domains/api";

const domain: Domain = {id:"domain",slug:"example",display_name:"자료",description:"",active:true,ready:true,connection_version:{id:"connection",version:1},readiness:{search_ready:true,answer_ready:true,service_ready:true,reason_codes:[]},workspace_options:[{id:"workspace",name:"자료",kind:"personal",expires_at:null}],generation_execution_preview:{deployment_name:"local",model_name:"local",model_version:1,provider:"local_openai_compatible",disclosure_version:"v1",location:"local",external_transfer:false,disclosure:"로컬"}};
const summary = {id:"accepted",title:"서버 제목",title_origin:"auto",legacy_state:"active",revision:1,created_at:"2026-09-30",updated_at:"2026-09-30"};
const turn = {id:"turn",request_id:"key",sequence:1,status:"failed",query:"첫 질문",response:null,request_scope:{connection_version_id:"connection",workspace_ids:["workspace"],folder_ids:[],document_ids:null},segment:1,error_code:"provider_timeout",redacted:false,execution_terminated:true,created_at:"2026-09-30",updated_at:"2026-09-30"};
const detail = {...summary,turns:[turn]};
const json = (value:unknown,status=200) => new Response(JSON.stringify(value),{status,headers:{"content-type":"application/json"}});
const missing = () => json({error:{code:"conversation_start_not_found",message:"missing",correlation_id:"synthetic"}},404);
const deniedStart = () => json({error:{code:"draft_upload_busy",message:"synthetic",correlation_id:"synthetic"}},409);
const openDraft = {id:"draft-one",state:"open",revision:3,created_at:"2026-09-30",updated_at:"2026-09-30",expires_at:"2026-10-01",bound_conversation_id:null,legacy_conversation_id:null};
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();window.history.replaceState(null,"","/");});

it("refreshes an accepted running first question without cancelling it or clearing the draft",async()=>{
  let finished=false;
  const calls:string[]=[];
  const current=()=>({...detail,turns:[{...turn,status:finished?"failed":"running",execution_terminated:finished}]});
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const path=String(input);calls.push(path);
    if(path.endsWith("/start")||path.includes("/starts/")||path.endsWith("/conversations/accepted"))return json(current());
    if(path.endsWith("/cancel"))return json({...detail,turns:[{...turn,status:"cancelled",execution_terminated:false}]});
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    if(path.endsWith("/conversations"))return json([summary]);
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  vi.useFakeTimers({toFake:["setTimeout","clearTimeout"]});
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"질문 보내기"})));
  expect(screen.getByRole("button",{name:"상태 새로고침"})).toBeVisible();
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"작성 중인 후속 질문"}});
  try{
    await act(async()=>fireEvent.click(screen.getByRole("button",{name:"상태 새로고침"})));
    expect(calls.some(path=>path.endsWith("/conversations/accepted"))).toBe(true);
    expect(calls.filter(path=>path.endsWith("/cancel"))).toEqual([]);
    expect(calls.filter(path=>path.endsWith("/start"))).toHaveLength(1);
    expect(screen.getByRole("textbox",{name:"질문"})).toHaveValue("작성 중인 후속 질문");
    expect(screen.getByRole("heading",{name:"서버 제목"})).toBeVisible();
  }finally{
    finished=true;
    // Finish the owned polling job before RTL unmounts the screen. A real delay
    // can outlive a timed-out test and corrupt the next test's async act scope.
    await act(async()=>vi.advanceTimersByTimeAsync(2000));
  }
  expect(screen.queryByRole("button",{name:"상태 새로고침"})).not.toBeInTheDocument();
});

it.each(["cancel","unmount"])("F6 recovers outstanding acceptance after original POST404 through %s without abandoning a possibly bound draft",async(leave)=>{
  window.history.replaceState(null,"","/?draft=draft-one");
  let resolveStart!:(response:Response)=>void;let resolveLookup!:(response:Response)=>void;
  let lookups=0;const posts:Record<string,unknown>[]=[];const cancels:string[]=[];const deletes:string[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start")){
      posts.push(JSON.parse(String(init?.body)));
      return new Promise<Response>(resolve=>{resolveStart=resolve;});
    }
    if(path.includes("/starts/")){
      lookups++;if(lookups===1)return missing();
      return new Promise<Response>(resolve=>{resolveLookup=resolve;});
    }
    if(path.endsWith("/cancel")){cancels.push(path);return json({...detail,turns:[{...turn,status:"cancelled"}]});}
    if(init?.method==="DELETE"){deletes.push(path);return json({...openDraft,state:"abandoned"});}
    if(path.endsWith("/attachment-drafts/draft-one"))return json(openDraft);
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    return json([]);
  }));
  const view=render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  await screen.findByText(/미전송 첨부 초안/);
  vi.useFakeTimers({toFake:["setTimeout","clearTimeout"]});
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"질문 보내기"})));
  await act(async()=>vi.advanceTimersByTimeAsync(2000));
  expect(resolveLookup).toBeDefined();
  await act(async()=>resolveStart(json({error:{code:"not_found",message:"synthetic postcommit authority denial",correlation_id:"synthetic"}},404)));
  await act(async()=>{
    if(leave==="cancel"){
      fireEvent.click(screen.getByRole("button",{name:"첨부 초안 취소"}));
    }else view.unmount();
  });
  if(leave==="unmount"){
    window.history.replaceState(null,"","/");
    render(<ConversationPage domain={{...domain,id:"replacement-domain"}} initialWorkspaceIds={["workspace"]}/>);
  }
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"교체 화면 질문"}});
  await act(async()=>resolveLookup(json({...detail,turns:[{...turn,status:"running",execution_terminated:false}]})));
  expect(deletes).toHaveLength(0);
  expect(cancels).toEqual([`/api/v1/rag/domains/example/conversations/accepted/turns/${posts[0].request_id}/cancel`]);
  expect(posts).toHaveLength(1);
  expect(screen.getByRole("textbox",{name:"질문"})).toHaveValue("교체 화면 질문");
  expect(screen.queryByRole("heading",{name:"서버 제목"})).not.toBeInTheDocument();
  expect(new URL(location.href).searchParams.has("conversation")).toBe(false);
});

it.each([
  [404,"not_found"],
  [403,"forbidden"],
  [409,"unknown_rejection"],
  [403,"draft_upload_busy"],
])("F6 preserves original UUID and full payload on same-query Send after ambiguous POST%s/%s",async(status,code)=>{
  window.history.replaceState(null,"","/?draft=draft-one");
  const posts:Record<string,unknown>[]=[];let revision=3;let draftReads=0;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start")){
      posts.push(JSON.parse(String(init?.body)));
      return posts.length===1?json({error:{code,message:"synthetic ambiguous response",correlation_id:"synthetic"}},status):json(detail);
    }
    if(path.includes("/starts/"))return missing();
    if(path.endsWith("/attachment-drafts/draft-one")){draftReads++;return json({...openDraft,revision});}
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  await screen.findByText(/미전송 첨부 초안/);
  vi.useFakeTimers({toFake:["setTimeout","clearTimeout"]});
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"질문 보내기"})));
  expect(screen.getByRole("textbox",{name:"질문"})).toHaveValue("첫 질문");
  revision=9;const beforeRetry=draftReads;
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"질문 보내기"})));
  expect(posts).toHaveLength(2);expect(posts[1]).toEqual(posts[0]);
  expect(posts[1]).toMatchObject({draft_id:"draft-one",draft_revision:3});
  expect(draftReads).toBe(beforeRetry);
  expect(screen.getByRole("heading",{name:"서버 제목"})).toBeVisible();
});

it.each(["cancel", "unmount"])("F4 owns unchanged-question retry after transport409 through %s, lookup404 and late accepted-ID cancellation",async(leave)=>{
  window.history.replaceState(null,"","/?draft=draft-one");
  const posts:Record<string,unknown>[]=[];const cancels:string[]=[];const deletes:string[]=[];
  let resolveStart!:(response:Response)=>void;let accepted=false;let lookups=0;let acceptedLookups=0;let revision=3;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start")){
      posts.push(JSON.parse(String(init?.body)));
      if(posts.length===1)return deniedStart();
      return new Promise<Response>(resolve=>{resolveStart=resolve;});
    }
    if(path.includes("/starts/")){lookups++;if(accepted)acceptedLookups++;return accepted?json({...detail,turns:[{...turn,status:"running",execution_terminated:false}]}):missing();}
    if(path.endsWith("/cancel")){cancels.push(path);return json({...detail,turns:[{...turn,status:"cancelled"}]});}
    if(init?.method==="DELETE")deletes.push(path);
    if(path.endsWith("/attachment-drafts/draft-one"))return json({...openDraft,revision});
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    return json([]);
  }));
  const view=render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  await screen.findByText(/미전송 첨부 초안/);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  fireEvent.click(screen.getByRole("button",{name:"질문 보내기"}));
  await screen.findByText(/첨부 업로드의 서버 종료/);
  expect(screen.getByRole("textbox",{name:"질문"})).toHaveValue("첫 질문");
  revision=9;
  vi.useFakeTimers({toFake:["setTimeout","clearTimeout"]});
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"질문 보내기"})));
  expect(posts).toHaveLength(2);expect(resolveStart).toBeDefined();
  const beforeLeave=lookups;
  await act(async()=>{
    if(leave==="cancel"){
      fireEvent.click(screen.getByRole("button",{name:"답변 취소"}));
      fireEvent.click(screen.getByRole("button",{name:"새 대화"}));
    }else view.unmount();
  });
  if(leave==="unmount"){
    window.history.replaceState(null,"","/");
    render(<ConversationPage domain={{...domain,id:"replacement-domain"}} initialWorkspaceIds={["workspace"]}/>);
  }
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"교체 화면 질문"}});
  accepted=true;
  await act(async()=>vi.advanceTimersByTimeAsync(2000));
  const cancelsBeforeResponse=cancels.length;
  // Settle even the broken fixture before asserting, so no owner leaks into later mocks.
  await act(async()=>resolveStart(json(detail)));
  expect(cancelsBeforeResponse).toBe(1);expect(cancels).toHaveLength(1);expect(lookups).toBeGreaterThan(beforeLeave);
  expect(acceptedLookups).toBeGreaterThan(0);expect(deletes).toHaveLength(0);
  expect(cancels[0]).toBe(`/api/v1/rag/domains/example/conversations/accepted/turns/${posts[1].request_id}/cancel`);
  expect(posts[1]).toMatchObject({query:"첫 질문",draft_id:"draft-one",draft_revision:9});
  expect(posts[1].request_id).not.toBe(posts[0].request_id);
  expect(screen.getByRole("textbox",{name:"질문"})).toHaveValue("교체 화면 질문");
  expect(screen.queryByRole("heading",{name:"서버 제목"})).not.toBeInTheDocument();
  expect(new URL(location.href).searchParams.has("conversation")).toBe(false);
});

it("F4/F5 preserves uncertain original draft payload after retry409 and leaves through lookup404 without premature abandon",async()=>{
  window.history.replaceState(null,"","/?draft=draft-one");
  const posts:Record<string,unknown>[]=[];const deletes:string[]=[];const cancels:string[]=[];
  let accepted=false;let reads=0;let revision=3;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start")){
      posts.push(JSON.parse(String(init?.body)));
      if(posts.length===1)throw new TypeError("synthetic response loss");
      return deniedStart();
    }
    if(path.includes("/starts/"))return accepted?json(detail):missing();
    if(path.endsWith("/cancel")){cancels.push(path);return json({...detail,turns:[{...turn,status:"cancelled"}]});}
    if(init?.method==="DELETE"){deletes.push(path);return json({...openDraft,state:"abandoned"});}
    if(path.endsWith("/attachment-drafts/draft-one")){reads++;return json({...openDraft,revision});}
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  await screen.findByText(/미전송 첨부 초안/);
  vi.useFakeTimers({toFake:["setTimeout","clearTimeout"]});
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"질문 보내기"})));
  revision=9;
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"같은 질문 다시 시도"})));
  const beforeLeave=reads;
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"새 대화"})));
  expect(reads).toBe(beforeLeave);expect(deletes).toHaveLength(0);
  accepted=true;
  await act(async()=>vi.advanceTimersByTimeAsync(2000));
  expect(posts).toHaveLength(2);expect(posts[1]).toEqual(posts[0]);
  expect(posts[1]).toMatchObject({draft_id:"draft-one",draft_revision:3});
  expect(cancels).toEqual([`/api/v1/rag/domains/example/conversations/accepted/turns/${posts[0].request_id}/cancel`]);
  expect(deletes).toHaveLength(0);
  expect(new URL(location.href).searchParams.has("conversation")).toBe(false);
});

it.each(["새 대화","첨부 초안 취소"])("F5 abandons definitively denied draft once at latest revision through %s while preserving originals",async(control)=>{
  window.history.replaceState(null,"","/?draft=draft-one");
  const mutations:string[]=[];let reads=0;let revision=3;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(init?.method)mutations.push(path);
    if(path.endsWith("/start"))return deniedStart();
    if(init?.method==="DELETE")return json({...openDraft,state:"abandoned",revision:10});
    if(path.endsWith("/attachment-drafts/draft-one")){reads++;return json({...openDraft,revision});}
    if(path.includes("/starts/"))return missing();
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  await screen.findByText(/미전송 첨부 초안/);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  fireEvent.click(screen.getByRole("button",{name:"질문 보내기"}));
  await screen.findByText(/첨부 업로드의 서버 종료/);
  revision=9;const beforeLeave=reads;
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:control})));
  expect(reads-beforeLeave).toBe(1);
  expect(mutations.filter(path=>path.includes("?expected_revision="))).toEqual(["/api/v1/rag/domains/example/attachment-drafts/draft-one?expected_revision=9"]);
  expect(mutations.some(path=>path.includes("/documents/"))).toBe(false);
  expect(new URL(location.href).searchParams.has("draft")).toBe(false);
});

it.each(["open","bound"])("F5 defers explicit abandon until pending POST becomes rejected and respects latest %s draft",async(state)=>{
  window.history.replaceState(null,"","/?draft=draft-one");
  let resolveStart!:(response:Response)=>void;let left=false;const deletes:string[]=[];let dispositionReads=0;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start"))return new Promise<Response>(resolve=>{resolveStart=resolve;});
    if(path.includes("/starts/"))return missing();
    if(init?.method==="DELETE"){deletes.push(path);return json({...openDraft,state:"abandoned",revision:10});}
    if(path.endsWith("/attachment-drafts/draft-one")){
      if(left)dispositionReads++;
      return json(left?{...openDraft,state,revision:9,bound_conversation_id:state==="bound"?"accepted":null}:openDraft);
    }
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  await screen.findByText(/미전송 첨부 초안/);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"질문 보내기"})));
  expect(resolveStart).toBeDefined();left=true;
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"새 대화"})));
  expect(dispositionReads).toBe(0);expect(deletes).toHaveLength(0);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"교체 화면 질문"}});
  await act(async()=>resolveStart(deniedStart()));
  expect(dispositionReads).toBe(1);
  expect(deletes).toEqual(state==="open"?["/api/v1/rag/domains/example/attachment-drafts/draft-one?expected_revision=9"]:[]);
  expect(screen.getByRole("textbox",{name:"질문"})).toHaveValue("교체 화면 질문");
});

it.each([false,true])("F5 attributes deferred rejection abandon failure only to its initiating empty screen (replacement selected=%s)",async(selected)=>{
  window.history.replaceState(null,"","/?draft=draft-one");
  let resolveStart!:(response:Response)=>void;let rejectAbandon!:(error:Error)=>void;let deletes=0;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start"))return new Promise<Response>(resolve=>{resolveStart=resolve;});
    if(path.includes("/starts/"))return missing();
    if(init?.method==="DELETE"){deletes++;return new Promise<Response>((_resolve,reject)=>{rejectAbandon=reject;});}
    if(path.endsWith("/attachment-drafts/draft-one"))return json(openDraft);
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    if(path.endsWith("/conversations"))return json([summary]);
    if(path.endsWith("/conversations/accepted"))return json(detail);
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  await screen.findByText(/미전송 첨부 초안/);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"질문 보내기"})));
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"새 대화"})));
  await act(async()=>resolveStart(deniedStart()));
  expect(deletes).toBe(1);expect(rejectAbandon).toBeDefined();
  if(selected){
    fireEvent.click(screen.getByRole("button",{name:"서버 제목"}));
    await screen.findByRole("heading",{name:"서버 제목"});
  }
  await act(async()=>rejectAbandon(new TypeError("synthetic abandon failure")));
  const failure=screen.queryByText("이전 첨부 초안의 포기를 확인하지 못했습니다. 원본 파일은 보존됩니다.");
  if(selected)expect(failure).not.toBeInTheDocument();else expect(failure).toBeVisible();
  expect(deletes).toBe(1);
});

it("visits and starts new screens without mutations, then accepts first question through one start and follows up through turns",async()=>{
  const mutations:Array<{path:string;body:Record<string,unknown>}> = [];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(init?.method==="POST") {mutations.push({path,body:JSON.parse(String(init.body))});return json(detail);}
    if(path.endsWith("/folders")||path.endsWith("/conversations"))return json([]);
    throw new Error(`Unexpected GET ${path}`);
  }));
  render(<StrictMode><ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/></StrictMode>);
  fireEvent.click(screen.getByRole("button",{name:"새 대화"}));
  expect(mutations).toHaveLength(0);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  fireEvent.click(screen.getByRole("button",{name:"질문 보내기"}));
  await screen.findByRole("heading",{name:"서버 제목"});
  expect(mutations).toHaveLength(1);
  expect(mutations[0].path).toBe("/api/v1/rag/domains/example/conversations/start");
  expect(mutations[0].body).not.toHaveProperty("expected_revision");
  expect(new URL(location.href).searchParams.get("conversation")).toBe("accepted");
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"후속 질문"}});
  fireEvent.click(screen.getByRole("button",{name:"질문 보내기"}));
  await waitFor(()=>expect(mutations).toHaveLength(2));
  expect(mutations[1].path).toBe("/api/v1/rag/domains/example/conversations/accepted/turns");
  expect(mutations[1].body.expected_revision).toBe(1);
});

it("preserves the entire original start payload on explicit retry after response loss",async()=>{
  const requests:unknown[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start")){requests.push(JSON.parse(String(init?.body)));if(requests.length===1)throw new TypeError("lost");return json(detail);}
    if(path.includes("/starts/"))return missing();
    if(init?.method)throw new Error(`Unexpected mutation ${path}`);
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  fireEvent.click(screen.getByRole("button",{name:"질문 보내기"}));
  fireEvent.click(await screen.findByRole("button",{name:"같은 질문 다시 시도"}));
  await screen.findByRole("heading",{name:"서버 제목"});
  expect(requests).toHaveLength(2);expect(requests[1]).toEqual(requests[0]);
});

it("waits through an unaccepted cancel lookup and cancels exactly once after late acceptance without replacing a new screen",async()=>{
  let resolveStart!:(value:Response)=>void;
  let accepted=false;let lookups=0;const cancels:string[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start"))return new Promise<Response>(resolve=>{resolveStart=resolve;});
    if(path.includes("/starts/")){lookups++;return accepted?json(detail):missing();}
    if(path.endsWith("/cancel")){cancels.push(path);return json({...detail,turns:[{...turn,status:"cancelled"}]});}
    if(init?.method)throw new Error(`Unexpected mutation ${path}`);
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  fireEvent.click(screen.getByRole("button",{name:"질문 보내기"}));
  await waitFor(()=>expect(resolveStart).toBeDefined());
  fireEvent.click(screen.getByRole("button",{name:"답변 취소"}));
  await waitFor(()=>expect(lookups).toBeGreaterThan(0));
  expect(screen.queryByText("답변 생성을 취소했습니다.")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"새 대화"}));
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"새 화면 질문"}});
  accepted=true;
  await waitFor(()=>expect(cancels).toHaveLength(1),{timeout:4000});
  expect(lookups).toBeGreaterThan(1);
  await act(async()=>{resolveStart(json(detail));});
  expect(cancels).toHaveLength(1);
  expect(cancels[0]).toContain("/accepted/turns/");
  expect(screen.getByRole("textbox",{name:"질문"})).toHaveValue("새 화면 질문");
  expect(new URL(location.href).searchParams.has("conversation")).toBe(false);
});

it("restores a server draft without creating a conversation or another draft",async()=>{
  window.history.replaceState(null,"","/?draft=draft-one");const mutations:string[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);if(init?.method)mutations.push(path);
    if(path.endsWith("/attachment-drafts/draft-one"))return json({id:"draft-one",state:"open",revision:3,created_at:"2026-09-30",updated_at:"2026-09-30",expires_at:"2026-10-01",bound_conversation_id:null,legacy_conversation_id:null});
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  expect(await screen.findByText(/미전송 첨부 초안/)).toBeVisible();expect(mutations).toHaveLength(0);
});

it("discovers accepted server title and running turn while the original start POST is still pending",async()=>{
  let resolveStart!:(value:Response)=>void;let starts=0;let lookups=0;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start")){starts++;return new Promise<Response>(resolve=>{resolveStart=resolve;});}
    if(path.includes("/starts/")){lookups++;return json({...detail,turns:[{...turn,status:"running",execution_terminated:false}]});}
    if(init?.method)throw new Error(`Unexpected mutation ${path}`);
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  fireEvent.click(screen.getByRole("button",{name:"질문 보내기"}));
  await screen.findByRole("heading",{name:"서버 제목"});
  expect(lookups).toBeGreaterThan(0);expect(starts).toBe(1);
  expect(new URL(location.href).searchParams.get("conversation")).toBe("accepted");
  expect(screen.getByRole("button",{name:"질문 보내기"})).toBeDisabled();
  await act(async()=>resolveStart(json(detail)));
  expect(await screen.findByText(/응답 시간이 초과/)).toBeVisible();
});

it("creates only one draft for actual file selection, serializes reservations, reads latest revision before first start and abandons an open draft",async()=>{
  let revision=1;const uploads:number[]=[];let creates=0;const starts:Record<string,unknown>[]=[];let abandoned=false;
  const current=()=>({id:"draft-one",state:abandoned?"abandoned":"open",revision,created_at:"2026-09-30",updated_at:"2026-09-30",expires_at:"2026-10-01",bound_conversation_id:null,legacy_conversation_id:null});
  const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("attachment-options"))return json({workspaces:[{id:"workspace",name:"자료",kind:"personal"}],reason_code:null});
    if(path.endsWith("/attachment-drafts")&&init?.method==="POST"){creates++;return json(current());}
    if(path.includes("/attachment-drafts/draft-one/attachments?")&&init?.method==="POST"){
      const expected=Number(new URL(path,"http://local").searchParams.get("expected_revision"));uploads.push(expected);if(expected!==revision)throw new Error("bad revision");revision++;
      return json({id:`file-${revision}`,document:null,status:"failed",error_code:"attachment_processing_failed",excluded_at:null});
    }
    if(path.includes("/attachment-drafts/draft-one?")&&init?.method==="DELETE"){expect(path).toContain(`expected_revision=${revision}`);abandoned=true;revision++;return json(current());}
    if(path.endsWith("/attachment-drafts/draft-one"))return json(current());
    if(path.endsWith("/start")){starts.push(JSON.parse(String(init?.body)));return json(detail);}
    if(path.includes("/starts/"))return missing();
    if(init?.method)throw new Error(`Unexpected mutation ${path}`);
    return json([]);
  });vi.stubGlobal("fetch",fetcher);
  const view=render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  fireEvent.change(screen.getByLabelText("대화에 파일 첨부"),{target:{files:[new File(["synthetic"],"one.txt"),new File(["synthetic"],"two.txt")]}});
  fireEvent.submit(screen.getByRole("textbox",{name:"질문"}).closest("form")!);
  expect(starts).toHaveLength(0);
  await waitFor(()=>expect(uploads).toEqual([1,2]));
  await waitFor(()=>expect(screen.getByRole("button",{name:"질문 보내기"})).toBeEnabled());
  expect(creates).toBe(1);expect(new URL(location.href).searchParams.get("draft")).toBe("draft-one");
  fireEvent.click(screen.getByRole("button",{name:"질문 보내기"}));
  await screen.findByRole("heading",{name:"서버 제목"});
  expect(starts[0]).toMatchObject({draft_id:"draft-one",draft_revision:3});
  expect(new URL(location.href).searchParams.has("draft")).toBe(false);
  view.unmount();window.history.replaceState(null,"","/?draft=draft-one");
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  fireEvent.click(await screen.findByRole("button",{name:"첨부 초안 취소"}));
  await waitFor(()=>expect(abandoned).toBe(true));
  expect(fetcher.mock.calls.some(([input,init])=>String(input).includes("/documents/")&&init?.method==="DELETE")).toBe(false);
});

it("guards duplicate submits synchronously before a deterministic server denial",async()=>{
  const starts:Record<string,unknown>[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start")){starts.push(JSON.parse(String(init?.body)));return starts.length===1?json({error:{code:"selected_documents_not_ready",message:"synthetic",correlation_id:"synthetic"}},409):json(detail);}
    if(path.includes("/starts/"))return missing();return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  const form=screen.getByRole("textbox",{name:"질문"}).closest("form")!;
  await act(async()=>{fireEvent.submit(form);fireEvent.submit(form);});
  await screen.findByRole("alert");expect(starts).toHaveLength(1);
  // This test only proves the synchronous submit guard before deterministic denial;
  // existing scope-selector tests cover the subsequent explicit revision controls.
});

it.each(["expired","abandoned"])("explains a %s draft, preserves originals and permits an explicit new screen",async(state)=>{
  window.history.replaceState(null,"","/?draft=closed-draft");const mutations:string[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);if(init?.method)mutations.push(path);
    if(path.endsWith("/attachment-drafts/closed-draft"))return json({id:"closed-draft",state,revision:2,created_at:"2026-09-30",updated_at:"2026-09-30",expires_at:"2026-09-30",bound_conversation_id:null,legacy_conversation_id:null});
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("원본 파일은 보존됩니다");
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"새 질문"}});
  expect(screen.getByRole("button",{name:"질문 보내기"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"새 대화"}));
  expect(new URL(location.href).searchParams.has("draft")).toBe(false);expect(mutations).toHaveLength(0);
});

it("redirects a bound draft to its accepted conversation without a mutation",async()=>{
  window.history.replaceState(null,"","/?draft=bound-draft");const mutations:string[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);if(init?.method)mutations.push(path);
    if(path.endsWith("/attachment-drafts/bound-draft"))return json({id:"bound-draft",state:"bound",revision:2,created_at:"2026-09-30",updated_at:"2026-09-30",expires_at:"2026-10-01",bound_conversation_id:"accepted",legacy_conversation_id:null});
    if(path.endsWith("/conversations/accepted"))return json(detail);return json([]);
  }));
  render(<ConversationPage domain={domain}/>);
  await screen.findByRole("heading",{name:"서버 제목"});expect(new URL(location.href).searchParams.get("conversation")).toBe("accepted");expect(new URL(location.href).searchParams.has("draft")).toBe(false);expect(mutations).toHaveLength(0);
});

it("shows legacy writer-busy reason, retries restoration explicitly and never writes a legacy turn",async()=>{
  window.history.replaceState(null,"","/?conversation=legacy");let restores=0;const mutations:string[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);if(init?.method)mutations.push(path);
    if(path.endsWith("/conversations/legacy"))return json({...summary,id:"legacy",legacy_state:"draft",turns:[]});
    if(path.endsWith("/restore-draft")){restores++;return restores===1?json({error:{code:"legacy_upload_busy",message:"busy",correlation_id:"synthetic"}},409):json({id:"legacy-draft",state:"open",revision:1,created_at:"2026-09-30",updated_at:"2026-09-30",expires_at:"2026-10-01",bound_conversation_id:null,legacy_conversation_id:"legacy"});}
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});return json([]);
  }));
  render(<ConversationPage domain={domain}/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("legacy_upload_busy");
  fireEvent.click(screen.getByRole("button",{name:"초안 상태 새로고침"}));
  await screen.findByText(/미전송 첨부 초안/);expect(restores).toBe(2);expect(mutations.every(path=>path.endsWith("restore-draft"))).toBe(true);
});

it("replaces cached titles with the current permission-redacted server list title",async()=>{
  let redacted=false;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>String(input).endsWith("/conversations")?json([{...summary,title:redacted?"접근할 수 없는 대화":"서버 제목"}]):json([])));
  render(<ConversationPage domain={domain}/>);
  await screen.findByRole("button",{name:"서버 제목"});redacted=true;
  fireEvent.click(screen.getByRole("button",{name:"대화 목록 새로고침"}));
  await screen.findByRole("button",{name:"접근할 수 없는 대화"});expect(screen.queryByRole("button",{name:"서버 제목"})).not.toBeInTheDocument();
});

it("permits an explicit new screen after the real draft GET returns gone",async()=>{
  window.history.replaceState(null,"","/?draft=gone");
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>String(input).endsWith("/attachment-drafts/gone")?json({error:{code:"draft_unavailable",message:"synthetic",correlation_id:"synthetic"}},410):json([])));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("원본 파일은 보존됩니다");
  expect(screen.getByRole("button",{name:"새 대화"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"새 대화"}));
  expect(new URL(location.href).searchParams.has("draft")).toBe(false);
});

it("F1 ignores a failed abandon owned by an earlier new screen after another conversation is selected",async()=>{
  window.history.replaceState(null,"","/?draft=old-draft");
  let rejectAbandon!:(error:Error)=>void;
  const draft={id:"old-draft",state:"open",revision:1,created_at:"2026-09-30",updated_at:"2026-09-30",expires_at:"2026-10-01",bound_conversation_id:null,legacy_conversation_id:null};
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(init?.method==="DELETE")return new Promise<Response>((_resolve,reject)=>{rejectAbandon=reject;});
    if(path.endsWith("/attachment-drafts/old-draft"))return json(draft);
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    if(path.endsWith("/conversations"))return json([detail]);
    if(path.endsWith("/conversations/accepted"))return json(detail);return json([]);
  }));
  render(<ConversationPage domain={domain}/>);
  await screen.findByText(/미전송 첨부 초안/);
  fireEvent.click(screen.getByRole("button",{name:"새 대화"}));
  await waitFor(()=>expect(rejectAbandon).toBeDefined());
  fireEvent.click(screen.getByRole("button",{name:"서버 제목"}));
  await screen.findByRole("heading",{name:"서버 제목"});
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"현재 화면 질문"}});
  await act(async()=>rejectAbandon(new TypeError("synthetic abandon failure")));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox",{name:"질문"})).toHaveValue("현재 화면 질문");
  expect(new URL(location.href).searchParams.get("conversation")).toBe("accepted");
});

it("F1 still attributes abandon failure to the initiating new screen",async()=>{
  window.history.replaceState(null,"","/?draft=old-draft");
  const draft={id:"old-draft",state:"open",revision:1,created_at:"2026-09-30",updated_at:"2026-09-30",expires_at:"2026-10-01",bound_conversation_id:null,legacy_conversation_id:null};
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(init?.method==="DELETE")throw new TypeError("synthetic abandon failure");
    if(path.endsWith("/attachment-drafts/old-draft"))return json(draft);
    if(path.endsWith("attachment-options"))return json({workspaces:[],reason_code:null});
    return json([]);
  }));
  render(<ConversationPage domain={domain}/>);
  await screen.findByText(/미전송 첨부 초안/);
  fireEvent.click(screen.getByRole("button",{name:"새 대화"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("이전 첨부 초안의 포기를 확인하지 못했습니다. 원본 파일은 보존됩니다.");
});

it.each(["question","file"])("F1 ignores an old abandon failure after the new screen creates a %s context",async(context)=>{
  window.history.replaceState(null,"","/?draft=old-draft");
  let rejectAbandon!:(error:Error)=>void;
  const oldDraft={id:"old-draft",state:"open",revision:1,created_at:"2026-09-30",updated_at:"2026-09-30",expires_at:"2026-10-01",bound_conversation_id:null,legacy_conversation_id:null};
  const newDraft={...oldDraft,id:"new-draft"};
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(init?.method==="DELETE")return new Promise<Response>((_resolve,reject)=>{rejectAbandon=reject;});
    if(path.endsWith("/attachment-drafts/old-draft"))return json(oldDraft);
    if(path.endsWith("attachment-options"))return json({workspaces:[{id:"workspace",name:"자료",kind:"personal"}],reason_code:null});
    if(path.endsWith("/attachment-drafts")&&init?.method==="POST")return json(newDraft);
    if(path.endsWith("/attachment-drafts/new-draft"))return json(newDraft);
    if(path.includes("/attachments?")&&init?.method==="POST")return json({id:"file",document:null,status:"failed",error_code:"attachment_processing_failed",excluded_at:null});
    if(path.endsWith("/start"))return json(detail);
    if(path.includes("/starts/"))return missing();return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  await screen.findByText(/미전송 첨부 초안/);
  fireEvent.click(screen.getByRole("button",{name:"새 대화"}));
  await waitFor(()=>expect(rejectAbandon).toBeDefined());
  if(context==="question"){
    fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"Replacement question"}});
    fireEvent.click(screen.getByRole("button",{name:"질문 보내기"}));
    await screen.findByRole("heading",{name:"서버 제목"});
  }else{
    fireEvent.change(screen.getByLabelText("대화에 파일 첨부"),{target:{files:[new File(["synthetic"],"replacement.txt")]}});
    await waitFor(()=>expect(new URL(location.href).searchParams.get("draft")).toBe("new-draft"));
  }
  await act(async()=>rejectAbandon(new TypeError("synthetic abandon failure")));
  expect(screen.queryByText("이전 첨부 초안의 포기를 확인하지 못했습니다. 원본 파일은 보존됩니다.")).not.toBeInTheDocument();
  expect(new URL(location.href).searchParams.get(context==="question"?"conversation":"draft")).toBe(context==="question"?"accepted":"new-draft");
});

it("F2 preserves accepted-ID cancellation after actual start AbortSignal rejection and component unmount with lookup404",async()=>{
  let accepted=false;let lookups=0;let aborted=false;const posts:Record<string,unknown>[]=[];const cancels:string[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith("/start")){
      posts.push(JSON.parse(String(init?.body)));
      return new Promise<Response>((_resolve,reject)=>{init?.signal?.addEventListener("abort",()=>{aborted=true;reject(new DOMException("synthetic abort","AbortError"));},{once:true});});
    }
    if(path.includes("/starts/")){lookups++;return accepted?json({...detail,turns:[{...turn,status:"running",execution_terminated:false}]}):missing();}
    if(path.endsWith("/cancel")){cancels.push(path);return json({...detail,turns:[{...turn,status:"cancelled"}]});}
    return json([]);
  }));
  const view=render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"첫 질문"}});
  fireEvent.click(screen.getByRole("button",{name:"질문 보내기"}));
  await waitFor(()=>expect(lookups).toBeGreaterThan(0));
  await act(async()=>view.unmount());expect(aborted).toBe(true);
  window.history.replaceState(null,"","/");
  render(<ConversationPage domain={{...domain,id:"replacement-domain"}} initialWorkspaceIds={["workspace"]}/>);
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"교체 화면 질문"}});
  accepted=true;
  await waitFor(()=>expect(cancels).toHaveLength(1),{timeout:4000});
  expect(posts).toHaveLength(1);expect(posts[0]).toMatchObject({query:"첫 질문",workspace_ids:["workspace"]});
  expect(cancels[0]).toBe(`/api/v1/rag/domains/example/conversations/accepted/turns/${posts[0].request_id}/cancel`);
  expect(lookups).toBeGreaterThan(1);expect(screen.getByRole("textbox",{name:"질문"})).toHaveValue("교체 화면 질문");
  expect(screen.queryByRole("heading",{name:"서버 제목"})).not.toBeInTheDocument();
  expect(new URL(location.href).searchParams.has("conversation")).toBe(false);
},10000);

it.each([true,false])("F3 reconciles selected title, editor and first-turn redaction after authoritative list change (editor already open=%s)",async(openEditor)=>{
  window.history.replaceState(null,"","/?conversation=accepted");
  let redacted=false;let details=0;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const path=String(input);
    if(path.endsWith("/conversations"))return json([{...summary,title:redacted?"접근할 수 없는 대화":"서버 제목"}]);
    if(path.endsWith("/conversations/accepted")){details++;return json(redacted?{...detail,title:"접근할 수 없는 대화",turns:[{...turn,query:"",redacted:true,request_scope:null}]}:detail);}
    return json([]);
  }));
  render(<ConversationPage domain={domain}/>);
  await screen.findByRole("heading",{name:"서버 제목"});expect(screen.getByText("첫 질문")).toBeVisible();
  if(openEditor){fireEvent.click(screen.getByRole("button",{name:"대화 이름 변경"}));fireEvent.change(screen.getByRole("textbox",{name:"대화 제목"}),{target:{value:"보존하면 안 되는 편집 캐시"}});}
  redacted=true;fireEvent.click(screen.getByRole("button",{name:"대화 목록 새로고침"}));
  await screen.findByRole("heading",{name:"접근할 수 없는 대화"});
  await screen.findByText("현재 권한으로 이 대화 내용을 표시할 수 없습니다.");
  if(!openEditor)fireEvent.click(screen.getByRole("button",{name:"대화 이름 변경"}));
  expect(screen.getByRole("textbox",{name:"대화 제목"})).toHaveValue("접근할 수 없는 대화");
  expect(screen.queryByText("첫 질문")).not.toBeInTheDocument();
  expect(details).toBe(2);
});

it("F3 preserves an unchanged manual title and dirty editor on ordinary authoritative refresh",async()=>{
  window.history.replaceState(null,"","/?conversation=accepted");
  let details=0;
  const manual={...detail,title:"Manual server title",title_origin:"manual"};
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const path=String(input);
    if(path.endsWith("/conversations"))return json([manual]);
    if(path.endsWith("/conversations/accepted")){details++;return json(manual);}
    return json([]);
  }));
  render(<ConversationPage domain={domain}/>);
  await screen.findByRole("heading",{name:"Manual server title"});
  fireEvent.click(screen.getByRole("button",{name:"대화 이름 변경"}));
  fireEvent.change(screen.getByRole("textbox",{name:"대화 제목"}),{target:{value:"Unsaved manual edit"}});
  fireEvent.click(screen.getByRole("button",{name:"대화 목록 새로고침"}));
  await waitFor(()=>expect(details).toBe(2));
  expect(screen.getByRole("heading",{name:"Manual server title"})).toBeVisible();
  expect(screen.getByRole("textbox",{name:"대화 제목"})).toHaveValue("Unsaved manual edit");
  expect(screen.getByText("첫 질문")).toBeVisible();
});

it("F3 fences delayed detail revalidation after switching to a new screen",async()=>{
  window.history.replaceState(null,"","/?conversation=accepted");
  let details=0;let resolveDetail!:(response:Response)=>void;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const path=String(input);
    if(path.endsWith("/conversations"))return json([summary]);
    if(path.endsWith("/conversations/accepted")){
      details++;if(details===1)return json(detail);
      return new Promise<Response>(resolve=>{resolveDetail=resolve;});
    }
    return json([]);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]}/>);
  await screen.findByRole("heading",{name:"서버 제목"});
  fireEvent.click(screen.getByRole("button",{name:"대화 목록 새로고침"}));
  await waitFor(()=>expect(resolveDetail).toBeDefined());
  fireEvent.click(screen.getByRole("button",{name:"새 대화"}));
  fireEvent.change(screen.getByRole("textbox",{name:"질문"}),{target:{value:"Replacement question"}});
  await act(async()=>resolveDetail(json({...detail,title:"접근할 수 없는 대화",turns:[{...turn,query:"",redacted:true,request_scope:null}]})));
  expect(screen.queryByRole("heading",{name:"접근할 수 없는 대화"})).not.toBeInTheDocument();
  expect(screen.queryByText("첫 질문")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox",{name:"질문"})).toHaveValue("Replacement question");
  expect(new URL(location.href).searchParams.has("conversation")).toBe(false);
  expect(screen.getByRole("button",{name:"질문 보내기"})).toBeEnabled();
});
