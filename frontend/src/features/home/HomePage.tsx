import Link from "next/link";

import { PublicNavigation } from "../navigation/PublicNavigation";
import { AgentCharacter } from "../public-labs/AgentCharacter";
import { listPublicLabs } from "../public-labs/catalog";
import { routes } from "../../shared/routing/routes";
import styles from "../public-labs/PublicLabScene.module.css";

export function HomePage() {
  const labs = listPublicLabs();

  return (
    <main className={styles.page}>
      <PublicNavigation />
      <section className={styles.hero} aria-labelledby="public-workshop-title">
        <p className={styles.eyebrow}>LEE BEOMSHIK&apos;S AI WORKSHOP</p>
        <h1 id="public-workshop-title">AI 기술 관리자들이 일하는 작업소</h1>
        <p>공부하고 실험한 AI 기술을 실제 기능과 해결 과정으로 연결합니다.</p>
        <Link href={routes.labs}>AI Lab 둘러보기</Link>
      </section>
      <section className={styles.scene} aria-label="기술 관리자 캐릭터">
        {labs.map((lab) => (
          <AgentCharacter key={lab.slug} lab={lab} variant="roaming" />
        ))}
      </section>
    </main>
  );
}
