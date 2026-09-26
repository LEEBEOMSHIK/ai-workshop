"use client";
import Link from "next/link";
import {usePathname} from "next/navigation";
import {useEffect,useId,useRef,useState,useSyncExternalStore,type ReactNode,type KeyboardEvent} from "react";
import {logout} from "../identity/api";
import type {SessionUser} from "../identity/session";
import {routes} from "../../shared/routing/routes";
import {adminMenuGroups,areaLinks,isCurrentMenu,isWithinPath} from "./areaMenus";
import styles from "./AdminShell.module.css";
export const ADMIN_MOBILE_QUERY="(max-width: 63.999rem)";
function trapDrawerFocus(event: KeyboardEvent<HTMLDialogElement>) {
 if(event.key!=="Tab"||!event.currentTarget.open)return;
 const drawer=event.currentTarget;
 const candidates=Array.from(drawer.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])'));
 const stops=candidates.filter(element=>{
  if(element.tabIndex<0||element.closest("[inert]"))return false;
  for(let ancestor:HTMLElement|null=element;ancestor&&ancestor!==drawer;ancestor=ancestor.parentElement){
   const style=window.getComputedStyle(ancestor);
   if(ancestor.hidden||style.display==="none"||style.visibility==="hidden")return false;
   if(ancestor instanceof HTMLDetailsElement&&!ancestor.open){
    const summary=Array.from(ancestor.children).find(child=>child.tagName==="SUMMARY");
    if(!summary?.contains(element))return false;
   }
  }
  return true;
 });
 const first=stops[0],last=stops.at(-1);
 if(!first||!last){event.preventDefault();drawer.focus();return;}
 const active=document.activeElement;
 if(!stops.includes(active as HTMLElement)||(event.shiftKey&&active===first)||(!event.shiftKey&&active===last)){
  event.preventDefault();(event.shiftKey?last:first).focus();
 }
}
function mobileSnapshot(){return typeof window.matchMedia==="function"&&window.matchMedia(ADMIN_MOBILE_QUERY).matches;}
function subscribeMobile(callback:()=>void){
 if(typeof window.matchMedia!=="function")return ()=>{};
 const query=window.matchMedia(ADMIN_MOBILE_QUERY);query.addEventListener("change",callback);
 return ()=>query.removeEventListener("change",callback);
}
function GroupedMenu({pathname,onNavigate}:{pathname:string|null;onNavigate?:()=>void}){
 const menu=useRef<HTMLElement>(null);
 useEffect(()=>{
  const current=menu.current?.querySelector('a[aria-current="page"]');
  const group=current?.closest("details");if(group)group.open=true;
 },[pathname]);
 return <nav ref={menu} aria-label="관리자 운영" className={styles.groups}>{adminMenuGroups.map(group=><details key={group.label} open>
  <summary>{group.label}</summary><ul>{group.items.map(item=><li key={item.href}><Link href={item.href} aria-current={isCurrentMenu(pathname,item)?"page":undefined} onClick={onNavigate}>{item.label}</Link></li>)}</ul>
 </details>)}</nav>;
}
function AreaLinks({pathname,onNavigate}:{pathname:string|null;onNavigate?:()=>void}){
 return <nav aria-label="영역 이동" className={styles.areaLinks}>{areaLinks.map(link=><Link key={link.href} href={link.href} aria-current={isWithinPath(pathname,link.prefix)?"location":undefined} onClick={onNavigate}>{link.label}</Link>)}</nav>;
}
function Account({user}:{user:SessionUser}){
 const pending=useRef(false);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
 async function signOut(){
  if(pending.current)return;pending.current=true;setBusy(true);setError("");
  try{await logout();window.location.replace(routes.login);}
  catch{pending.current=false;setBusy(false);setError("로그아웃하지 못했습니다. 다시 시도해 주세요.");}
 }
 return <div className={styles.account}><span>{user.display_name}</span><span className={styles.master}>마스터</span><button type="button" onClick={signOut} disabled={busy} aria-busy={busy}>{busy?"로그아웃 중…":"로그아웃"}</button>{error&&<p role="alert">{error}</p>}</div>;
}
export function AdminShell({user,children}:{user:SessionUser;children?:ReactNode}){
 const pathname=usePathname();const mobile=useSyncExternalStore(subscribeMobile,mobileSnapshot,()=>false);
 const dialog=useRef<HTMLDialogElement>(null);const trigger=useRef<HTMLButtonElement>(null);const title=useRef<HTMLParagraphElement>(null);
 const previousOverflow=useRef<string|null>(null);const [drawerOpen,setDrawerOpen]=useState(false);const drawerId=useId();
 const activeGroup=adminMenuGroups.find(group=>group.items.some(item=>isCurrentMenu(pathname,item)));
 const activeItem=activeGroup?.items.find(item=>isCurrentMenu(pathname,item));
 function restoreScroll(){if(previousOverflow.current!==null){document.body.style.overflow=previousOverflow.current;previousOverflow.current=null;}}
 function closeDrawer(){if(dialog.current?.open)dialog.current.close();}
 function afterClose(){setDrawerOpen(false);restoreScroll();if(mobileSnapshot())trigger.current?.focus();else title.current?.focus();}
 function openDrawer(){if(!dialog.current||dialog.current.open)return;previousOverflow.current=document.body.style.overflow;document.body.style.overflow="hidden";dialog.current.showModal();setDrawerOpen(true);}
 useEffect(()=>{if(dialog.current?.open)dialog.current.close();},[pathname]);
 useEffect(()=>{if(!mobile&&dialog.current?.open)dialog.current.close();},[mobile]);
 useEffect(()=>()=>{if(previousOverflow.current!==null)document.body.style.overflow=previousOverflow.current;},[]);
 if(user.role!=="owner")return null;
 return <div className={styles.shell}>
  {!mobile&&<aside className={styles.sidebar}><Link className={styles.brand} href={routes.workshopHome}>AI Workshop</Link><p className={styles.sidebarLabel}>관리자</p><GroupedMenu pathname={pathname}/><AreaLinks pathname={pathname}/></aside>}
  <div className={styles.main}>
   <header className={styles.topbar}>{mobile&&<button ref={trigger} type="button" aria-label="메뉴 열기" aria-controls={drawerId} aria-expanded={drawerOpen} onClick={openDrawer}><span aria-hidden="true">☰</span></button>}
    <p ref={title} tabIndex={-1} className={styles.position}>{!mobile&&activeGroup&&<span>{activeGroup.label} / </span>}{activeItem?.label??"관리자"}</p>
    {!mobile&&<Account user={user}/>}
   </header>
   <div className={styles.content}>{children}</div>
  </div>
  <dialog ref={dialog} id={drawerId} aria-label="관리자 메뉴" className={styles.drawer} onKeyDown={trapDrawerFocus} onClose={afterClose} onCancel={event=>{event.preventDefault();closeDrawer();}} onClick={event=>{if(event.target===event.currentTarget)closeDrawer();}}>
   <div className={styles.drawerContent}><header><Link className={styles.brand} href={routes.workshopHome} onClick={closeDrawer}>AI Workshop</Link><button type="button" aria-label="메뉴 닫기" onClick={closeDrawer}>닫기</button></header>
    <GroupedMenu pathname={pathname} onNavigate={closeDrawer}/><AreaLinks pathname={pathname} onNavigate={closeDrawer}/><Account user={user}/>
   </div>
  </dialog>
 </div>;
}
