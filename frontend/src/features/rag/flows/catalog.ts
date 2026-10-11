import type { FlowDefinition } from "../../flowcharts/types";
import { ingestionFlow } from "./ingestion";
import { answerFlow } from "./answer";
import { sessionsFlow } from "./sessions";
import { multiturnFlow } from "./multiturn";

export const ragFlows: readonly FlowDefinition[] = [ingestionFlow, answerFlow, sessionsFlow, multiturnFlow];
