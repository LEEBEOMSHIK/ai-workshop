"use client";

import { type KeyboardEvent, useRef, useState } from "react";

import { ModelLabPage } from "../models/ModelLabPage";
import { ComparisonPanel } from "./ComparisonPanel";
import { GenerativeEvaluationPanel } from "./GenerativeEvaluationPanel";
import { ConfigurationBuilder } from "./ConfigurationBuilder";
import { SavedConfigurationList } from "./SavedConfigurationList";
import type { ConfigurationStudioData, SavedConfiguration } from "./api";

type StudioTab = "configuration" | "comparison" | "models";

const tabs: Array<{ id: StudioTab; label: string }> = [
  { id: "configuration", label: "RAG 구성" },
  { id: "comparison", label: "비교 실험" },
  { id: "models", label: "모델 레지스트리" },
];

export function ConfigurationStudioPage({ initialData, initialTab, initialRunId, initialCaseId }: {
  initialData: ConfigurationStudioData; initialTab?: string; initialRunId?: string; initialCaseId?: string;
}) {
  const [activeTab, setTab] = useState<StudioTab>(initialTab === "comparison" || initialTab === "models" ? initialTab : "configuration");
  const [evaluationKind, setEvaluationKind] = useState(initialRunId && !initialData.runs.some(run => run.id === initialRunId) ? "generative" : "extractive");
  const [generativeOpened, setGenerativeOpened] = useState(evaluationKind === "generative");
  function setActiveTab(tab: StudioTab) {
    setTab(tab);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    window.history.replaceState(null, "", url);
  }
  const [configurations, setConfigurations] = useState(initialData.configurations);
  const [compareVersionIds, setCompareVersionIds] = useState<string[]>([]);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  function handleSaved(configuration: SavedConfiguration, addToComparison: boolean) {
    setConfigurations((current) => {
      const withoutSameVersion = current.filter(
        (candidate) => candidate.version_id !== configuration.version_id,
      );
      return [...withoutSameVersion, configuration];
    });
    if (addToComparison) {
      setCompareVersionIds((current) => [...new Set([...current, configuration.version_id])]);
      setActiveTab("comparison");
    }
  }

  function handleConfigurationUpdated(configuration: SavedConfiguration) {
    setConfigurations((current) => current.map((candidate) =>
      candidate.version_id === configuration.version_id ? configuration : candidate,
    ));
  }

  function handleDefaultPromoted(promoted: SavedConfiguration, refreshed: SavedConfiguration[]) {
    setConfigurations((current) => current.map((candidate) => {
      const updated = candidate.version_id === promoted.version_id
        ? promoted
        : refreshed.find((item) => item.version_id === candidate.version_id) ?? candidate;
      const isDefault = candidate.version_id === promoted.version_id;
      return { ...updated, is_default: isDefault, experimental: !(updated.evaluation_state === "passed" && isDefault) };
    }));
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    let nextIndex = index;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    setActiveTab(tabs[nextIndex].id);
    tabRefs.current[nextIndex]?.focus();
  }

  return (
    <main className="configuration-studio-shell">
      <header className="configuration-studio-header">
        <p className="eyebrow">RAG CONFIGURATION STUDIO</p>
        <h1>RAG 구성 스튜디오</h1>
        <p>서버에 등록된 불변 프로파일을 조합하고, 저장된 정확한 버전만 비교합니다.</p>
      </header>

      <div className="studio-tabs" role="tablist" aria-label="RAG 구성 스튜디오">
        {tabs.map((tab, index) => (
          <button
            key={tab.id}
            ref={(element) => { tabRefs.current[index] = element; }}
            type="button"
            role="tab"
            id={`studio-tab-${tab.id}`}
            aria-controls={`studio-panel-${tab.id}`}
            aria-selected={activeTab === tab.id}
            tabIndex={activeTab === tab.id ? 0 : -1}
            onClick={() => setActiveTab(tab.id)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <section
        role="tabpanel"
        id="studio-panel-configuration"
        aria-labelledby="studio-tab-configuration"
        hidden={activeTab !== "configuration"}
      >
        {activeTab === "configuration" ? (
          <div className="configuration-workspace">
            <SavedConfigurationList
              configurations={configurations}
              models={initialData.models}
              profiles={initialData.profiles}
            />
            <ConfigurationBuilder
              configurations={configurations}
              models={initialData.models}
              profiles={initialData.profiles}
              workspaces={initialData.workspaces}
              onSaved={handleSaved}
            />
          </div>
        ) : null}
      </section>

      <section
        role="tabpanel"
        id="studio-panel-comparison"
        aria-labelledby="studio-tab-comparison"
        hidden={activeTab !== "comparison"}
      >
        <div role="group" aria-label="평가 종류">
          <button type="button" aria-pressed={evaluationKind === "extractive"} onClick={() => setEvaluationKind("extractive")}>추출형 v1</button>
          <button type="button" aria-pressed={evaluationKind === "generative"} onClick={() => { setEvaluationKind("generative"); setGenerativeOpened(true); }}>생성형 generative-v1</button>
        </div>
        <div hidden={evaluationKind !== "extractive"}>
          <ComparisonPanel
            configurations={configurations}
            initialRuns={initialData.runs}
            initialSelectedVersionIds={compareVersionIds}
            workspaces={initialData.workspaces}
            onConfigurationUpdated={handleConfigurationUpdated}
            onDefaultPromoted={handleDefaultPromoted}
          />
        </div>
        {generativeOpened ? <div hidden={evaluationKind !== "generative"}><GenerativeEvaluationPanel
          configurations={configurations} workspaces={initialData.workspaces}
          initialRunId={initialRunId} initialCaseId={initialCaseId}
          onConfigurationUpdated={handleConfigurationUpdated}
        /></div> : null}
      </section>

      <section
        role="tabpanel"
        id="studio-panel-models"
        aria-labelledby="studio-tab-models"
        hidden={activeTab !== "models"}
      >
        {activeTab === "models" ? (
          <ModelLabPage
            embedded
            initialModels={initialData.models}
            initialProfiles={initialData.profiles}
          />
        ) : null}
      </section>
    </main>
  );
}

