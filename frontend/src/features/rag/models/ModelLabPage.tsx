"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  type JsonValue,
  type ModelDefinitionSummary,
  type ModelKind,
  type ProfileKind,
  type ProfileSummary,
  registerModelVersion,
  registerYamlProfile,
} from "./api";

interface ModelLabPageProps {
  initialModels?: ModelDefinitionSummary[];
  initialProfiles?: ProfileSummary[];
  embedded?: boolean;
}

const modelLabels: Record<ModelKind, string> = {
  embedding: "임베딩 모델",
  reranker: "리랭커 모델",
  llm: "LLM 모델",
};
const profileLabels: Record<ProfileKind, string> = {
  indexing: "색인 프로파일",
  retrieval: "검색 프로파일",
  generation: "생성 프로파일",
};
const evaluationLabels: Record<ProfileSummary["evaluation_state"], string> = {
  draft: "초안",
  pending: "평가 대기",
  passed: "평가 통과",
  failed: "평가 실패",
};

export function ModelLabPage({
  initialModels = [],
  initialProfiles = [],
  embedded = false,
}: ModelLabPageProps) {
  const [models, setModels] = useState(initialModels.filter(isSupportedModel));
  const [profiles, setProfiles] = useState(initialProfiles);
  const [modelError, setModelError] = useState("");
  const [profileError, setProfileError] = useState("");
  const [modelSaving, setModelSaving] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function handleModelSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setModelError("");
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setModelSaving(true);
    try {
      const config = JSON.parse(String(form.get("config"))) as Record<string, JsonValue>;
      const registered = await registerModelVersion({
        kind: String(form.get("kind")) as ModelKind,
        name: String(form.get("name")),
        version: Number(form.get("version")),
        config,
      });
      if (!mounted.current) return;
      setModels((current) => [...current, registered].filter(isSupportedModel));
      formElement.reset();
    } catch (error) {
      if (mounted.current) {
        setModelError(error instanceof Error ? error.message : "모델 설정을 확인해 주세요.");
      }
    } finally {
      if (mounted.current) setModelSaving(false);
    }
  }

  async function handleProfileSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProfileError("");
    const form = new FormData(event.currentTarget);
    setProfileSaving(true);
    try {
      const registered = await registerYamlProfile(
        String(form.get("kind")) as ProfileKind,
        String(form.get("content")),
      );
      if (mounted.current) setProfiles((current) => [...current, registered]);
    } catch (error) {
      if (mounted.current) {
        setProfileError(error instanceof Error ? error.message : "YAML 내용을 확인해 주세요.");
      }
    } finally {
      if (mounted.current) setProfileSaving(false);
    }
  }

  const Title = embedded ? "h2" : "h1";
  const content = (
    <>
      <header className="model-lab-header">
        <div>
          <p className="eyebrow">RAG MODEL REGISTRY</p>
          <Title className="model-lab-title">모델 레지스트리</Title>
          <p>실행 전, 변경할 수 없는 모델·프로파일 버전과 평가 상태를 관리합니다.</p>
        </div>
      </header>

      <section className="registry-group" aria-labelledby="model-registry-title">
        <h2 id="model-registry-title">모델 정의</h2>
        <div className="registry-grid">
          {(Object.keys(modelLabels) as ModelKind[]).map((kind) => (
            <RegistryTable
              key={kind}
              heading={modelLabels[kind]}
              rows={models.filter((item) => item.kind === kind).map((item) => ({
                id: item.id,
                name: item.name,
                version: item.version,
                state: "등록됨",
                details: modelDetails(item),
              }))}
            />
          ))}
        </div>
      </section>

      <section className="registry-group" aria-labelledby="profile-registry-title">
        <h2 id="profile-registry-title">파이프라인 프로파일</h2>
        <div className="registry-grid">
          {(Object.keys(profileLabels) as ProfileKind[]).map((kind) => (
            <RegistryTable
              key={kind}
              heading={profileLabels[kind]}
              rows={profiles.filter((item) => item.kind === kind).map((item) => ({
                id: item.id,
                name: item.name,
                version: item.version,
                state: item.is_default ? "기본 사용" : evaluationLabels[item.evaluation_state],
                details: item.id,
              }))}
            />
          ))}
        </div>
      </section>

      {!embedded ? <section className="version-forms" aria-label="새 버전 등록">
        <form className="version-form" onSubmit={handleModelSubmit}>
          <h2>새 모델 버전</h2>
          <fieldset disabled={modelSaving}>
            <label>종류<select name="kind" defaultValue="embedding">
              <option value="embedding">임베딩</option><option value="reranker">리랭커</option>
              <option value="llm">LLM</option>
            </select></label>
            <label>이름<input name="name" required /></label>
            <label>버전<input name="version" type="number" min="1" defaultValue="1" required /></label>
            <label>설정 JSON<textarea name="config" defaultValue="{}" required /></label>
          </fieldset>
          {modelError ? <p className="form-error" role="alert">{modelError}</p> : null}
          <button type="submit" disabled={modelSaving}>
            {modelSaving ? "등록 중…" : "모델 버전 등록"}
          </button>
        </form>
        <form className="version-form" onSubmit={handleProfileSubmit}>
          <h2>새 프로파일 버전</h2>
          <fieldset disabled={profileSaving}>
            <label>종류<select name="kind" defaultValue="retrieval">
              <option value="indexing">색인</option><option value="retrieval">검색</option>
              <option value="generation">생성</option>
            </select></label>
            <label>프로파일 YAML<textarea name="content" rows={10} defaultValue={"kind: retrieval\nname: bm25-baseline\nversion: 1\nconfig:\n  bm25: {}\nbindings: []"} required /></label>
          </fieldset>
          {profileError ? <p className="form-error" role="alert">{profileError}</p> : null}
          <button type="submit" disabled={profileSaving}>
            {profileSaving ? "등록 중…" : "YAML 프로파일 등록"}
          </button>
        </form>
      </section> : null}
    </>
  );

  return embedded ? (
    <section className="model-lab-embedded" aria-label="모델 레지스트리">
      {content}
    </section>
  ) : (
    <main className="model-lab-shell">{content}</main>
  );
}

function RegistryTable({
  heading,
  rows,
}: {
  heading: string;
  rows: { id: string; name: string; version: number; state: string; details: string }[];
}) {
  return (
    <article className="registry-panel">
      <h3>{heading}</h3>
      <table>
        <thead><tr><th>이름</th><th>버전</th><th>상태</th><th>불변 정의</th></tr></thead>
        <tbody>
          {rows.map((row) => <tr key={row.id}><td>{row.name}</td><td>v{row.version}</td><td>{row.state}</td><td>{row.details}</td></tr>)}
          {rows.length === 0 ? <tr><td colSpan={4}>등록된 버전 없음</td></tr> : null}
        </tbody>
      </table>
    </article>
  );
}

function isSupportedModel(model: ModelDefinitionSummary): boolean {
  return model.kind === "embedding" || model.kind === "reranker" || model.kind === "llm";
}

function modelDetails(model: ModelDefinitionSummary): string {
  const details = [model.id];
  for (const key of ["repo_id", "revision", "device", "data_policy"] as const) {
    const value = model.config[key];
    if (typeof value === "string") details.push(`${key}=${value}`);
  }
  return details.join(" · ");
}
