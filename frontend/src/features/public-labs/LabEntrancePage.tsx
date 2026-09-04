import Link from "next/link";

import { routes } from "../../shared/routing/routes";
import { PublicNavigation } from "../navigation/PublicNavigation";
import { AgentCharacter } from "./AgentCharacter";
import type { PublicLabCatalogResult } from "./catalog";
import styles from "./PublicLabScene.module.css";

interface LabEntrancePageProps {
  catalog: PublicLabCatalogResult;
}

export function LabEntrancePage({ catalog }: LabEntrancePageProps) {
  const labs = catalog.status === "ready" ? catalog.labs : [];

  return (
    <main className={`${styles.page} ${styles.entrancePage}`}>
      <PublicNavigation />
      <section className={styles.entranceHero} aria-labelledby="lab-entrance-title">
        <div className={styles.entranceCopy}>
          <p className={styles.eyebrow}>AI WORKSHOP · PUBLIC ENTRANCE</p>
          <h1 id="lab-entrance-title">AI 기술 관리자들을 만나는 연구소 입구</h1>
          <p>
            연구소를 돌아다니는 관리자에게 말을 걸어 보세요. 각 관리자가 맡은 AI 기술과
            현재 공개된 연구실을 안내합니다.
          </p>
          <Link className={styles.entranceLink} href={routes.labs}>
            연구실 전체 보기
          </Link>
        </div>

        <section className={styles.entranceScene} aria-label="AI 연구소 입구 광장">
          <div className={styles.entrancePortal} aria-hidden="true">
            <span>AI LABS</span>
          </div>
          <div className={styles.entrancePath} aria-hidden="true" />
          <div className={styles.entranceAgents}>
            {catalog.status === "error" ? (
              <p className={styles.entranceEmpty} role="alert">
                연구소 입구 정보를 불러오지 못했습니다
              </p>
            ) : labs.length === 0 ? (
              <p className={styles.entranceEmpty}>
                현재 공개된 기술 관리자를 준비하고 있습니다
              </p>
            ) : (
              labs.map((lab) => (
                <section
                  key={lab.slug}
                  className={styles.entranceAgent}
                  aria-labelledby={`${lab.slug}-entrance-manager`}
                >
                  <p className={styles.entranceStatus}>{lab.statusLabel}</p>
                  <h2 id={`${lab.slug}-entrance-manager`}>{lab.name} 관리자</h2>
                  <AgentCharacter lab={lab} variant="roaming" />
                </section>
              ))
            )}
          </div>
        </section>
      </section>
    </main>
  );
}
