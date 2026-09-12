import Link from "next/link";

import { routes } from "../../shared/routing/routes";
import styles from "./PublicNavigation.module.css";

export function PublicNavigation() {
  return (
    <header className={styles.navigation}>
      <Link className={styles.brand} href={routes.home}>AI Workshop</Link>
      <nav className={styles.links} aria-label="공개 전시실">
        <Link href={routes.labs}>AI Labs</Link>
        <Link href={routes.workshopHome}>비공개 작업소 입장</Link>
      </nav>
    </header>
  );
}
