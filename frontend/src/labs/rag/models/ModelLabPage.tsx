import { type FormEvent, useState } from "react";
import { useLoaderData } from "react-router-dom";

import {
  type JsonValue,
  type ModelDefinitionSummary,
  type ModelKind,
  type ModelLabData,
  type ProfileKind,
  type ProfileSummary,
  registerModelVersion,
  registerYamlProfile,
} from "./api";

interface ModelLabPageProps {
  initialModels?: ModelDefinitionSummary[];
  initialProfiles?: ProfileSummary[];
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
}: ModelLabPageProps) {
  const [models, setModels] = useState(initialModels);
  const [profiles, setProfiles] = useState(initialProfiles);
  const [modelError, setModelError] = useState("");
  const [profileError, setProfileError] = useState("");

  async function handleModelSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setModelError("");
    const form = new FormData(event.currentTarget);
    try {
      const config = JSON.parse(String(form.get("config"))) as Record<string, JsonValue>;
      const registered = await registerModelVersion({
        kind: String(form.get("kind")) as ModelKind,
        name: String(form.get("name")),
        version: Number(form.get("version")),
        config,
      });
      setModels((current) => [...current, registered]);
      event.currentTarget.reset();
    } catch (error) {
      setModelError(error instanceof Error ? error.message : "모델 설정을 확인해 주세요.");
    }
  }

  async function handleProfileSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProfileError("");
    const form = new FormData(event.currentTarget);
    try {
      const registered = await registerYamlProfile(
        String(form.get("kind")) as ProfileKind,
        String(form.get("content")),
      );
      setProfiles((current) => [...current, registered]);
    } catch (error) {
      setProfileError(error instanceof Error ? error.message : "YAML 내용을 확인해 주세요.");
    }
  }

  return (
    <main className="model-lab-shell">
      <header className="model-lab-header">
        <div>
          <p className="eyebrow">RAG MODEL REGISTRY</p>
          <h1 className="model-lab-title">모델 실험실</h1>
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
              }))}
            />
          ))}
        </div>
      </section>

      <section className="version-forms" aria-label="새 버전 등록">
        <form className="version-form" onSubmit={handleModelSubmit}>
          <h2>새 모델 버전</h2>
          <label>종류<select name="kind" defaultValue="embedding">
            <option value="embedding">임베딩</option><option value="reranker">리랭커</option>
            <option value="llm">LLM</option>
          </select></label>
          <label>이름<input name="name" required /></label>
          <label>버전<input name="version" type="number" min="1" defaultValue="1" required /></label>
          <label>설정 JSON<textarea name="config" defaultValue="{}" required /></label>
          {modelError ? <p className="form-error">{modelError}</p> : null}
          <button type="submit">모델 버전 등록</button>
        </form>
        <form className="version-form" onSubmit={handleProfileSubmit}>
          <h2>새 프로파일 버전</h2>
          <label>종류<select name="kind" defaultValue="retrieval">
            <option value="indexing">색인</option><option value="retrieval">검색</option>
            <option value="generation">생성</option>
          </select></label>
          <label>프로파일 YAML<textarea name="content" rows={10} defaultValue={"kind: retrieval\nname: bm25-baseline\nversion: 1\nconfig:\n  bm25: {}\nbindings: []"} required /></label>
          {profileError ? <p className="form-error">{profileError}</p> : null}
          <button type="submit">YAML 프로파일 등록</button>
        </form>
      </section>
    </main>
  );
}

function RegistryTable({
  heading,
  rows,
}: {
  heading: string;
  rows: { id: string; name: string; version: number; state: string }[];
}) {
  return (
    <article className="registry-panel">
      <h3>{heading}</h3>
      <table>
        <thead><tr><th>이름</th><th>버전</th><th>상태</th></tr></thead>
        <tbody>
          {rows.map((row) => <tr key={row.id}><td>{row.name}</td><td>v{row.version}</td><td>{row.state}</td></tr>)}
          {rows.length === 0 ? <tr><td colSpan={3}>등록된 버전 없음</td></tr> : null}
        </tbody>
      </table>
    </article>
  );
}

export function ModelLabRoute() {
  const data = useLoaderData() as ModelLabData;
  return <ModelLabPage initialModels={data.models} initialProfiles={data.profiles} />;
}
