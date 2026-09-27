import { routes } from "../../shared/routing/routes";

export type Area = "public" | "workspace" | "admin";
interface MenuItem { label: string; href: string; prefixes: readonly string[]; domainChat?: boolean; domainFiles?: boolean; exact?: boolean }
export const adminMenuGroups: readonly {label: string; items: readonly MenuItem[]}[] = [
    {label: "RAG 관리", items: [
      {label: "실행 모니터링", href: routes.adminRagExecutions, prefixes: [routes.adminRagExecutions]},
    {label: "RAG 도메인", href: routes.adminRagDomains, prefixes: [routes.adminRagDomains]},
    {label: "RAG 구성", href: routes.adminRagConfigurations, prefixes: [routes.adminRagConfigurations]},
    {label: "RAG 모델", href: routes.adminRagModels, prefixes: [routes.adminRagModels]},
  ]},
  {label: "공개 콘텐츠", items: [
    {label: "공개 연구 관리", href: routes.adminPublishing, prefixes: [routes.adminPublishing]},
  ]},
  {label: "시스템 관리", items: [
    {label: "권한 관리", href: routes.adminSystemAccess, prefixes: [routes.adminSystemAccess]},
    {label: "런타임", href: routes.adminSystemRuntime, prefixes: [routes.adminSystemRuntime]},
    {label: "문제 및 개선 이력", href: routes.adminSystemIssues, prefixes: [routes.adminSystemIssues]},
  ]},
];

export const areaLinks = [
  { label: "AI Lab", href: routes.labs, prefix: "/labs", ownerOnly: false },
  { label: "비공개 작업소", href: routes.workshopHome, prefix: "/workshop", ownerOnly: false },
  { label: "관리자", href: routes.adminRagModels, prefix: "/admin", ownerOnly: true },
] as const;

export const areaMenus: Record<Area, { label: string; items: readonly MenuItem[] }> = {
  public: {label: "공개 전시실", items: [
    {label: "홈", href: routes.home, prefixes: [routes.home], exact:true},
    {label: "AI Labs", href: routes.labs, prefixes: [routes.labs]},
    {label: "RAG 실험실", href: routes.ragLab, prefixes: [routes.ragLab]},
    {label: "공개 연구", href: routes.ragStudies, prefixes: [routes.ragStudies,"/studies"]},
  ]},
  workspace: { label: "비공개 작업소", items: [
    { label: "파일함", href: routes.workshopHome, prefixes: [routes.workshopHome], domainFiles:true },
    { label: "RAG 대화", href: routes.workshopRagSearch, prefixes: [routes.workshopRagSearch, "/workshop/rag/sources"], domainChat: true },
    { label: "학습 기록", href: routes.workshopLearning, prefixes: [routes.workshopLearning] },
  ] },
  admin: { label: "관리자 운영", items: adminMenuGroups.flatMap(group => group.items) },
};

export function isWithinPath(pathname: string | null, prefix: string): boolean {
  return pathname !== null && (pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function isCurrentMenu(pathname: string | null, item: MenuItem): boolean {
  if(item.exact)return pathname===item.href;
  return item.prefixes.some((prefix) => isWithinPath(pathname, prefix))
    || Boolean(item.domainChat && pathname && /^\/workshop\/rag\/domains\/[^/]+\/chat(?:\/|$)/.test(pathname))
    || Boolean(item.domainFiles && pathname && /^\/workshop\/rag\/domains\/[^/]+\/files(?:\/|$)/.test(pathname));
}

export function currentMenuItem(area:Area,pathname:string|null):MenuItem|undefined {
  return areaMenus[area].items.filter(item=>isCurrentMenu(pathname,item)).sort((a,b)=>Math.max(...b.prefixes.map(prefix=>isWithinPath(pathname,prefix)?prefix.length:0))-Math.max(...a.prefixes.map(prefix=>isWithinPath(pathname,prefix)?prefix.length:0)))[0];
}
export function menuGroups(area:Area) {
  return area==="admin"?adminMenuGroups:[{label:areaMenus[area].label,items:areaMenus[area].items}];
}
