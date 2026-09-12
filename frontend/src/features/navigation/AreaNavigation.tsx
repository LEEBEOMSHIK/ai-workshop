"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef, useState } from "react";
import { logout } from "../identity/api";
import type { SessionUser } from "../identity/session";
import { routes } from "../../shared/routing/routes";
import { areaLinks, areaMenus, isCurrentMenu, isWithinPath, type Area } from "./areaMenus";
import styles from "./AreaNavigation.module.css";

export function AreaNavigation({ area, user }: { area: Area; user: SessionUser }) {
  const pathname = usePathname();
  const menu = areaMenus[area];
  const logoutPending = useRef(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  async function handleLogout() {
    if (logoutPending.current) return;
    logoutPending.current = true;
    setIsLoggingOut(true);
    setLogoutError(null);
    try {
      await logout();
      window.location.replace(routes.login);
    } catch {
      logoutPending.current = false;
      setIsLoggingOut(false);
      setLogoutError("로그아웃하지 못했습니다. 다시 시도해 주세요.");
    }
  }

  return <header className={styles.header}>
    <div className={styles.topRow}>
      <Link className={styles.brand} href={routes.workshopHome}>AI Workshop</Link>
      <nav className={styles.links} aria-label="영역 이동">
        {areaLinks.filter((link) => !link.ownerOnly || user.role === "owner").map((link) => <Link
          key={link.href} href={link.href} aria-current={isWithinPath(pathname, link.prefix) ? "location" : undefined}
        >{link.label}</Link>)}
      </nav>
      <div className={styles.account}>
        <span className={styles.user}>{user.display_name}</span>
        {user.role === "owner" ? <span className={styles.master}>마스터</span> : null}
        <button className={styles.logout} type="button" onClick={handleLogout}
          disabled={isLoggingOut} aria-busy={isLoggingOut}>
          {isLoggingOut ? "로그아웃 중…" : "로그아웃"}
        </button>
      </div>
    </div>
    {logoutError ? <p className={styles.error} role="alert">{logoutError}</p> : null}
    {area !== "admin" || user.role === "owner" ? <nav className={`${styles.links} ${styles.menuRow}`} aria-label={menu.label}>
      {menu.items.map((item) => <Link key={item.href} href={item.href}
        aria-current={isCurrentMenu(pathname, item) ? "page" : undefined}>{item.label}</Link>)}
    </nav> : null}
  </header>;
}
