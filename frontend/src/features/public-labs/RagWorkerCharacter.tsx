"use client";

import { InteractiveAgentCharacter } from "./InteractiveAgentCharacter";
import type { RagLabAgent } from "./rag-lab-agents";
import styles from "./PublicLabScene.module.css";

interface RagWorkerCharacterProps {
  agent: RagLabAgent;
}

export function RagWorkerCharacter({ agent }: RagWorkerCharacterProps) {
  return (
    <InteractiveAgentCharacter
      profile={{
        name: agent.name,
        role: agent.role,
        statusLabel: agent.statusLabel,
        eyebrow: agent.eyebrow,
      }}
      variant="working"
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
    </InteractiveAgentCharacter>
  );
}
