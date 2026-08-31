import { type CSSProperties, type ReactNode, useEffect, useMemo, useState } from "react";
import { useLocation, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../../../shared/api/client";
import {
  type HighlightSpan,
  type NormalizedTextData,
  loadNormalizedText,
  loadPdfPage,
} from "./api";

interface SourceViewerProps {
  assetVersionId: string;
  projectionId: string;
  highlights: HighlightSpan[];
  page?: number | null;
}

const highlightLabels: Record<HighlightSpan["kind"], string> = {
  keyword: "정확·키워드 일치",
  semantic: "의미 일치",
};

export function SourceViewer({
  assetVersionId,
  projectionId,
  highlights,
  page,
}: SourceViewerProps) {
  const [attempt, setAttempt] = useState(0);
  const requestedPage = page ?? highlights.find((highlight) => highlight.page !== null)?.page;
  const requestKey = `${assetVersionId}:${projectionId}:${requestedPage ?? "auto"}:${attempt}`;
  const [viewerState, setViewerState] = useState<{
    key: string;
    document: NormalizedTextData;
    pdfUrl: string | null;
  } | null>(null);
  const [failure, setFailure] = useState<{ key: string; error: ApiError } | null>(null);
  const [pageDimensions, setPageDimensions] = useState<{
    key: string;
    width: number;
    height: number;
  } | null>(null);
  const document = viewerState?.key === requestKey ? viewerState.document : null;
  const pdfUrl = viewerState?.key === requestKey ? viewerState.pdfUrl : null;
  const error = failure?.key === requestKey ? failure.error : null;
  const loading = document === null && error === null;
  const dimensions =
    pageDimensions?.key === requestKey
      ? { width: pageDimensions.width, height: pageDimensions.height }
      : { width: 0, height: 0 };

  const pageNumber =
    requestedPage ??
    document?.elements.find((element) => element.location.page !== null)?.location.page ??
    1;

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;

    void (async () => {
      try {
        const loadedDocument = await loadNormalizedText(assetVersionId, projectionId);
        if (!active) return;
        let loadedPdfUrl: string | null = null;
        if (loadedDocument.media_type === "application/pdf") {
          const pdfPage =
            requestedPage ??
            loadedDocument.elements.find((element) => element.location.page !== null)?.location.page ??
            1;
          const blob = await loadPdfPage(assetVersionId, projectionId, pdfPage);
          if (!active) return;
          objectUrl = URL.createObjectURL(blob);
          loadedPdfUrl = objectUrl;
        }
        setViewerState({ key: requestKey, document: loadedDocument, pdfUrl: loadedPdfUrl });
      } catch (caught) {
        if (!active) return;
        setFailure({
          key: requestKey,
          error:
            caught instanceof ApiError
              ? caught
              : new ApiError("원문을 불러오지 못했습니다.", 500, "viewer_failed"),
        });
      }
    })();

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [assetVersionId, projectionId, requestKey, requestedPage]);

  const validatedTextHighlights = useMemo(
    () => validateTextHighlights(document, highlights),
    [document, highlights],
  );

  if (loading) {
    return <main className="source-viewer-shell"><p role="status">원문을 불러오는 중…</p></main>;
  }
  if (error) {
    const retryable = error.status === 503;
    return (
      <main className="source-viewer-shell">
        <p role="alert">{viewerErrorMessage(error)}</p>
        {retryable ? <button type="button" onClick={() => setAttempt((value) => value + 1)}>다시 시도</button> : null}
      </main>
    );
  }
  if (!document) return null;

  return (
    <main className="source-viewer-shell">
      <header className="source-viewer-header">
        <p className="eyebrow">AUTHORIZED SOURCE</p>
        <h1 className="source-viewer-title">{document.title}</h1>
        <p>변경할 수 없는 버전 {document.asset_version_number}</p>
      </header>

      <div className="highlight-legend" aria-label="하이라이트 범례">
        <span className="match-badge keyword">정확·키워드 일치</span>
        <span className="match-badge semantic">의미 일치</span>
      </div>

      {document.media_type === "application/pdf" ? (
        <PdfPage
          title={document.title}
          page={pageNumber}
          imageUrl={pdfUrl}
          highlights={highlights}
          dimensions={dimensions}
          onImageLoad={(width, height) => setPageDimensions({ key: requestKey, width, height })}
        />
      ) : (
        <section className="normalized-document" aria-label="정규화된 원문">
          {document.elements.map((element) => (
            <article className="normalized-element" key={element.id}>
              {element.section_path.length > 0 ? (
                <p className="source-location">{element.section_path.join(" › ")}</p>
              ) : null}
              <p>{highlightElement(element, validatedTextHighlights.highlights)}</p>
            </article>
          ))}
          {validatedTextHighlights.invalid ? (
            <p className="provenance-warning">유효하지 않은 하이라이트 범위를 제외했습니다.</p>
          ) : null}
        </section>
      )}
    </main>
  );
}

