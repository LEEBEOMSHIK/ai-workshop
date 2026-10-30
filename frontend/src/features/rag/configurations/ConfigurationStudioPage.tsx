"use client";

import Link from "next/link";
import { routes } from "../../../shared/routing/routes";
import buttonStyles from "../../../shared/ui/Button.module.css";
import { ChoiceGroup } from "../../../shared/ui/ChoiceGroup";
import styles from "./ConfigurationStudioComparison.module.css";
import adminStyles from "./ConfigurationAdmin.module.css";

import { type KeyboardEvent, useRef, useState } from "react";

import { ModelLabPage } from "../models/ModelLabPage";
import { ComparisonPanel } from "./ComparisonPanel";
import { GenerativeEvaluationPanel } from "./GenerativeEvaluationPanel";
import { ComparisonListPanel } from "../comparisons/ComparisonListPanel";
import { ConfigurationBuilder } from "./ConfigurationBuilder";
import { SavedConfigurationList } from "./SavedConfigurationList";
import type { ConfigurationStudioData, SavedConfiguration } from "./api";

type StudioTab = "configuration" | "comparison" | "models";

const tabs: Array<{ id: StudioTab; label: string }> = [
  { id: "configuration", label: "RAG 구성" },
  { id: "comparison", label: "비교 실험" },
  { id: "models", label: "모델 레지스트리" },
];

export function ConfigurationStudioPage({ initialData, initialTab, initialRunId, initialCaseId, initialComparisonView }: {
  initialData: ConfigurationStudioData; initialTab?: string; initialRunId?: string; initialCaseId?: string; initialComparisonView?: string;
}) {
  const [activeTab, setTab] = useState<StudioTab>(initialTab === "comparison" || initialTab === "models" ? initialTab : "configuration");
  const [configurationTask, setConfigurationTask] = useState("saved");
  const [builderOpened, setBuilderOpened] = useState(false);
  function selectConfigurationTask(task: string) {
    setConfigurationTask(task);
    if (task === "create") setBuilderOpened(true);
  }
  const [evaluationKind, setEvaluationKind] = useState(initialComparisonView === "stored" ? "stored" : initialRunId && !initialData.runs.some(run => run.id === initialRunId) ? "generative" : "extractive");
  const [generativeOpened, setGenerativeOpened] = useState(evaluationKind === "generative");
  function selectEvaluation(kind: "extractive" | "generative" | "stored") {
    setEvaluationKind(kind);
    if (kind === "generative") setGenerativeOpened(true);
    const url = new URL(window.location.href);
    if (kind === "stored") url.searchParams.set("view", "stored"); else url.searchParams.delete("view");
    window.history.replaceState(null, "", url);
  }
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
    setConfigurationTask("saved");
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
    <main className={`configuration-studio-shell ${adminStyles.admin} ${activeTab === "comparison" ? styles.compactShell : ""}`}>
      <header className={`configuration-studio-header ${activeTab === "comparison" ? styles.compactHeader : ""}`}>
        <p className="eyebrow">RAG CONFIGURATION STUDIO</p>
        <h1>RAG 구성 스튜디오</h1>
        <p>서버에 등록된 불변 프로파일을 조합하고, 저장된 정확한 버전만 비교합니다.</p>
        <Link className={`${buttonStyles.button} ${buttonStyles.secondary}`} href={routes.adminRagSetup}>모델 연결·RAG 간편 설정</Link>
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
          <div className={adminStyles.workspace}>
            <div className={adminStyles.taskIntro}>
              <h2>구성 확인 또는 새 조합 만들기</h2>
              <p>저장된 버전의 준비 상태를 확인하거나, 등록된 프로파일로 새 구성을 만드세요. 저장 후 비교 실험에서 정확한 버전을 평가할 수 있습니다.</p>
              <ChoiceGroup legend="구성 작업" variant="segmented" value={configurationTask} onChange={selectConfigurationTask}
                options={[{ value: "saved", label: "저장 구성 확인" }, { value: "create", label: "새 구성 만들기" }]} />
            </div>
            <div hidden={configurationTask !== "saved"}>
            <SavedConfigurationList
              configurations={configurations}
              models={initialData.models}
              profiles={initialData.profiles}
            />
            </div>
            {builderOpened ? <div hidden={configurationTask !== "create"}>
            <ConfigurationBuilder
              configurations={configurations}
              models={initialData.models}
              profiles={initialData.profiles}
              workspaces={initialData.workspaces}
              onSaved={handleSaved}
            />
            </div> : null}
          </div>
      </section>

      <section
        role="tabpanel"
        id="studio-panel-comparison"
        aria-labelledby="studio-tab-comparison"
        hidden={activeTab !== "comparison"}
      >
        <div className={styles.comparisonToolbar}>
          <div className={styles.kindPicker} role="group" aria-label="평가 종류">
            <button type="button" aria-pressed={evaluationKind === "extractive"} onClick={() => selectEvaluation("extractive")}>검색 품질 비교</button>
            <button type="button" aria-pressed={evaluationKind === "generative"} onClick={() => selectEvaluation("generative")}>답변 품질 비교</button>
            <button type="button" aria-pressed={evaluationKind === "stored"} onClick={() => selectEvaluation("stored")}>저장된 모델 비교</button>
          </div>
          <p className={styles.hint}><Link href="/admin/rag/executions">실제 대화 실행 이력</Link></p>
        </div>
        {activeTab === "comparison" && evaluationKind === "stored" ? <ComparisonListPanel /> : null}
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
        {activeTab === "models" ? <>
          <p><Link href="/admin/rag/models">모델·배포·생성 프로파일 등록하기</Link></p>
          <ModelLabPage
            embedded
            initialModels={initialData.models}
            initialProfiles={initialData.profiles}
          />
        </> : null}
      </section>
    </main>
  );
}

