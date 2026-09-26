import { routes } from "../../shared/routing/routes";

export type Area = "workspace" | "admin";
interface MenuItem { label: string; href: string; prefixes: readonly string[]; domainChat?: boolean }

export const areaLinks = [
  { label: "AI Lab", href: routes.labs, prefix: "/labs", ownerOnly: false },
  { label: "비공개 작업소", href: routes.workshopHome, prefix: "/workshop", ownerOnly: false },
  { label: "관리자", href: routes.adminRagModels, prefix: "/admin", ownerOnly: true },
] as const;

export const areaMenus: Record<Area, { label: string; items: readonly MenuItem[] }> = {
  workspace: { label: "비공개 작업소", items: [
    { label: "파일함", href: routes.workshopHome, prefixes: [routes.workshopHome] },
    { label: "RAG 대화", href: routes.workshopRagSearch, prefixes: [routes.workshopRagSearch, "/workshop/rag/sources"], domainChat: true },
    { label: "학습 기록", href: routes.workshopLearning, prefixes: [routes.workshopLearning] },
  ] },
  admin: { label: "관리자 운영", items: [
    { label: "RAG 도메인", href: routes.adminRagDomains, prefixes: [routes.adminRagDomains] },
    { label: "RAG 구성", href: routes.adminRagConfigurations, prefixes: [routes.adminRagConfigurations] },
    { label: "RAG 모델", href: routes.adminRagModels, prefixes: [routes.adminRagModels] },
    { label: "공개 연구 관리", href: routes.adminPublishing, prefixes: [routes.adminPublishing] },
    { label: "권한 관리", href: routes.adminSystemAccess, prefixes: [routes.adminSystemAccess] },
    { label: "시스템 런타임", href: routes.adminSystemRuntime, prefixes: [routes.adminSystemRuntime] },
    { label: "문제·개선 이력", href: routes.adminSystemIssues, prefixes: [routes.adminSystemIssues] },
  ] },
};

export function isWithinPath(pathname: string | null, prefix: string): boolean {
  return pathname !== null && (pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function isCurrentMenu(pathname: string | null, item: MenuItem): boolean {
  return item.prefixes.some((prefix) => isWithinPath(pathname, prefix))
    || Boolean(item.domainChat && pathname && /^\/workshop\/rag\/domains\/[^/]+\/chat(?:\/|$)/.test(pathname));
}