function PdfPage({
  title,
  page,
  imageUrl,
  highlights,
  dimensions,
  onImageLoad,
}: {
  title: string;
  page: number;
  imageUrl: string | null;
  highlights: HighlightSpan[];
  dimensions: { width: number; height: number };
  onImageLoad: (width: number, height: number) => void;
}) {
  const pageHighlights = highlights.filter((highlight) => highlight.page === page);
  const overlays = pageHighlights.flatMap((highlight) => {
    const style = overlayStyle(highlight.bbox, dimensions);
    return style ? [{ highlight, style }] : [];
  });
  const dimensionsReady = dimensions.width > 0 && dimensions.height > 0;
  const unavailableKinds = Array.from(
    new Set(
      pageHighlights
        .filter(
          (highlight) =>
            highlight.bbox === null ||
            (dimensionsReady && overlayStyle(highlight.bbox, dimensions) === null),
        )
        .map((highlight) => highlight.kind),
    ),
  );

  return (
    <section className="pdf-viewer" aria-label={`${page}페이지 원문`}>
      {imageUrl ? (
        <div className="pdf-page">
          <img
            src={imageUrl}
            alt={`${title} ${page}페이지`}
            onLoad={(event) =>
              onImageLoad(event.currentTarget.naturalWidth, event.currentTarget.naturalHeight)
            }
          />
          <div className="pdf-overlay-layer" aria-hidden={overlays.length === 0}>
            {overlays.map(({ highlight, style }) => (
              <span
                key={`${highlight.evidence_unit_id}-${highlight.kind}-${highlight.char_start}`}
                className={`pdf-highlight ${highlight.kind}-highlight`}
                aria-label={`${highlightLabels[highlight.kind]} 강조 영역`}
                style={style}
              />
            ))}
          </div>
        </div>
      ) : null}
      {unavailableKinds.map((kind) => (
        <p className="provenance-warning" key={kind}>
          {highlightLabels[kind]} 원문 좌표를 사용할 수 없습니다.
        </p>
      ))}
    </section>
  );
}

function validateTextHighlights(
  document: NormalizedTextData | null,
  highlights: HighlightSpan[],
): { highlights: HighlightSpan[]; invalid: boolean } {
  if (!document) return { highlights: [], invalid: false };
  const sorted = [...highlights].sort(
    (left, right) => left.char_start - right.char_start || left.char_end - right.char_end,
  );
  const accepted: HighlightSpan[] = [];
  let invalid = false;
  let previousEnd = -1;
  for (const highlight of sorted) {
    const element = document.elements.find(
      (candidate) =>
        highlight.char_start >= candidate.location.char_start &&
        highlight.char_end <= candidate.location.char_end,
    );
    const localStart = element ? highlight.char_start - element.location.char_start : -1;
    const localEnd = element ? highlight.char_end - element.location.char_start : -1;
    const codePointLength = element ? Array.from(element.text).length : -1;
    const utf16Start = element ? codePointIndexToUtf16Offset(element.text, localStart) : null;
    const utf16End = element ? codePointIndexToUtf16Offset(element.text, localEnd) : null;
    const valid =
      Number.isInteger(highlight.char_start) &&
      Number.isInteger(highlight.char_end) &&
      highlight.char_start >= 0 &&
      highlight.char_end > highlight.char_start &&
      highlight.char_start >= previousEnd &&
      element !== undefined &&
      localEnd <= codePointLength &&
      utf16Start !== null &&
      utf16End !== null &&
      element.text.slice(utf16Start, utf16End) === highlight.text;
    if (!valid) {
      invalid = true;
      continue;
    }
    accepted.push(highlight);
    previousEnd = highlight.char_end;
  }
  return { highlights: accepted, invalid };
}

