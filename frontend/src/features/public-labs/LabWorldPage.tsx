import { PublicNavigation } from "../navigation/PublicNavigation";
import { AgentCharacter } from "./AgentCharacter";
import type { PublicLabCatalogResult } from "./catalog";
import styles from "./PublicLabScene.module.css";

interface LabWorldPageProps {
  catalog: PublicLabCatalogResult;
}

interface WorldStatusHudProps {
  catalog: PublicLabCatalogResult;
}

function WorldStatusHud({ catalog }: WorldStatusHudProps) {
  const message =
    catalog.status === "error"
      ? "공개 연구실 상태를 확인할 수 없습니다"
      : catalog.labs.length === 0
        ? "현재 공개된 연구실 0곳 · 공개된 Labs를 준비하고 있습니다"
        : `현재 공개된 연구실 ${catalog.labs.length}곳 · 공개된 Labs에서 제공`;

  return (
    <section aria-label="공개 연구실 상태" role="status">
      <p className={styles.eyebrow}>STATUS HUD</p>
      <p>{message}</p>
    </section>
  );
}

export function LabWorldPage({ catalog }: LabWorldPageProps) {
  return (
    <main className={styles.page}>
      <PublicNavigation />
      <section className={styles.hero} aria-labelledby="lab-world-title">
        <p className={styles.eyebrow}>PUBLIC AI LAB WORLD</p>
        <h1 id="lab-world-title">AI 기술 관리자들이 일하는 연구소</h1>
        <p>현재 공개된 Labs의 연구실과 기술 관리자를 둘러보세요.</p>
      </section>
      <WorldStatusHud catalog={catalog} />
      <section className={styles.scene} aria-label="AI 연구소 작업 현장">
        {catalog.status === "error" ? (
          <p role="alert">연구실 정보를 불러오지 못했습니다</p>
        ) : catalog.labs.length === 0 ? (
          <p>현재 공개된 연구실을 준비하고 있습니다</p>
        ) : (
          catalog.labs.map((lab) => (
            <section key={lab.slug} aria-labelledby={`${lab.slug}-lab-title`}>
              <p className={styles.eyebrow}>{lab.eyebrow}</p>
              <h2 id={`${lab.slug}-lab-title`}>{lab.name}</h2>
              <p>{lab.description}</p>
              <AgentCharacter lab={lab} variant="working" />
            </section>
          ))
        )}
      </section>
    </main>
  );
}
