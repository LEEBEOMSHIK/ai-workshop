import { PublicNavigation } from "../navigation/PublicNavigation";
import { AgentCharacter } from "./AgentCharacter";
import type { PublicLab } from "./catalog";
import styles from "./PublicLabScene.module.css";

interface LabWorldPageProps {
  labs: readonly PublicLab[];
}

export function LabWorldPage({ labs }: LabWorldPageProps) {
  return (
    <main className={styles.page}>
      <PublicNavigation />
      <section className={styles.hero} aria-labelledby="lab-world-title">
        <p className={styles.eyebrow}>PUBLIC AI WORKSHOP</p>
        <h1 id="lab-world-title">AI Lab</h1>
        <p>기술 관리자와 대화하며 현재 공개된 AI 연구실을 살펴보세요.</p>
      </section>
      <section className={styles.scene} aria-label="AI Lab 작업 현장">
        {labs.map((lab) => (
          <section key={lab.slug} aria-labelledby={`${lab.slug}-lab-title`}>
            <p className={styles.eyebrow}>{lab.eyebrow}</p>
            <h2 id={`${lab.slug}-lab-title`}>{lab.name}</h2>
            <p>{lab.description}</p>
            <AgentCharacter lab={lab} variant="working" />
          </section>
        ))}
      </section>
    </main>
  );
}
