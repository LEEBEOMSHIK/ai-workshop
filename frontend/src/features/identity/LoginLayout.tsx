import Link from "next/link";
import type { ReactNode } from "react";
import { routes } from "../../shared/routing/routes";
import styles from "./LoginPage.module.css";

export function LoginLayout({ children }: { children: ReactNode }) {
  return <div className={styles.page}>
    <header className={styles.header}>
      <Link href={routes.home} className={styles.brand} aria-label="AI Workshop 홈">AI Workshop</Link>
    </header>
    <div className={styles.shell}>{children}</div>
  </div>;
}
