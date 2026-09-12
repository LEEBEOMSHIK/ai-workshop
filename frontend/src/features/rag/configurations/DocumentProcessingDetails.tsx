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
  const routes = objectValue(objectValue(profile.config.parser_policy)?.routes);
  const pdf = objectValue(routes?.["application/pdf"]);
  const pdfOptions = objectValue(pdf?.options);
  const scannedPdf = enabled && pdf?.name === "pymupdf-ocr";
  const roles = [
    ["레이아웃 감지", "ocr_layout_detection"],
    ["텍스트 감지", "ocr_text_detection"],
    ["텍스트 인식", "ocr_text_recognition"],
    ["표 내부 텍스트 줄 방향", "ocr_textline_orientation"],
    ["표 분류", "ocr_table_classification"],
    ["유선 표 구조", "ocr_table_structure_wired"],
    ["무선 표 구조", "ocr_table_structure"],
    ["유선 표 셀 감지", "ocr_table_cells_wired"],
    ["무선 표 셀 감지", "ocr_table_cells_wireless"],
    ["표 방향 분류", "ocr_table_orientation"],
  ] as const;
  return (
    <details className="component-details">
      <summary>전체 OCR 구성 보기</summary>
      <dl>
        <Detail label="프로파일" value={`${profile.name} v${profile.version}`} />
        <Detail label="평가 상태" value={profile.evaluation_state} />
        <Detail label="OCR" value={enabled ? "사용" : "사용 안 함"} />
        <Detail label="PDF 파서" value={pdf
          ? `${stringValue(pdf.name) || "이름 미지정"} v${stringValue(pdf.version) || "버전 미지정"}`
          : "PDF 파서 미설정"} />
        <Detail label="PDF OCR 범위" value={pdfOcrScope(scannedPdf, pdf?.version)} />
        {scannedPdf ? (
          <>
            <Detail label="PDF 렌더 해상도" value={numericSetting(pdfOptions?.raster_dpi, "DPI")} />
            <Detail label="PDF 페이지당 최대 픽셀" value={numericSetting(pdfOptions?.max_page_pixels, "픽셀")} />
            <Detail label="PDF 최대 페이지 수" value={numericSetting(pdfOptions?.max_pages, "페이지")} />
          </>
        ) : null}
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

function pdfOcrScope(enabled: boolean, version: unknown): string {
  if (!enabled) return "스캔 PDF OCR 미설정";
  if (version === "1") {
    return "텍스트가 없는 페이지만 OCR · 같은 페이지의 텍스트와 이미지 동시 OCR은 지원하지 않음";
  }
  if (version === "2") {
    return "본문 텍스트 추출 + 이미지 영역 OCR · 텍스트가 없는 페이지는 전체 OCR · 같은 위치의 중복 근거 제거 · 원문 좌표 보존";
  }
  return "PDF OCR 범위 확인 필요 · 저장된 파서 버전의 처리 범위를 확인할 수 없음";
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numericSetting(value: unknown, unit: string): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value} ${unit}`
    : "미지정";
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
