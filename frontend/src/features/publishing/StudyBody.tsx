import type { StudySnapshot } from "./types";
import { legacyStudySubsectionLabels } from "./study-subsections";
import styles from "./Publishing.module.css";

function StudyParagraphs({ text, subsections = false }: { text: string; subsections?: boolean }) {
  return text.split(/\r?\n(?:[\t ]*\r?\n)+/).filter((paragraph) => paragraph.trim()).map((paragraph, index) => {
    const lineBreak = /\r?\n/.exec(paragraph);
    const label = lineBreak ? paragraph.slice(0, lineBreak.index) : "";
    if (subsections && lineBreak && legacyStudySubsectionLabels.has(label)) {
      return (
        <div className={styles.subsection} key={index}>
          <h3>{label}</h3>
          <p className={styles.plainText}>{paragraph.slice(lineBreak.index + lineBreak[0].length)}</p>
        </div>
      );
    }
    return <p className={styles.plainText} key={index}>{paragraph}</p>;
  });
}

export function StudyBody({ snapshot }: { snapshot: StudySnapshot }) {
  const { content } = snapshot;
  return (
    <article className={styles.reader} aria-labelledby={`study-${content.slug}-title`}>
      <header className={styles.readerHeader}>
        <p className={styles.muted}>리비전 {snapshot.revision}</p>
        <h1 id={`study-${content.slug}-title`}>{content.title}</h1>
        <p className={`${styles.plainText} ${styles.readerSummary}`}>{content.summary}</p>
        <div className={styles.topics} aria-label="기술 주제">
          {content.topic_keys.map((topic) => <span key={topic}>{topic}</span>)}
        </div>
        {content.persona ? <p>안내: {content.persona.label}</p> : null}
      </header>
      <section className={styles.bodySection} aria-labelledby={`study-${content.slug}-body`}>
        <h2 id={`study-${content.slug}-body`}>연구 기록</h2>
        <StudyParagraphs text={content.body} subsections />
      </section>
      <section className={styles.bodySection} aria-labelledby={`study-${content.slug}-verification`}>
        <h2 id={`study-${content.slug}-verification`}>과거 검증 기록</h2>
        <StudyParagraphs text={content.verification} />
        <p className={styles.help}>이 기록은 당시의 검증 결과이며 현재 서비스 가용성을 증명하지 않습니다.</p>
      </section>
      <section className={styles.bodySection} aria-labelledby={`study-${content.slug}-limitations`}>
        <h2 id={`study-${content.slug}-limitations`}>남은 한계</h2>
        <StudyParagraphs text={content.limitations} />
      </section>
    </article>
  );
}
