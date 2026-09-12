import Link from "next/link";

import { PublicNavigation } from "../navigation/PublicNavigation";
import { preparingRooms, preparingStatus } from "../office-game/preparingRooms";
import type { PublicLabCatalogResult } from "./catalog";
import styles from "./LabDirectory.module.css";

interface LabWorldPageProps {
  catalog: PublicLabCatalogResult;
}

export function LabWorldPage({ catalog }: LabWorldPageProps) {
  const statusMessage = catalog.status === "error"
    ? "공개 연구실 상태를 확인할 수 없습니다"
    : `현재 공개된 연구실 ${catalog.labs.length}곳`;

  return (
    <main className={styles.page}>
      <PublicNavigation />
      <div className={styles.content}>
        <header className={styles.intro}>
          <p className={styles.eyebrow}>AI LABS</p>
          <h1>AI 연구실</h1>
          <p>관심 있는 AI 기술과 담당 관리자를 살펴보고 연구실로 들어가세요.</p>
        </header>
        <section className={styles.section} aria-labelledby="available-labs-title">
          <h2 id="available-labs-title">연구실 둘러보기</h2>
          <p className={styles.muted} role="status" aria-label="공개 연구실 상태">{statusMessage}</p>
          {catalog.status === "error" ? (
            <p className={styles.notice} role="alert">연구실 정보를 불러오지 못했습니다</p>
          ) : catalog.labs.length === 0 ? (
            <p className={styles.notice}>현재 공개된 연구실을 준비하고 있습니다</p>
          ) : (
            <ul className={styles.grid}>
              {catalog.labs.map((lab) => <li key={lab.slug}>
                <Link className={styles.card} href={lab.href} prefetch={false} data-prefetch="false" aria-label={`${lab.name} 들어가기`}>
                  <span className={styles.status}>{lab.statusLabel}</span>
                  <h3>{lab.name}</h3>
                  <p>{lab.description}</p>
                  <p className={styles.manager}>관리자: {lab.manager.name} · {lab.manager.role}</p>
                </Link>
              </li>)}
            </ul>
          )}
        </section>
        <section className={styles.section} aria-labelledby="preparing-labs-title">
          <h2 id="preparing-labs-title">준비 중인 연구실</h2>
          <ul className={styles.grid}>
            {preparingRooms.map((room) => <li key={room.id}>
              <article className={`${styles.card} ${styles.preparingCard}`}>
                <span className={styles.preparingStatus}>{preparingStatus}</span>
                <h3>{room.name}</h3>
                <p>{room.purpose}</p>
              </article>
            </li>)}
          </ul>
        </section>
      </div>
    </main>
  );
}
