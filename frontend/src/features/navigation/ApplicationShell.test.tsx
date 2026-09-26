import {render,screen,within} from "@testing-library/react";
import {expect,it,vi} from "vitest";
import {fireEvent} from "@testing-library/react";
import {useUnsavedChanges} from "../learning/useUnsavedChanges";
import {ApplicationShell} from "./ApplicationShell";
const route=vi.hoisted(()=>({path:"/"}));
vi.mock("next/navigation",()=>({usePathname:()=>route.path}));
const owner={id:"owner",display_name:"Owner",email:"owner@example.test",role:"owner" as const};
it("shows public navigation without exposing a supplied private identity",()=>{
 render(<ApplicationShell area="public" user={owner}><p>Public page</p></ApplicationShell>);
 expect(screen.getByRole("navigation",{name:"공개 전시실"})).toBeVisible();
 expect(screen.queryByRole("link",{name:"관리자"})).not.toBeInTheDocument();expect(screen.queryByText("Owner")).not.toBeInTheDocument();expect(screen.queryByRole("button",{name:"로그아웃"})).not.toBeInTheDocument();
 expect(screen.getByText("Public page")).toBeVisible();
});
it.each([["/", "홈"],["/labs","AI Labs"],["/labs/rag","RAG 실험실"],["/labs/rag/studies","공개 연구"],["/studies/example","공개 연구"]])("selects only the most specific public item for %s",(path,label)=>{
 route.path=path;render(<ApplicationShell area="public"/>);
 const nav=screen.getByRole("navigation",{name:"공개 전시실"});
 expect(within(nav).getByRole("link",{name:label})).toHaveAttribute("aria-current","page");expect(within(nav).getAllByRole("link").filter(link=>link.getAttribute("aria-current")==="page")).toHaveLength(1);
});
it("uses the shared shell for members and highlights domain files",()=>{
 route.path="/workshop/rag/domains/example/files";render(<ApplicationShell area="workspace" user={{...owner,role:"member"}}><p>Private content</p></ApplicationShell>);
 expect(screen.getByRole("link",{name:"파일함"})).toHaveAttribute("aria-current","page");expect(screen.queryByRole("link",{name:"관리자"})).not.toBeInTheDocument();expect(screen.queryByText("마스터")).not.toBeInTheDocument();
});
it("does not render protected content without a user",()=>{
 render(<ApplicationShell area="workspace"><p>Private content</p></ApplicationShell>);expect(screen.queryByText("Private content")).not.toBeInTheDocument();
});
function DirtyContent(){useUnsavedChanges(true);return <textarea aria-label="Unsaved draft" defaultValue="Keep this draft"/>;}
it("preserves the existing unsaved-change guard on shell navigation",()=>{
 route.path="/admin/publishing";
 const confirm=vi.spyOn(window,"confirm").mockReturnValue(false);
 render(<ApplicationShell area="admin" user={owner}><DirtyContent/></ApplicationShell>);
 expect(fireEvent.click(screen.getByRole("link",{name:"RAG 모델"}))).toBe(false);
 expect(confirm).toHaveBeenCalledTimes(1);
 expect(screen.getByLabelText("Unsaved draft")).toHaveValue("Keep this draft");
 confirm.mockRestore();
});
