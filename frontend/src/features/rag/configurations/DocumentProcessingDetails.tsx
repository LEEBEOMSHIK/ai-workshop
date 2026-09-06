import type { ModelDefinition, Profile } from "./api";

export function DocumentProcessingDetails({
  profile,
  models,
}: {
  profile: Profile | undefined;
  models: ModelDefinition[];
}) {
  if (!profile) return null;
  const ocr = objectValue(profile.config.ocr);
  const enabled = ocr?.enabled === true;
  const roles = [
    ["텍스트 감지", "ocr_text_detection"],
    ["텍스트 인식", "ocr_text_recognition"],
    ["표 구조", "ocr_table_structure"],
  ] as const;
  return (
    <details className="component-details">
      <summary>전체 OCR 구성 보기</summary>
      <dl>
        <Detail label="프로파일" value={`${profile.name} v${profile.version}`} />
        <Detail label="평가 상태" value={profile.evaluation_state} />
        <Detail label="OCR" value={enabled ? "사용" : "사용 안 함"} />
        {enabled ? (
          <>
            <Detail label="파이프라인" value={`${stringValue(ocr?.pipeline_name)} ${stringValue(ocr?.pipeline_version)}`} />
            <Detail label="언어" value={arrayValue(ocr?.languages).join(", ")} />
            <Detail label="최소 신뢰도" value={String(ocr?.confidence_threshold ?? "미지정")} />
            <Detail label="실행 위치" value={ocr?.data_policy === "local_only" ? "로컬·온프레미스 전용" : "정책 확인 필요"} />
            {roles.map(([label, role]) => {
              const binding = profile.bindings.find((item) => item.role === role);
              const model = models.find((item) => item.id === binding?.model_id && item.kind === role);
              return <Detail key={role} label={label} value={modelSummary(model)} />;
            })}
          </>
        ) : null}
      </dl>
    </details>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value || "정보 없음"}</dd></div>;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function arrayValue(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function modelSummary(model: ModelDefinition | undefined): string {
  if (!model) return "연결된 모델 정보 없음";
  const source = stringValue(model.config.source);
  const revision = stringValue(model.config.revision);
  const license = stringValue(model.config.license);
  const digest = stringValue(model.config.artifact_sha256);
  const verified = digest.length === 64 ? "SHA-256 등록" : "아티팩트 확인 필요";
  return `${model.name} v${model.version} · ${source || "로컬 아티팩트"} · ${revision || "리비전 미지정"} · ${license || "라이선스 미지정"} · ${verified}`;
}
