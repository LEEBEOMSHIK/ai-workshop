"use client";
import Link from "next/link";
import {usePathname} from "next/navigation";
import {useEffect,useId,useRef,useState,useSyncExternalStore,type ReactNode,type KeyboardEvent,type PointerEvent} from "react";
import {logout} from "../identity/api";
import type {SessionUser} from "../identity/session";
import {routes} from "../../shared/routing/routes";
import {Button} from "../../shared/ui/Button";
import {ThemeChoice} from "../../shared/ui/ThemeChoice";
import {areaLinks,areaMenus,currentMenuItem,menuGroups,isDomainChatPath,isWithinPath,type Area} from "./areaMenus";
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
 const currentHref = currentMenuItem(area, pathname)?.href;
 return <nav ref={menu} aria-label={areaMenus[area].label} className={styles.groups}>
  {menuGroups(area).map(group => {
   const links = <ul key={group.label}>{group.items.map(item =>
    <li key={item.href}>
     <Link target="_self" className={styles.menuLink} href={item.href} aria-current={item.href === currentHref ? "page" : undefined} onClick={onNavigate}>
      {item.label}
     </Link>
    </li>
   )}</ul>;
   if (area === "workspace") return links;
   return <details key={group.label} open><summary>{group.label}</summary>{links}</details>;
  })}
 </nav>;
}
function AreaLinks({area,user,pathname,onNavigate}:{area:Area;user?:SessionUser;pathname:string|null;onNavigate?:()=>void}){
 return <nav aria-label="영역 이동" className={styles.areaLinks}>{areaLinks.filter(link=>(!link.ownerOnly||user?.role==="owner")&&(area!=="public"||link.href===routes.workshopHome)).map(link=><Link target="_self" key={link.href} className={styles.menuLink} href={link.href} aria-current={isWithinPath(pathname,link.prefix)?"location":undefined} onClick={onNavigate}>{area==="public"?"비공개 작업소 입장":link.label}</Link>)}</nav>;
}
function Account({user,compact=false}:{user?:SessionUser;compact?:boolean}){
 const pending=useRef(false);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
 const [open,setOpen]=useState(false);
 const container=useRef<HTMLDivElement>(null);
 const trigger=useRef<HTMLButtonElement>(null);
 const panelId=useId();
 const label=user?"계정 및 화면 설정":"화면 설정";
 useEffect(()=>{
  if(!open)return;
  const closeOutside=(event:Event)=>{
   if(event.target instanceof Node&&!container.current?.contains(event.target))setOpen(false);
  };
  document.addEventListener("pointerdown",closeOutside);
  document.addEventListener("focusin",closeOutside);
  return ()=>{
   document.removeEventListener("pointerdown",closeOutside);
   document.removeEventListener("focusin",closeOutside);
  };
 },[open]);
 async function signOut(){
  if(pending.current)return;pending.current=true;setBusy(true);setError("");
  try{await logout();window.location.replace(routes.login);}
  catch{pending.current=false;setBusy(false);setError("로그아웃하지 못했습니다. 다시 시도해 주세요.");}
 }
 return <div ref={container} className={styles.account} onKeyDown={event=>{
  if(open&&event.key==="Escape"){
   event.preventDefault();event.stopPropagation();setOpen(false);trigger.current?.focus();
  }
 }}>
  <Button ref={trigger} variant="quiet" className={styles.accountTrigger} aria-controls={panelId} aria-expanded={open}
   aria-label={label} title={label} onClick={()=>setOpen(!open)}>
   <svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6">
    {user?<><circle cx="12" cy="8" r="3.5"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/></>:<><circle cx="12" cy="12" r="4"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2"/></>}
   </svg>
   {!compact&&<span>{user?.display_name??label}</span>}
  </Button>
  {open&&<section id={panelId} aria-label={label} className={styles.accountPanel}>
   {user&&<div className={styles.identity}><strong>{user.display_name}</strong><span>{user.role==="owner"?"마스터":"멤버"}</span></div>}
   <ThemeChoice/>
   {user&&<Button onClick={signOut} disabled={busy} aria-busy={busy}>{busy?"로그아웃 중…":"로그아웃"}</Button>}
   {error&&<p role="alert">{error}</p>}
  </section>}
 </div>;
}
const workspaceIcons: Record<string, string> = {
 [routes.workshopHome]: "M3 7V5h6l2 2h10v12H3z",
 [routes.workshopRagSearch]: "M3 4h18v13H9l-6 4z",
 [routes.workshopLearning]: "M12 6Q8 3 3 5v14q5-2 9 1 4-3 9-1V5q-5-2-9 1v14",
 [routes.workshopFlows]: "M10 3h4v4h-4z M12 7v5 M5 16v-4h14v4 M3 16h4v4H3z M17 16h4v4h-4z",
 [routes.workshopDesignSystem]: "M3 3h8v8H3z M15 3h6v8h-6z M3 15h8v6H3z M15 15h6v6h-6z",
};
function WorkspaceRailLinks({activeHref}:{activeHref?:string}) {
 return <nav aria-label={areaMenus.workspace.label}>{areaMenus.workspace.items.map(item =>
   <Link target="_self" key={item.href} className={styles.railLink} href={item.href} aria-label={item.label} title={item.label} aria-current={item.href===activeHref?"page":undefined}>
    <svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"><path d={workspaceIcons[item.href]}/></svg>
   </Link>
  )}</nav>;
}

const sidebarKey = "ai-workshop.workspace-sidebar.v1";
const sidebarEvent = "workspace-sidebar-change";
const defaultSidebarWidth = 288;
const minSidebarWidth = 256;
const maxSidebarWidth = 400;
type SidebarPreference = { width: number; collapsed: boolean };
function clampSidebarWidth(width: number) {
 return Math.max(minSidebarWidth, Math.min(maxSidebarWidth, Math.round(width)));
}
function readSidebarPreference(): string | null {
 try { return window.localStorage.getItem(sidebarKey); } catch { return null; }
}
function parseSidebarPreference(raw: string | null): SidebarPreference | null {
 if (!raw) return null;
 try {
  const value = JSON.parse(raw);
  return typeof value?.collapsed === "boolean" && Number.isFinite(value.width)
   ? {collapsed: value.collapsed, width: clampSidebarWidth(value.width)} : null;
 } catch { return null; }
}
function subscribeSidebar(callback: () => void) {
 window.addEventListener("storage", callback);
 window.addEventListener(sidebarEvent, callback);
 return () => {
  window.removeEventListener("storage", callback);
  window.removeEventListener(sidebarEvent, callback);
 };
}

function SidebarSeparator({sidebarId,width,onWidthChange,onCommit}:{sidebarId:string;width:number;onWidthChange:(value:number|null)=>void;onCommit:(value:number)=>void}) {
 const drag = useRef<{id:number;x:number;width:number}|null>(null);
 useEffect(() => () => { if(drag.current) onWidthChange(null); }, [onWidthChange]);
 function dragWidth(event: PointerEvent<HTMLDivElement>) {
  const origin = drag.current;
  return origin?.id === event.pointerId ? clampSidebarWidth(origin.width + event.clientX - origin.x) : null;
 }
 return <div className={styles.resizeHandle} role="separator" tabIndex={0} aria-label="작업소 메뉴 너비"
  aria-orientation="vertical" aria-controls={sidebarId} aria-valuemin={minSidebarWidth} aria-valuemax={maxSidebarWidth} aria-valuenow={width} aria-valuetext={`${width}픽셀`}
  onKeyDown={event => {
   const widths:Record<string,number> = {Home:minSidebarWidth,End:maxSidebarWidth,ArrowLeft:width-16,ArrowRight:width+16};
   if (!Object.hasOwn(widths,event.key)) return;
   event.preventDefault(); onCommit(clampSidebarWidth(widths[event.key]));
  }}
  onPointerDown={event => {
   if (event.button !== 0 || drag.current) return;
   event.currentTarget.setPointerCapture(event.pointerId);
   drag.current = {id:event.pointerId,x:event.clientX,width};
  }}
  onPointerMove={event => { const value=dragWidth(event); if(value!==null)onWidthChange(value); }}
  onPointerUp={event => {
   const value=dragWidth(event);
   if(value!==null) {drag.current=null; onWidthChange(null); onCommit(value);}
  }}
  onLostPointerCapture={() => {drag.current=null; onWidthChange(null);}}
 />;
}
export function ApplicationShell({area,user,children,immersive=false,onMenuOpenChange}:{area:Area;user?:SessionUser;children?:ReactNode;immersive?:boolean;onMenuOpenChange?:(open:boolean)=>void}){
 const pathname=usePathname();const mobile=useSyncExternalStore(subscribeMobile,mobileSnapshot,()=>false);
 const sidebarId = useId();
 const stored = useSyncExternalStore(subscribeSidebar,readSidebarPreference,()=>null);
 const [localPreference,setLocalPreference] = useState<SidebarPreference|null>(null);
 const [dragWidth,setDragWidth] = useState<number|null>(null);
 const preference = localPreference ?? parseSidebarPreference(stored);
 const conversationRoute = area==="workspace" && isDomainChatPath(pathname);
 const compactWorkspace = conversationRoute || (area==="workspace" && preference?.collapsed);
 const sidebarWidth = dragWidth ?? preference?.width ?? defaultSidebarWidth;
 function saveSidebar(width:number,collapsed:boolean) {
  const next = {width,collapsed};
  try {
   window.localStorage.setItem(sidebarKey,JSON.stringify(next));
   setLocalPreference(null);
   window.dispatchEvent(new Event(sidebarEvent));
  } catch { setLocalPreference(next); }
 }
 const dialog=useRef<HTMLDialogElement>(null);const trigger=useRef<HTMLButtonElement>(null);const title=useRef<HTMLParagraphElement>(null);
 const previousOverflow=useRef<string|null>(null);const [drawerOpen,setDrawerOpen]=useState(false);const drawerId=useId();
 const activeGroup=menuGroups(area).find(group=>group.items.some(item=>currentMenuItem(area,pathname)?.href===item.href));
 const activeItem=currentMenuItem(area,pathname);
 const privateUser=area==="public"?undefined:user;
 const brandPath=area==="public"?routes.home:routes.workshopHome;
 const callback=useRef(onMenuOpenChange);useEffect(()=>{callback.current=onMenuOpenChange;},[onMenuOpenChange]);
 function restoreScroll(){if(previousOverflow.current!==null){document.body.style.overflow=previousOverflow.current;previousOverflow.current=null;}}
 function closeDrawer(){if(dialog.current?.open)dialog.current.close();}
 function afterClose(){setDrawerOpen(false);callback.current?.(false);restoreScroll();if(trigger.current)trigger.current.focus();else title.current?.focus();}
 function openDrawer(){if(!dialog.current||dialog.current.open)return;previousOverflow.current=document.body.style.overflow;document.body.style.overflow="hidden";dialog.current.showModal();setDrawerOpen(true);callback.current?.(true);}
 useEffect(()=>{if(dialog.current?.open)dialog.current.close();},[pathname]);
 useEffect(()=>{if(!mobile&&dialog.current?.open)dialog.current.close();},[mobile]);
 useEffect(()=>()=>{if(previousOverflow.current!==null){document.body.style.overflow=previousOverflow.current;callback.current?.(false);}},[]);
 if((area==="admin"&&privateUser?.role!=="owner")||(area==="workspace"&&!privateUser))return null;
 const menuTrigger=<Button ref={trigger} variant="quiet" aria-label="메뉴 열기" title="메뉴 열기" aria-controls={drawerId} aria-expanded={drawerOpen} onClick={openDrawer}><span aria-hidden="true">☰</span></Button>;
 return <div className={`${styles.shell} ${immersive?styles.immersive:""}`}>
  {!mobile&&<aside id={sidebarId} className={`${styles.sidebar} ${compactWorkspace?styles.rail:""}`}
   style={area==="workspace"&&!compactWorkspace?{width:sidebarWidth,flexBasis:sidebarWidth}:undefined}>
   <div className={styles.sidebarScroll}>
   {compactWorkspace?<>{menuTrigger}<WorkspaceRailLinks activeHref={activeItem?.href}/></>:<>
    <Link target="_self" className={styles.brand} href={brandPath}>AI Workshop</Link><p className={styles.sidebarLabel}>{areaMenus[area].label}</p>
    <GroupedMenu area={area} pathname={pathname}/><AreaLinks area={area} user={privateUser} pathname={pathname}/>
   </>}
   {area==="workspace"&&!conversationRoute&&<Button variant="quiet" className={styles.sidebarToggle} aria-label={compactWorkspace?"작업소 메뉴 펼치기":"작업소 메뉴 접기"}
    title={compactWorkspace?"작업소 메뉴 펼치기":"작업소 메뉴 접기"} aria-expanded={!compactWorkspace} aria-controls={sidebarId}
    onClick={()=>saveSidebar(sidebarWidth,!compactWorkspace)}><span aria-hidden="true">{compactWorkspace?"»":"«"}</span>{!compactWorkspace&&"메뉴 접기"}</Button>}
   </div>
   {!drawerOpen&&<Account key={pathname} user={privateUser} compact={Boolean(compactWorkspace)}/>}
  </aside>}
  {!mobile&&area==="workspace"&&!compactWorkspace&&<SidebarSeparator sidebarId={sidebarId} width={sidebarWidth} onWidthChange={setDragWidth} onCommit={value=>saveSidebar(value,false)}/>}
  <div className={styles.main}>
   <header className={styles.topbar}>{mobile&&menuTrigger}
    <p ref={title} tabIndex={-1} className={styles.position}>{!mobile&&activeGroup&&<span>{activeGroup.label} / </span>}{activeItem?.label??(pathname===routes.login?"로그인":pathname===routes.setup?"초기 설정":areaMenus[area].label)}</p>
   </header>
   <div className={`${styles.content} ${styles[`${area}Content`]}`}>{children}</div>
  </div>
  <dialog ref={dialog} id={drawerId} aria-label={area==="admin"?"관리자 메뉴":`${areaMenus[area].label} 메뉴`} className={styles.drawer} onKeyDown={trapDrawerFocus} onClose={afterClose} onCancel={event=>{event.preventDefault();closeDrawer();}} onClick={event=>{if(event.target===event.currentTarget)closeDrawer();}}>
   {(mobile||compactWorkspace||drawerOpen)&&<div className={styles.drawerContent}><header><Link target="_self" className={styles.brand} href={brandPath} onClick={closeDrawer}>AI Workshop</Link><button type="button" aria-label="메뉴 닫기" onClick={closeDrawer}>닫기</button></header>
    <div className={styles.sidebarScroll}><GroupedMenu area={area} pathname={pathname} onNavigate={closeDrawer}/><AreaLinks area={area} user={privateUser} pathname={pathname} onNavigate={closeDrawer}/></div>
    {drawerOpen&&<Account key={pathname} user={privateUser}/>}
   </div>}
  </dialog>
 </div>;
}
