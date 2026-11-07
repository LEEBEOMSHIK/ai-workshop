import type { CSSProperties } from "react";
import { LearningRecordClassification, LearningSequenceDetail } from "../../../../features/learning/LearningSequence";
import { ColorValue } from "./ColorValue";
import { ComponentCatalog } from "./ComponentCatalog";
import styles from "./Gallery.module.css";

const colors = [
  ["메인 배경", "background", "작업 화면의 바탕"],
  ["서브 배경", "surface", "패널과 분리된 영역"],
  ["프라이머리", "primary", "브랜드의 중심 색"],
  ["세컨더리", "secondary", "포인트와 탐색 단서"],
  ["성공·실행", "success", "완료 상태와 결과"],
  ["하이라이트", "highlight", "강조할 지점"],
  ["기본 텍스트", "text", "제목과 본문의 글자색"],
] as const;
const gradients = [
  ["brand", "연구·AI·혁신"],
  ["growth", "실험·성장·결과"],
] as const;
const categories = [
  ["research", "연구"], ["experiment", "실험"], ["data", "데이터"],
  ["analysis", "분석"], ["development", "개발"], ["learning", "학습"],
] as const;
const tokenStyle = (name: string) => ({ "--sample": `var(--${name})` } as CSSProperties);

export default function DesignSystemPage() {
  return <main className={styles.gallery}>
    <header className={styles.hero}>
      <div>
        <p className={styles.kicker}>AI WORKSHOP <span>/</span> UI GUIDE</p>
        <h1>디자인 시스템</h1>
        <p className={styles.lead}>작업소에서 쓰는 공통 컴포넌트와 색상, 화면별 적용 예시를 한곳에서 찾아보세요.</p>
      </div>
      <div className={styles.heroArt} aria-hidden="true"><i /><i /><i /></div>
    </header>
    <nav aria-label="디자인 시스템 목차" className={styles.index}>
      <a href="#components"><span>01</span> 공통 컴포넌트</a>
      <a href="#palette"><span>02</span> 색상 팔레트</a>
      <a href="#screen-patterns"><span>03</span> 화면 적용 예시</a>
    </nav>
    <section id="components" className={styles.section} aria-labelledby="components-heading">
      <div className={styles.heading}><span>01</span><h2 id="components-heading">공통 컴포넌트</h2></div>
      <p>용도에 맞는 컴포넌트를 찾고, 사용 코드를 펼쳐 import 경로와 JSX 예시를 확인하세요.</p>
      <ComponentCatalog />
    </section>

    <section id="palette" className={styles.section} aria-labelledby="palette-heading">
      <div className={styles.heading}><span>02</span><h2 id="palette-heading">색상 팔레트</h2></div>
      <p>아래 견본은 현재 화면 모드의 색상입니다. 메뉴 하단의 화면 모드를 바꾸면 견본과 색상값이 함께 바뀝니다.</p>
      <ul className={styles.palette}>{colors.map(([label, name, use]) => <li key={name} style={tokenStyle(`color-${name}`)}>
        <div className={styles.swatch} aria-hidden="true" />
        <h3>{label}</h3><ColorValue token={`--color-${name}`} />
        <p>{use}</p><code>--color-{name}</code>
      </li>)}</ul>

      <h3 className={styles.subhead}>그라디언트</h3>
      <div className={styles.gradients}>{gradients.map(([name, label]) => <figure key={name} style={tokenStyle(`gradient-${name}`)}>
        <div aria-hidden="true" /><figcaption><strong>{label}</strong><code>--gradient-{name}</code></figcaption>
      </figure>)}</div>

      <h3 className={styles.subhead}>활동 분류</h3>
      <p>색과 활동명을 함께 표시해 연구 주제와 기록을 구분합니다.</p>
      <ul className={styles.categories}>{categories.map(([name, label]) => <li key={name} style={tokenStyle(`color-category-${name}`)}>
        <strong><i aria-hidden="true" />{label}</strong><code>--color-category-{name}</code>
      </li>)}</ul>
    </section>

    <section id="screen-patterns" className={styles.section} aria-labelledby="screen-patterns-heading">
      <div className={styles.heading}><span>03</span><h2 id="screen-patterns-heading">화면 적용 예시</h2></div>
      <h3 className={styles.subhead}>학습 출발점과 개선 결과</h3>
      <p>학습 차수와 모델의 출발점을 구분합니다. 목표·확인된 결과·남은 문제는 같은 위치에서 읽고, 실행 근거는 필요할 때 펼칩니다. 아래는 표시 방법을 위한 합성 예시입니다.</p>
      <LearningRecordClassification kind="experiment" topicKeys={["fine-tuning", "rag"]} topics={[
        { key: "fine-tuning", label: "Fine-tuning" },
        { key: "rag", label: "RAG" },
      ]} />
      <LearningSequenceDetail status="completed" value={{
        series: "합성 문서 답변 실험", step: 2, performed_on: null,
        start_mode: "continued", source_label: "선행 실험에서 저장한 어댑터",
        source_evidence: "실행 기록의 입력 어댑터와 선행 실험의 출력 파일 식별값을 대조합니다.",
        objective: "질문에서 요구한 조건을 빠짐없이 답변하기",
        outcome_status: "mixed", outcome: "학습에 사용한 질문 일부에서 조건 누락을 수정했습니다.",
        remaining: "미사용 질문에서의 개선은 확인되지 않았습니다.",
      }} />
      <p><code>features/learning/LearningSequence.tsx</code>의 실제 컴포넌트를 사용합니다. 출발점 미기록은 ‘미확인’, 평가 미기록은 ‘미평가’로 표시하며 차수나 문구에서 추정하지 않습니다.</p>
      <p>기술 주제는 제목 바로 아래에서 공통 <code>StatusBadge</code>의 중립 스타일로 구분합니다. 분류 표시는 버튼이 아니며, 수행 상태와 분리합니다.</p>
      <p>학습 목록에서는 제목·분류·결과·여백을 포함한 카드 전체가 하나의 상세 링크입니다. 카드 표면 전체에 hover와 키보드 포커스를 표시하며, Tab으로 선택한 뒤 Enter로 이동할 수 있습니다. 링크 이름은 기록 제목으로 읽고 카드 내부에 다른 조작을 중첩하지 않습니다.</p>
      <p>작성은 ‘새 기록’ 하나로 시작합니다. 기본 자유 기록에 ‘실험 항목 추가’를 선택해 목적·가설·절차·결과를 덧붙입니다. 같은 작성 중 항목을 껐다 켜도 입력은 보존하며, 끈 상태로 저장하면 실험 항목은 저장하지 않습니다.</p>
      <p>학습 목록은 간결한 제목과 오른쪽 주요 ‘＋ 새 기록’ 버튼으로 시작합니다. 정렬·상세 필터는 목록 위에, 표시 개수는 하단 페이지 이동 옆에 둡니다. 적용 조건은 접혀도 요약으로 읽을 수 있으며, 필터 초기화는 정렬과 표시 개수를 유지합니다.</p>
      <p>긴 학습 목록은 공통 <code>SelectField</code>로 페이지당 5·10·20개를 선택합니다. 기본은 5개이며, 개수를 바꾸면 다른 필터와 정렬을 유지한 채 첫 페이지로 돌아갑니다.</p>
    </section>
  </main>;
}
