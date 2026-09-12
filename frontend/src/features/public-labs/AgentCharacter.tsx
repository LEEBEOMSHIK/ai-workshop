"use client";

import type { PublicLab } from "./catalog";
import type { ReactNode } from "react";
import { InteractiveAgentCharacter } from "./InteractiveAgentCharacter";
import Link from "next/link";
import type { StudySnapshot } from "../publishing/types";
import { publicStudyPath } from "../../shared/routing/routes";

interface AgentCharacterProps {
  lab: PublicLab;
  variant: "roaming" | "working";
  visual?: ReactNode;
  dialogAction?: {
    href: string;
    label: string;
  };
  relatedStudies?: readonly StudySnapshot[];
}

export function AgentCharacter({ lab, variant, dialogAction, relatedStudies = [], visual }: AgentCharacterProps) {
  return (
    <InteractiveAgentCharacter
      profile={{
        name: lab.manager.name,
        role: lab.manager.role,
        statusLabel: lab.statusLabel,
        eyebrow: lab.eyebrow,
      }}
      variant={variant}
      visual={visual}
      action={dialogAction ?? {
        href: lab.href,
        label: lab.manager.ctaLabel,
      }}
    >
      <p>{lab.manager.intro}</p>
      <p>{lab.manager.invitation}</p>
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
