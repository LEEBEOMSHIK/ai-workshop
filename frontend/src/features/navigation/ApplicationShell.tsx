"use client";
import Link from "next/link";
import {usePathname} from "next/navigation";
import {useEffect,useId,useRef,useState,useSyncExternalStore,type ReactNode,type KeyboardEvent} from "react";
import {logout} from "../identity/api";
import type {SessionUser} from "../identity/session";
import {routes} from "../../shared/routing/routes";
import {areaLinks,areaMenus,currentMenuItem,menuGroups,isWithinPath,type Area} from "./areaMenus";
import styles from "./ApplicationShell.module.css";
export const APPLICATION_MOBILE_QUERY="(max-width: 63.999rem)";
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
function mobileSnapshot(){return typeof window.matchMedia==="function"&&window.matchMedia(APPLICATION_MOBILE_QUERY).matches;}
function subscribeMobile(callback:()=>void){
 if(typeof window.matchMedia!=="function")return ()=>{};
 const query=window.matchMedia(APPLICATION_MOBILE_QUERY);query.addEventListener("change",callback);
 return ()=>query.removeEventListener("change",callback);
}
function GroupedMenu({area,pathname,onNavigate}:{area:Area;pathname:string|null;onNavigate?:()=>void}){
 const menu=useRef<HTMLElement>(null);
 useEffect(()=>{
  const current=menu.current?.querySelector('a[aria-current="page"]');
  const group=current?.closest("details");if(group)group.open=true;
 },[pathname]);
 return <nav ref={menu} aria-label={areaMenus[area].label} className={styles.groups}>{menuGroups(area).map(group=><details key={group.label} open>
  <summary>{group.label}</summary><ul>{group.items.map(item=><li key={item.href}><Link href={item.href} aria-current={currentMenuItem(area,pathname)?.href===item.href?"page":undefined} onClick={onNavigate}>{item.label}</Link></li>)}</ul>
 </details>)}</nav>;
}
function AreaLinks({area,user,pathname,onNavigate}:{area:Area;user?:SessionUser;pathname:string|null;onNavigate?:()=>void}){
 return <nav aria-label="영역 이동" className={styles.areaLinks}>{areaLinks.filter(link=>(!link.ownerOnly||user?.role==="owner")&&(area!=="public"||link.href===routes.workshopHome)).map(link=><Link key={link.href} href={link.href} aria-current={isWithinPath(pathname,link.prefix)?"location":undefined} onClick={onNavigate}>{area==="public"?"비공개 작업소 입장":link.label}</Link>)}</nav>;
}
function Account({user}:{user:SessionUser}){
 const pending=useRef(false);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
 async function signOut(){
  if(pending.current)return;pending.current=true;setBusy(true);setError("");
  try{await logout();window.location.replace(routes.login);}
  catch{pending.current=false;setBusy(false);setError("로그아웃하지 못했습니다. 다시 시도해 주세요.");}
 }
 return <div className={styles.account}><span>{user.display_name}</span>{user.role==="owner"&&<span className={styles.master}>마스터</span>}<button type="button" onClick={signOut} disabled={busy} aria-busy={busy}>{busy?"로그아웃 중…":"로그아웃"}</button>{error&&<p role="alert">{error}</p>}</div>;
}
export function ApplicationShell({area,user,children,immersive=false,onMenuOpenChange}:{area:Area;user?:SessionUser;children?:ReactNode;immersive?:boolean;onMenuOpenChange?:(open:boolean)=>void}){
 const pathname=usePathname();const mobile=useSyncExternalStore(subscribeMobile,mobileSnapshot,()=>false);
 const dialog=useRef<HTMLDialogElement>(null);const trigger=useRef<HTMLButtonElement>(null);const title=useRef<HTMLParagraphElement>(null);
 const previousOverflow=useRef<string|null>(null);const [drawerOpen,setDrawerOpen]=useState(false);const drawerId=useId();
 const activeGroup=menuGroups(area).find(group=>group.items.some(item=>currentMenuItem(area,pathname)?.href===item.href));
 const activeItem=currentMenuItem(area,pathname);
 const privateUser=area==="public"?undefined:user;
 const brandPath=area==="public"?routes.home:routes.workshopHome;
 const callback=useRef(onMenuOpenChange);useEffect(()=>{callback.current=onMenuOpenChange;},[onMenuOpenChange]);
 function restoreScroll(){if(previousOverflow.current!==null){document.body.style.overflow=previousOverflow.current;previousOverflow.current=null;}}
 function closeDrawer(){if(dialog.current?.open)dialog.current.close();}
 function afterClose(){setDrawerOpen(false);callback.current?.(false);restoreScroll();if(mobileSnapshot())trigger.current?.focus();else title.current?.focus();}
 function openDrawer(){if(!dialog.current||dialog.current.open)return;previousOverflow.current=document.body.style.overflow;document.body.style.overflow="hidden";dialog.current.showModal();setDrawerOpen(true);callback.current?.(true);}
 useEffect(()=>{if(dialog.current?.open)dialog.current.close();},[pathname]);
 useEffect(()=>{if(!mobile&&dialog.current?.open)dialog.current.close();},[mobile]);
 useEffect(()=>()=>{if(previousOverflow.current!==null){document.body.style.overflow=previousOverflow.current;callback.current?.(false);}},[]);
 if((area==="admin"&&privateUser?.role!=="owner")||(area==="workspace"&&!privateUser))return null;
 return <div className={`${styles.shell} ${immersive?styles.immersive:""}`}>
  {!mobile&&<aside className={styles.sidebar}><Link className={styles.brand} href={brandPath}>AI Workshop</Link><p className={styles.sidebarLabel}>{areaMenus[area].label}</p><GroupedMenu area={area} pathname={pathname}/><AreaLinks area={area} user={privateUser} pathname={pathname}/></aside>}
  <div className={styles.main}>
   <header className={styles.topbar}>{mobile&&<button ref={trigger} type="button" aria-label="메뉴 열기" aria-controls={drawerId} aria-expanded={drawerOpen} onClick={openDrawer}><span aria-hidden="true">☰</span></button>}
    <p ref={title} tabIndex={-1} className={styles.position}>{!mobile&&activeGroup&&<span>{activeGroup.label} / </span>}{activeItem?.label??(pathname===routes.login?"로그인":pathname===routes.setup?"초기 설정":areaMenus[area].label)}</p>
    {!mobile&&privateUser&&<Account user={privateUser}/>}
   </header>
   <div className={`${styles.content} ${styles[`${area}Content`]}`}>{children}</div>
  </div>
  <dialog ref={dialog} id={drawerId} aria-label={area==="admin"?"관리자 메뉴":`${areaMenus[area].label} 메뉴`} className={styles.drawer} onKeyDown={trapDrawerFocus} onClose={afterClose} onCancel={event=>{event.preventDefault();closeDrawer();}} onClick={event=>{if(event.target===event.currentTarget)closeDrawer();}}>
   {(mobile||drawerOpen)&&<div className={styles.drawerContent}><header><Link className={styles.brand} href={brandPath} onClick={closeDrawer}>AI Workshop</Link><button type="button" aria-label="메뉴 닫기" onClick={closeDrawer}>닫기</button></header>
    <GroupedMenu area={area} pathname={pathname} onNavigate={closeDrawer}/><AreaLinks area={area} user={privateUser} pathname={pathname} onNavigate={closeDrawer}/>{privateUser&&<Account user={privateUser}/>}
   </div>}
  </dialog>
 </div>;
}
