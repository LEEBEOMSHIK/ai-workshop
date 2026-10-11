import type { FlowArchitecture } from "./types";
import styles from "./Flowcharts.module.css";

export function FlowArchitectureView({ title, architecture }: { title: string; architecture: FlowArchitecture }) {
  return <section className={styles.architecture} aria-label="기술 구성과 내부 동작">
    <p className={styles.eyebrow}>구성 요소와 데이터의 이동</p>
    <h3>어떤 기술로, 어떻게 연결하나요?</h3>
    <p className={styles.architectureSummary}>{architecture.summary}</p>
    <figure className={styles.architectureDiagram} aria-label={`${title} 기술 구성도`}>
      <figcaption>주요 연결을 읽는 구성도입니다. 아래 번호 순서로 데이터가 이동합니다. 조건·실패 경로는 세부 흐름에서 확인하세요.</figcaption>
      <ol className={styles.architectureSteps}>
        {architecture.steps.map((step, index) => <li key={step.title}>
          <span className={styles.architectureNumber} aria-hidden="true">{index + 1}</span>
          <strong>{step.title}</strong><small>{step.technology}</small><p>{step.explanation}</p>
        </li>)}
      </ol>
    </figure>
    <aside className={styles.example} aria-label="설명용 예시">
      <h4>이해를 돕는 가상 예시</h4>
      <dl><div><dt>{architecture.example.followup ? "첫 질문" : "입력"}</dt><dd>{architecture.example.question}</dd></div>
        {architecture.example.followup && <div><dt>이어서 질문</dt><dd>{architecture.example.followup}</dd></div>}</dl>
      <p>{architecture.example.explanation}</p>
      <small>실제 실행 결과나 답변 품질을 확인한 사례가 아닙니다.</small>
    </aside>
    <details className={styles.architectureMore}>
      <summary>사용 기술과 구현 방식</summary>
      <dl className={styles.technologyGrid}>{architecture.technologies.map(item => <div key={item.name}>
        <dt>{item.name}</dt><dd><p>{item.purpose}</p><p>{item.implementation}</p></dd>
      </div>)}</dl>
    </details>
    <details className={styles.architectureMore}>
      <summary>적용 범위·구현 근거</summary>
      <ul>{architecture.boundaries.map(item => <li key={item}>{item}</li>)}</ul>
      <ul className={styles.architectureSources}>{architecture.references.map(source => <li key={source.reference}>
        <span>{source.title}</span><code>{source.reference}</code>
      </li>)}</ul>
    </details>
  </section>;
}