function highlightElement(
  element: NormalizedTextData["elements"][number],
  highlights: HighlightSpan[],
): ReactNode[] {
  const relevant = highlights.filter(
    (highlight) =>
      highlight.char_start >= element.location.char_start &&
      highlight.char_end <= element.location.char_end,
  );
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const highlight of relevant) {
    const codePointStart = highlight.char_start - element.location.char_start;
    const codePointEnd = highlight.char_end - element.location.char_start;
    const start = codePointIndexToUtf16Offset(element.text, codePointStart);
    const end = codePointIndexToUtf16Offset(element.text, codePointEnd);
    if (start === null || end === null) continue;
    if (start > cursor) parts.push(element.text.slice(cursor, start));
    parts.push(
      <mark
        className={`${highlight.kind}-highlight`}
        aria-label={highlightLabels[highlight.kind]}
        key={`${highlight.evidence_unit_id}-${highlight.kind}-${highlight.char_start}`}
      >
        {element.text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  }
  if (cursor < element.text.length) parts.push(element.text.slice(cursor));
  return parts;
}

function codePointIndexToUtf16Offset(text: string, codePointIndex: number): number | null {
  const codePoints = Array.from(text);
  if (!Number.isInteger(codePointIndex) || codePointIndex < 0 || codePointIndex > codePoints.length) {
    return null;
  }
  let utf16Offset = 0;
  for (let index = 0; index < codePointIndex; index += 1) {
    utf16Offset += codePoints[index].length;
  }
  return utf16Offset;
}

function overlayStyle(
  bbox: HighlightSpan["bbox"],
  dimensions: { width: number; height: number },
): CSSProperties | null {
  if (!bbox || dimensions.width <= 0 || dimensions.height <= 0) return null;
  const [rawLeft, rawTop, rawRight, rawBottom] = bbox;
  if (![rawLeft, rawTop, rawRight, rawBottom].every(Number.isFinite)) return null;
  const left = clamp(rawLeft, 0, dimensions.width);
  const top = clamp(rawTop, 0, dimensions.height);
  const right = clamp(rawRight, 0, dimensions.width);
  const bottom = clamp(rawBottom, 0, dimensions.height);
  if (right <= left || bottom <= top) return null;
  return {
    left: `${(left / dimensions.width) * 100}%`,
    top: `${(top / dimensions.height) * 100}%`,
    width: `${((right - left) / dimensions.width) * 100}%`,
    height: `${((bottom - top) / dimensions.height) * 100}%`,
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function viewerErrorMessage(error: ApiError): string {
  if (error.status === 401) return "로그인이 필요합니다.";
  if (error.status === 404) return "원문을 찾을 수 없습니다.";
  if (error.status === 503) return "원문 파일을 일시적으로 불러올 수 없습니다.";
  return "원문을 불러오지 못했습니다.";
}

interface ViewerRouteState {
  highlights?: HighlightSpan[];
  page?: number | null;
}

export function SourceViewerRoute() {
  const { assetVersionId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const state = location.state as ViewerRouteState | null;
  const projectionId = searchParams.get("projectionId") ?? "";
  if (!assetVersionId || !projectionId) {
    return <main className="source-viewer-shell"><p role="alert">원문 요청 정보가 올바르지 않습니다.</p></main>;
  }
  return (
    <SourceViewer
      assetVersionId={assetVersionId}
      projectionId={projectionId}
      highlights={state?.highlights ?? []}
      page={state?.page}
    />
  );
}
