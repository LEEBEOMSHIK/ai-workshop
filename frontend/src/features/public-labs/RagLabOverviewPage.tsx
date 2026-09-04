import Link from "next/link";

import { loginPath, routes } from "../../shared/routing/routes";
import { PublicNavigation } from "../navigation/PublicNavigation";
import { AgentCharacter } from "./AgentCharacter";
import { listPublicLabs } from "./catalog";
import { listRagLabAgents } from "./rag-lab-agents";
import { RagWorkerCharacter } from "./RagWorkerCharacter";
import styles from "./PublicLabScene.module.css";

export function RagLabOverviewPage() {
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
        <Link className={styles.labLink} href={loginPath(routes.workshopRagSearch)}>
          로그인하고 현재 검색 기능 사용하기
        </Link>
      </section>

      <section
        className={styles.ragWorkroom}
        aria-labelledby="rag-pipeline-title"
      >
        <div className={styles.workroomGrid} aria-hidden="true" />
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
              dialogAction={{
                href: loginPath(routes.workshopRagSearch),
                label: "현재 검색 기능 사용하기",
              }}
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
                <div className={styles.stationConsole} aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <RagWorkerCharacter agent={agent} />
              </section>
            </li>
          ))}
        </ol>
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
