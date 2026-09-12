import Link from "next/link";

import { routes } from "../../shared/routing/routes";
import { PublicNavigation } from "../navigation/PublicNavigation";
import { AgentCharacter } from "./AgentCharacter";
import { listPublicLabs } from "./catalog";
import { listRagLabAgents } from "./rag-lab-agents";
import { RagWorkerCharacter } from "./RagWorkerCharacter";
import styles from "./PublicLabScene.module.css";
import { PixelPerson } from "./PixelPerson";
import { RagWorkbench } from "./RagWorkbench";
import type { StudySnapshot } from "../publishing/types";
import { relatedStudiesForWorker } from "../publishing/study-links";

export function RagLabOverviewPage({ studies = [] }: { studies?: readonly StudySnapshot[] }) {
  const ragLab = listPublicLabs().find((lab) => lab.slug === "rag");
  const agents = listRagLabAgents();

  if (!ragLab) {
    return (
      <main className={styles.page}>
        <PublicNavigation />
        <p className={styles.ragLabUnavailable} role="alert">
          공개 RAG 연구실 정보를 불러오지 못했습니다
        </p>
      </main>
    );
  }

  return (
    <main className={`${styles.page} ${styles.ragLabPage}`}>
      <PublicNavigation />
      <section className={styles.ragLabHeader} aria-labelledby="rag-lab-title">
        <div>
          <p className={styles.eyebrow}>{ragLab.eyebrow}</p>
          <h1 id="rag-lab-title">{ragLab.name}</h1>
          <p>
            RAG 총괄과 각 기술 담당자가 문서를 검색 가능한 근거로 바꾸는 과정을
            살펴보세요. 캐릭터에게 말을 걸면 현재 맡은 일을 직접 설명합니다.
          </p>
        </div>
        <div className={styles.ragHeaderActions}>
        <Link className={styles.returnToOffice} href="/">← 사장실 · 로비로 돌아가기</Link>
        <Link className={styles.labLink} href={routes.workshopRagSearch}>
          현재 검색 기능 사용하기
        </Link>
        <Link className={styles.labLink} href={routes.ragStudies}>공개 연구 기록</Link>
        </div>
      </section>

      <section
        className={styles.ragWorkroom}
        aria-labelledby="rag-pipeline-title"
      >
        <div className={styles.workroomGrid} aria-hidden="true" />
        <div className={styles.labBackWall} aria-hidden="true"><span /><span /><span /></div>
        <section className={styles.commandDeck}>
          <div className={styles.commandCopy}>
            <p className={styles.eyebrow}>RAG COMMAND</p>
            <h2 id="rag-pipeline-title">RAG 작업 파이프라인</h2>
            <p>
              총괄이 전체 검색 품질과 근거 추적을 관리하고, 여섯 담당자가 현재 구현된
              공정을 순서대로 이어서 작업합니다.
            </p>
            <p className={styles.agentBoundaryNote}>
              화면의 캐릭터는 각 기술 책임을 설명하며, 실제 처리는 검증된
              서비스와 worker가 수행합니다.
            </p>
          </div>
          <div className={styles.commandAgent}>
            <AgentCharacter
              lab={ragLab}
              variant="working"
              visual={<PixelPerson identity="rag-chief" />}
              dialogAction={{
                href: routes.workshopRagSearch,
                label: "현재 검색 기능 사용하기",
              }}
              relatedStudies={studies}
            />
          </div>
        </section>

        <ol className={styles.workerStations}>
          {agents.map((agent, index) => (
            <li key={agent.slug} className={styles.workerStation}>
              <section aria-labelledby={`${agent.slug}-station-title`}>
                <header className={styles.stationHeader}>
                  <span className={styles.stationOrder} aria-hidden="true">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <p>{agent.eyebrow}</p>
                    <h3 id={`${agent.slug}-station-title`}>{agent.role}</h3>
                  </div>
                </header>
                <RagWorkbench slug={agent.slug} />
                <RagWorkerCharacter agent={agent} relatedStudies={relatedStudiesForWorker(agent.slug, studies)} />
              </section>
            </li>
          ))}
        </ol>
        <div className={styles.workroomThreshold}><span>RAG RESEARCH STUDIO</span><p>캐릭터를 클릭해 담당 업무 듣기 · 공개 소개 연출</p></div>
      </section>

      <section className={styles.ragCapabilityDeck} aria-label="현재 RAG 연구 범위">
        <article>
          <p className={styles.eyebrow}>RETRIEVAL</p>
          <h2>현재 검색 기준선</h2>
          <p>BM25 + bi-encoder + RRF</p>
        </article>
        <article>
          <p className={styles.eyebrow}>EVIDENCE</p>
          <h2>현재 근거 표시</h2>
          <p>정확 일치와 의미 일치를 구분한 원문 하이라이트</p>
        </article>
        <article>
          <p className={styles.eyebrow}>BOUNDARY</p>
          <h2>운영 경계</h2>
          <p>모델·색인·검색 구성 변경은 인증된 시스템 관리자 영역에서만 수행합니다.</p>
        </article>
      </section>
    </main>
  );
}
