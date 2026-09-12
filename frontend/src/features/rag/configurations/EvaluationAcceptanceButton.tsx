import { useEffect, useRef, useState } from "react";
import { acceptConfigurationEvaluation, loadConfigurations, type SavedConfiguration } from "./api";

export function EvaluationAcceptanceButton({ configuration, runId, disabled, onUpdated }: {
  configuration: SavedConfiguration; runId: string; disabled: boolean;
  onUpdated: (configuration: SavedConfiguration) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  async function accept() {
    if (disabled || request.current) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setMessage(""); setError("");
    try {
      const response = await acceptConfigurationEvaluation(configuration.id, configuration.version_id, runId, controller.signal);
      if (controller.signal.aborted) return;
      onUpdated(response.configuration);
      let refreshFailed = false;
      try {
        const refreshed = await loadConfigurations(controller.signal);
        if (!controller.signal.aborted) refreshed.forEach(onUpdated);
      } catch { refreshFailed = true; }
      if (!controller.signal.aborted) setMessage("검색 평가 통과를 반영했습니다. 전체 기본값은 변경하지 않았습니다. 서비스 사용 준비는 별도 확인하세요." + (refreshFailed ? " 준비 정보 새로고침에 실패했습니다. 평가 통과는 유지되며 준비 정보는 다시 조회해 주세요." : ""));
    } catch {
      if (!controller.signal.aborted) setError("평가 통과를 반영하지 못했습니다. 정확한 버전·실행·정책과 서버 통과 조건을 확인해 주세요.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }
  return <><button type="button" disabled={disabled || busy} onClick={() => void accept()}>{busy ? "평가 통과 반영 중…" : "이 버전의 평가 통과 반영"}</button>
    {message ? <p role="status">{message}</p> : null}{error ? <p role="alert">{error}</p> : null}</>;
}
