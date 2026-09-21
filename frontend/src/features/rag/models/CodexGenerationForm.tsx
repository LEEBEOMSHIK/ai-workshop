import { useState, type FormEvent } from "react";
import { codexError, registerYamlProfile, type CodexRunner, type DeploymentSummary, type ProfileSummary } from "./api";

export function CodexGenerationForm({ deployments, runners, onSaved }: {
  deployments: DeploymentSummary[]; runners: CodexRunner[]; onSaved: (value: ProfileSummary) => void;
}) {
  const choices = deployments.filter((item) => item.provider === "development_codex_exec");
  const [selected, setSelected] = useState("");
  const [optionIndex, setOptionIndex] = useState(0);
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const deployment = choices.find((item) => item.version_id === selected) ?? choices[0];
  const runner = runners.find((item) => item.runner_ref === deployment?.runner_ref);
  const prompt = runner?.prompt_options[optionIndex];
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!deployment || !runner?.local_preflight_passed || !prompt || busy) return;
    const form = new FormData(event.currentTarget); setBusy(true); setMessage("");
    try {
      const saved = await registerYamlProfile("generation", JSON.stringify({
        kind: "generation", name: String(form.get("name")).trim(), version: Number(form.get("version")),
        deployment_version_id: deployment.version_id, bindings: [],
        config: { prompt_ref: prompt.answer_ref, context_prompt_ref: prompt.context_ref, citation_mode: "required",
          ...(prompt.context_evidence ? { context_evidence: prompt.context_evidence } : {}),
          context_policy: { max_history_turns: Number(form.get("historyTurns")), max_history_tokens: Number(form.get("historyTokens")) },
          generation: { timeout_seconds: Number(form.get("timeout")), max_output_tokens: Number(form.get("output")), temperature: 0, response_schema_version: prompt.response_schema_version } },
      }));
      onSaved(saved); setMessage("생성 프로파일을 등록했습니다. 구성 스튜디오에서 저장 구성을 만드세요.");
    } catch (error) { setMessage(codexError(error)); } finally { setBusy(false); }
  }
  return <form className="version-form" onSubmit={submit}>
    <h3>Codex 생성 프로파일</h3>
    <fieldset disabled={busy}>
      <label>Codex 배포 버전<select value={deployment?.version_id ?? ""} onChange={(event) => { setSelected(event.target.value); setOptionIndex(0); }}>{choices.map((item) => <option key={item.version_id} value={item.version_id}>{item.display_name} v{item.version}</option>)}</select></label>
      <label>생성 프로파일 이름<input name="name" required /></label>
      <label>생성 프로파일 버전<input name="version" type="number" min={1} defaultValue={1} required /></label>
      <label>서버 지침 버전<select value={optionIndex} onChange={(event) => setOptionIndex(Number(event.target.value))}>{runner?.prompt_options.map((item, index) => <option key={item.answer_ref} value={index}>{item.answer_ref} / {item.context_ref} · schema {item.response_schema_version}</option>)}</select></label>
      {prompt ? <div className="control-help"><h4>읽기 전용 지침 · {prompt.control_ref}</h4><pre style={{ whiteSpace: "pre-wrap" }}>{prompt.control_text}</pre><details><summary>답변·문맥화 지침 보기</summary><pre style={{ whiteSpace: "pre-wrap" }}>{prompt.answer_text}</pre><pre style={{ whiteSpace: "pre-wrap" }}>{prompt.context_text}</pre></details></div> : null}
      <label>시간 제한 (초)<input key={`timeout-${runner?.runner_ref}`} name="timeout" type="number" min={1} max={runner?.limits.timeout_seconds} defaultValue={runner?.limits.timeout_seconds ?? 60} required /></label>
      <label>출력 수용 토큰 한도<input key={`output-${runner?.runner_ref}`} name="output" type="number" min={1} max={runner?.limits.max_output_tokens} defaultValue={runner?.limits.max_output_tokens ?? 1024} required /></label>
      <label>이력 턴 한도<input name="historyTurns" type="number" min={1} max={20} defaultValue={4} required /></label>
      <label>이력 토큰 한도<input name="historyTokens" type="number" min={1} defaultValue={1024} required /></label>
      <p>temperature는 CLI에서 관리하며 전송하지 않습니다. 출력 수용 한도는 생성량·과금 상한이 아닙니다. 등록은 연결 검증이나 평가 통과를 의미하지 않습니다.</p>
    </fieldset>
    <button disabled={busy || !prompt || !runner?.local_preflight_passed}>Codex 생성 프로파일 등록</button>
    {message ? <p role="status">{message}</p> : null}
  </form>;
}
