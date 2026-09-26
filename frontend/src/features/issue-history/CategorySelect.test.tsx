import {render,screen,within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {expect,it} from "vitest";
import {CategorySelect,categoryPath} from "./CategorySelect";
import type {Category} from "./types";
const categories: Category[] = [
 {id:"rag",code:"rag",name:"RAG",parent_id:null,is_active:true,sort_order:0,revision:1},
 {id:"common",code:"platform",name:"공통",parent_id:null,is_active:true,sort_order:1,revision:1},
 {id:"search",code:"search",name:"검색·근거",parent_id:"rag",is_active:true,sort_order:0,revision:1},
 {id:"env",code:"env",name:"실행 환경",parent_id:"common",is_active:true,sort_order:0,revision:1},
];
it("filters child choices by parent and clears the child on parent changes",async()=>{
 const user=userEvent.setup();render(<CategorySelect categories={categories} initialChild="search" mode="filter"/>);
 expect(screen.getByLabelText("상위 카테고리")).toHaveValue("rag");expect(screen.getByLabelText("하위 카테고리")).toHaveValue("search");
 await user.selectOptions(screen.getByLabelText("상위 카테고리"),"common");
 expect(screen.getByLabelText("하위 카테고리")).toHaveValue("");
 expect(within(screen.getByLabelText("하위 카테고리")).queryByRole("option",{name:"검색·근거"})).not.toBeInTheDocument();
 expect(within(screen.getByLabelText("하위 카테고리")).getByRole("option",{name:"실행 환경"})).toBeInTheDocument();
 expect(screen.getByLabelText("상위 카테고리")).toHaveAttribute("name","parent_category_id");
});
it("preserves an existing inactive assignment but does not offer it for new assignments",()=>{
 const inactive=categories.map(c=>c.id==="rag"||c.id==="search"?{...c,is_active:false}:c);
 const {rerender}=render(<CategorySelect categories={inactive} initialChild="search" mode="assignment"/>);
 expect(screen.getByLabelText("상위 카테고리")).toHaveValue("rag");expect(screen.getByLabelText("하위 카테고리")).toHaveValue("search");
 rerender(<CategorySelect key="new" categories={inactive} mode="assignment"/>);
 expect(within(screen.getByLabelText("상위 카테고리")).queryByRole("option",{name:/RAG/})).not.toBeInTheDocument();
});
it("displays the full category path",()=>expect(categoryPath(categories,"search")).toBe("RAG > 검색·근거"));
