"use client";
import {useState} from "react";
import type {Category} from "./types";
export function categoryPath(categories:Category[],id:string){
 const category=categories.find(item=>item.id===id);
 if(!category)return "분류 없음";
 const parent=categories.find(item=>item.id===category.parent_id);
 return parent?`${parent.name} > ${category.name}`:category.name;
}
export function CategorySelect({categories,initialChild,initialParent,mode}:{categories:Category[];initialChild?:string;initialParent?:string;mode:"filter"|"assignment"}){
 const existing=categories.find(item=>item.id===initialChild);
 const existingParent=existing?.parent_id;
 const [parent,setParent]=useState(initialParent??existingParent??"");
 const [child,setChild]=useState(initialChild??"");
 const assignment=mode==="assignment";
 const parents=categories.filter(item=>!item.parent_id && (!assignment||item.is_active||item.id===existingParent));
 const parentActive=categories.find(item=>item.id===parent)?.is_active;
 const children=categories.filter(item=>item.parent_id===parent && (!assignment||(item.is_active&&parentActive)||item.id===initialChild));
 return <>
  <label>상위 카테고리<select name={assignment?undefined:"parent_category_id"} value={parent} required={assignment} onChange={event=>{setParent(event.target.value);setChild("");}}>
   <option value="">{assignment?"상위 분류 선택":"전체 상위 카테고리"}</option>
   {parents.map(item=><option key={item.id} value={item.id}>{item.name}{!item.is_active?" (비활성)":""}</option>)}
  </select></label>
  <label>하위 카테고리<select name="category_id" value={child} required={assignment} disabled={!parent} onChange={event=>setChild(event.target.value)}>
   <option value="">{assignment?"하위 분류 선택":"전체 하위 카테고리"}</option>
   {children.map(item=><option key={item.id} value={item.id}>{item.name}{!item.is_active?" (비활성)":""}</option>)}
  </select></label>
 </>;
}
