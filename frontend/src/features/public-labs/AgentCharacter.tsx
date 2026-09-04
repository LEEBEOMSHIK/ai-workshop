"use client";

import type { PublicLab } from "./catalog";
import { InteractiveAgentCharacter } from "./InteractiveAgentCharacter";

interface AgentCharacterProps {
  lab: PublicLab;
  variant: "roaming" | "working";
  dialogAction?: {
    href: string;
    label: string;
  };
}

export function AgentCharacter({ lab, variant, dialogAction }: AgentCharacterProps) {
  return (
    <InteractiveAgentCharacter
      profile={{
        name: lab.manager.name,
        role: lab.manager.role,
        statusLabel: lab.statusLabel,
        eyebrow: lab.eyebrow,
      }}
      variant={variant}
      action={dialogAction ?? {
        href: lab.href,
        label: lab.manager.ctaLabel,
      }}
    >
      <p>{lab.manager.intro}</p>
      <p>{lab.manager.invitation}</p>
    </InteractiveAgentCharacter>
  );
}
