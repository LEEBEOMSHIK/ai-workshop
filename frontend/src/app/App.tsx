import { Link } from "react-router-dom";

export function App() {
  return (
    <main className="workshop-shell">
      <div className="ambient ambient-one" aria-hidden="true" />
      <div className="ambient ambient-two" aria-hidden="true" />
      <section className="hero" aria-labelledby="workshop-title">
        <p className="eyebrow">LEE BEOMSHIK&apos;S PRIVATE LAB</p>
        <h1 id="workshop-title">AI Workshop</h1>
        <p className="hero-copy">
          공부한 흔적을 실험으로 바꾸고, 검증한 기술을 나만의 AI 작업자로
          성장시키는 로컬 우선 작업소입니다.
        </p>
        <div className="status-row" aria-label="현재 작업소 상태">
          <span className="status-dot" aria-hidden="true" />
          <span>작업소 기반을 구성하고 있습니다</span>
        </div>
      </section>
      <section className="lab-grid" aria-label="작업소 영역">
        <article className="lab-card lab-card-primary">
          <p className="card-index">LAB 01</p>
          <h2>Asset Management RAG</h2>
          <p>
            전문 문서를 찾고, 근거 위치를 의미 단위로 강조하는 AI 검색을
            준비하고 있습니다.
          </p>
          <nav className="lab-card-actions" aria-label="Asset Management RAG 바로가기">
            <Link to="/rag/search">근거 검색</Link>
            <Link to="/rag/configurations">RAG 구성</Link>
            <Link to="/rag/models">모델 관리</Link>
          </nav>
          <span className="card-state">검색 수직 슬라이스 사용 가능</span>
        </article>
        <article className="lab-card">
          <p className="card-index">KNOWLEDGE</p>
          <h2>학습과 실험 기록</h2>
          <p>자유 메모와 재현 가능한 실험을 연결하는 공간입니다.</p>
          <span className="card-state muted">Coming next</span>
        </article>
        <article className="lab-card">
          <p className="card-index">AGENTS</p>
          <h2>에이전트 조직</h2>
          <p>총괄 관리자와 전문 작업자가 계층적으로 협업합니다.</p>
          <span className="card-state muted">Coming next</span>
        </article>
      </section>
    </main>
  );
}
