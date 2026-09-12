import { useState, type FormEvent } from "react";
import { codexError, registerModelVersion, type ModelDefinitionSummary } from "./api";

export function LlmModelForm({ onSaved }: { onSaved: (model: ModelDefinitionSummary) => void }) {
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (saving) return;
    const form = new FormData(event.currentTarget); setSaving(true); setMessage("");
    try {
      onSaved(await registerModelVersion({ kind: "llm", name: String(form.get("name")).trim(), version: Number(form.get("version")), config: { model_identifier: String(form.get("identifier")).trim() } }));
      setMessage("LLM 정의를 등록했습니다. 아래에서 이 모델의 배포를 등록하세요.");
    } catch (error) { setMessage(codexError(error)); } finally { setSaving(false); }
  }
  return <form className="version-form" onSubmit={save}><h3>LLM 모델 식별자</h3><fieldset disabled={saving}>
    <label>LLM 정의 이름<input name="name" required /></label>
    <label>LLM 정의 버전<input name="version" type="number" min={1} defaultValue={1} required /></label>
    <label>모델 식별자<input name="identifier" required /></label>
    <p>변경 시 새 정의·배포·프로파일 버전을 등록합니다. 기존 버전은 덮어쓰지 않습니다.</p>
  </fieldset><button disabled={saving}>LLM 정의 버전 등록</button>{message ? <p role="status">{message}</p> : null}</form>;
}
