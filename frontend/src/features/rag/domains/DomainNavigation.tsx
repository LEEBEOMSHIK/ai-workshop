import Link from "next/link";

import { ragDomainChatPath, ragDomainFilesPath } from "../../../shared/routing/routes";

export function DomainNavigation({ slug, displayName, current }: {
  slug: string;
  displayName: string;
  current: "files" | "chat";
}) {
  return (
    <nav className="domain-navigation" aria-label={`${displayName} 도메인 메뉴`}>
      <strong>{displayName}</strong>
      <Link href={ragDomainFilesPath(slug)} aria-current={current === "files" ? "page" : undefined}>파일함</Link>
      <Link href={ragDomainChatPath(slug)} aria-current={current === "chat" ? "page" : undefined}>대화</Link>
    </nav>
  );
}
