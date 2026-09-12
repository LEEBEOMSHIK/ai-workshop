"use client";

import { InteractiveAgentCharacter } from "./InteractiveAgentCharacter";
import type { RagLabAgent } from "./rag-lab-agents";
import styles from "./PublicLabScene.module.css";
import { PixelPerson } from "./PixelPerson";
import { ragStationArt } from "./rag-station-art";
import Link from "next/link";
import type { StudySnapshot } from "../publishing/types";
import { publicStudyPath } from "../../shared/routing/routes";

interface RagWorkerCharacterProps {
  agent: RagLabAgent;
  relatedStudies?: readonly StudySnapshot[];
}

export function RagWorkerCharacter({ agent, relatedStudies = [] }: RagWorkerCharacterProps) {
  return (
    <InteractiveAgentCharacter
      profile={{
        name: agent.name,
        role: agent.role,
        statusLabel: agent.statusLabel,
        eyebrow: agent.eyebrow,
      }}
      variant="working"
      visual={<PixelPerson identity={ragStationArt(agent.slug).person} />}
    >
      <p>{agent.intro}</p>
      <dl className={styles.agentBrief}>
        <div>
          <dt>현재 작업</dt>
          <dd>{agent.currentWork}</dd>
        </div>
        <div>
          <dt>입력과 결과</dt>
          <dd>{agent.inputOutput}</dd>
        </div>
        <div>
          <dt>다음 인계</dt>
          <dd>{agent.handoff}</dd>
        </div>
      </dl>
      {relatedStudies.length > 0 ? (
        <div>
          <h3>관련 공개 연구</h3>
          <ul>
            {relatedStudies.map((study) => (
              <li key={study.content.slug}>
                <Link href={publicStudyPath(study.content.slug)} prefetch={false}>{study.content.title}</Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </InteractiveAgentCharacter>
  );
}
