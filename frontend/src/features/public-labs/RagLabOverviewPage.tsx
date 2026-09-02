import Link from "next/link";

import { loginPath, routes } from "../../shared/routing/routes";
import { PublicNavigation } from "../navigation/PublicNavigation";
import styles from "./PublicLabScene.module.css";

export function RagLabOverviewPage() {
  return (
    <main className={styles.page}>
      <PublicNavigation />
      <section className={styles.hero} aria-labelledby="rag-lab-title">
        <p className={styles.eyebrow}>RETRIEVAL · EVIDENCE · GENERATION</p>
        <h1 id="rag-lab-title">RAG 기술 연구실</h1>
        <p>현재 검증된 검색 기능과 다음 공개 서비스 준비 범위를 구분해 소개합니다.</p>
        <Link
          className={styles.labLink}
          href={loginPath(routes.workshopRagSearch)}
        >
          로그인하고 현재 검색 기능 사용하기
        </Link>
      </section>
      <section className={styles.scene} aria-label="RAG 기술 개요">
        <section>
          <h2>담당 기술</h2>
          <ul>
            <li>문서 파싱과 구조 청킹</li>
            <li>BM25 + bi-encoder + RRF</li>
            <li>정확 일치와 의미 일치를 구분한 원문 하이라이트</li>
          </ul>
        </section>
        <section>
          <h2>현재 사용할 수 있는 기능</h2>
          <ul>
            <li>로그인 작업소의 자산운용 문서 검색</li>
            <li>전사·개인·임시 검색 범위</li>
            <li>원문 근거 이동</li>
          </ul>
        </section>
        <section>
          <h2>공개 서비스 준비</h2>
          <ul>
            <li>다중 도메인과 불변 공개 릴리스</li>
            <li>대화형 LLM 답변과 인용 검증</li>
          </ul>
        </section>
        <section>
          <h2>관리 경계</h2>
          <ul>
            <li>모델·색인·검색 구성은 시스템 관리자 영역에서만 변경</li>
          </ul>
        </section>
      </section>
    </main>
  );
}
