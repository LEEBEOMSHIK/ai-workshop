import {fireEvent,render,screen,within,act} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {beforeEach,afterEach,expect,it,vi} from "vitest";
import {AdminShell} from "./AdminShell";
const route=vi.hoisted(()=>({path:"/admin/system/issues/detail"}));
vi.mock("next/navigation",()=>({usePathname:()=>route.path}));
const owner={id:"owner",display_name:"Owner",email:"owner@example.test",role:"owner" as const};
let mobile=false;
const listeners=new Set<()=>void>();
beforeEach(()=>{
 mobile=false;route.path="/admin/system/issues/detail";
 vi.stubGlobal("matchMedia",vi.fn(()=>({get matches(){return mobile;},addEventListener:(_name:string,cb:()=>void)=>listeners.add(cb),removeEventListener:(_name:string,cb:()=>void)=>listeners.delete(cb)})));
 HTMLDialogElement.prototype.showModal=function(){this.open=true;this.querySelector<HTMLElement>('button')?.focus();};
 HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new Event("close"));};
});
afterEach(()=>{listeners.clear();vi.unstubAllGlobals();document.body.style.overflow="";});
it("groups desktop administration and marks the active deep route",()=>{
 render(<AdminShell user={owner}><p>Page content</p></AdminShell>);
 const navigation=screen.getByRole("navigation",{name:"관리자 운영"});
 expect(within(navigation).getByText("RAG 관리")).toBeVisible();expect(within(navigation).getByText("공개 콘텐츠")).toBeVisible();expect(within(navigation).getByText("시스템 관리")).toBeVisible();
 expect(within(navigation).getByRole("link",{name:"문제 및 개선 이력"})).toHaveAttribute("aria-current","page");
 expect(screen.getByText("Page content")).toBeVisible();
});
it("opens the mobile drawer and closes even after clicking the current link",async()=>{
 mobile=true;const user=userEvent.setup();render(<AdminShell user={owner}><p>Content</p></AdminShell>);
 const trigger=screen.getByRole("button",{name:"메뉴 열기"});await user.click(trigger);
 const dialog=screen.getByRole("dialog",{name:"관리자 메뉴"});expect(dialog).toHaveAttribute("open");expect(document.body.style.overflow).toBe("hidden");
 expect(within(dialog).getByRole("navigation",{name:"영역 이동"})).toBeVisible();
 const currentLink=within(dialog).getByRole("link",{name:"문제 및 개선 이력"});
 currentLink.addEventListener("click",event=>event.preventDefault());
 await user.click(currentLink);
 expect(dialog).not.toHaveAttribute("open");expect(trigger).toHaveFocus();expect(document.body.style.overflow).toBe("");
});
it("handles native Escape cancellation and restores trigger focus",async()=>{
 mobile=true;const user=userEvent.setup();render(<AdminShell user={owner}/>);const trigger=screen.getByRole("button",{name:"메뉴 열기"});await user.click(trigger);
 const dialog=screen.getByRole("dialog");fireEvent(dialog,new Event("cancel",{cancelable:true}));
 expect(dialog).not.toHaveAttribute("open");expect(trigger).toHaveFocus();
});
it("closes the drawer when navigating or resizing to desktop",async()=>{
 mobile=true;const user=userEvent.setup();const {rerender}=render(<AdminShell user={owner}/>);
 await user.click(screen.getByRole("button",{name:"메뉴 열기"}));route.path="/admin/rag/models";rerender(<AdminShell user={owner}/>);expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
 await user.click(screen.getByRole("button",{name:"메뉴 열기"}));act(()=>{mobile=false;listeners.forEach(cb=>cb());});
 expect(screen.queryByRole("dialog")).not.toBeInTheDocument();expect(document.body.style.overflow).toBe("");
 expect(screen.getByRole("navigation",{name:"관리자 운영"})).toBeVisible();
});
it("does not expose owner administration to other roles",()=>{
 render(<AdminShell user={{...owner,role:"member"}}><p>Private admin content</p></AdminShell>);
 expect(screen.queryByRole("navigation",{name:"관리자 운영"})).not.toBeInTheDocument();expect(screen.queryByText("Private admin content")).not.toBeInTheDocument();
});
it("logs out once before navigating to login and keeps pending actions disabled",async()=>{
 const replace=vi.fn();let complete!:(response:Response)=>void;
 const request=vi.fn<typeof fetch>().mockImplementation(()=>new Promise(resolve=>{complete=resolve;}));
 vi.stubGlobal("fetch",request);
 vi.stubGlobal("window",new Proxy(window,{get(target,key){return key==="location"?{replace}:Reflect.get(target,key);}}));
 const user=userEvent.setup();render(<AdminShell user={owner}/>);
 await user.click(screen.getByRole("button",{name:"로그아웃"}));
 const pending=screen.getByRole("button",{name:"로그아웃 중…"});expect(pending).toBeDisabled();
 await user.click(pending);expect(request).toHaveBeenCalledTimes(1);expect(replace).not.toHaveBeenCalled();
 await act(async()=>complete(new Response(null,{status:204})));
 expect(replace).toHaveBeenCalledWith("/login");
});
it("shows logout failure without leaving administration",async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(null,{status:500})));
 const user=userEvent.setup();render(<AdminShell user={owner}/>);
 await user.click(screen.getByRole("button",{name:"로그아웃"}));
 expect(await screen.findByRole("alert")).toHaveTextContent("다시 시도");expect(screen.getByRole("button",{name:"로그아웃"})).toBeEnabled();
});
it("wraps Tab and Shift+Tab within the open drawer",async()=>{
 mobile=true;const user=userEvent.setup();render(<AdminShell user={owner}/>);
 await user.click(screen.getByRole("button",{name:"메뉴 열기"}));
 const dialog=screen.getByRole("dialog");
 const first=within(dialog).getByRole("link",{name:"AI Workshop"});const last=within(dialog).getByRole("button",{name:"로그아웃"});
 first.focus();await user.tab({shift:true});expect(last).toHaveFocus();
 await user.tab();expect(first).toHaveFocus();
});
