import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Profile } from "./api";
import { DocumentProcessingDetails } from "./DocumentProcessingDetails";

function profile(routes: Profile["config"]): Profile {
  return {
    id: "processing-test", kind: "document_processing", name: "문서 처리", version: 2,
    config: { parser_policy: { routes }, ocr: { enabled: true } },
    bindings: [], deployment_version_id: null, legacy: false,
    readiness: { ready: false, reason_codes: [] }, evaluation_state: "draft", is_default: false,
  };
}

describe("DocumentProcessingDetails PDF routing", () => {
  it("describes mixed-page OCR only for the selected saved v2 parser route", () => {
    const selected = profile({
      "application/pdf": { name: "pymupdf-ocr", version: "2" },
    });
    selected.version = 1;
    render(<DocumentProcessingDetails models={[]} profile={selected} />);

    expect(screen.getByText("pymupdf-ocr v2")).toBeInTheDocument();
    expect(screen.getByText(/본문 텍스트 추출.*이미지 영역 OCR/)).toBeInTheDocument();
    expect(screen.getByText(/같은 위치의 중복 근거 제거/)).toBeInTheDocument();
    expect(screen.getByText(/원문 좌표 보존/)).toBeInTheDocument();
    expect(screen.queryByText(/동시 OCR은 지원하지 않음/)).not.toBeInTheDocument();
  });

  it.each([undefined, "99"])("does not assume OCR capabilities for parser version %s", (version) => {
    render(<DocumentProcessingDetails models={[]} profile={profile({
      "application/pdf": { name: "pymupdf-ocr", version },
    })} />);

    expect(screen.getByText(/PDF OCR 범위 확인 필요/)).toBeInTheDocument();
    expect(screen.queryByText(/텍스트가 없는 페이지만 OCR/)).not.toBeInTheDocument();
    expect(screen.queryByText(/이미지 영역 OCR/)).not.toBeInTheDocument();
  });

  it("does not claim mixed-page OCR when the selected profile disables OCR", () => {
    const selected = profile({
      "application/pdf": { name: "pymupdf-ocr", version: "2" },
    });
    selected.config.ocr = { enabled: false };
    render(<DocumentProcessingDetails models={[]} profile={selected} />);

    expect(screen.getByText("스캔 PDF OCR 미설정")).toBeInTheDocument();
    expect(screen.queryByText(/이미지 영역 OCR/)).not.toBeInTheDocument();
  });

  it("shows saved PDF parser and raster limits rather than assumed defaults", () => {
    render(<DocumentProcessingDetails models={[]} profile={profile({
      "application/pdf": { name: "pymupdf-ocr", version: "1", options: {
        raster_dpi: 192, max_page_pixels: 12000000, max_pages: 75,
      } },
    })} />);

    expect(screen.getByText("pymupdf-ocr v1")).toBeInTheDocument();
    expect(screen.getByText("192 DPI")).toBeInTheDocument();
    expect(screen.getByText("12000000 픽셀")).toBeInTheDocument();
    expect(screen.getByText("75 페이지")).toBeInTheDocument();
    expect(screen.getByText(/텍스트가 없는 페이지만 OCR/)).toBeInTheDocument();
    expect(screen.getByText(/같은 페이지의 텍스트와 이미지 동시 OCR은 지원하지 않음/)).toBeInTheDocument();
  });

  it("does not claim scanned PDF support for DOCX OCR or text-only PDF routes", () => {
    const { rerender } = render(<DocumentProcessingDetails models={[]} profile={profile({
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
        name: "python-docx", version: "1",
      },
    })} />);
    expect(screen.getByText("PDF 파서 미설정")).toBeInTheDocument();
    expect(screen.queryByText(/텍스트가 없는 페이지만 OCR/)).not.toBeInTheDocument();

    rerender(<DocumentProcessingDetails models={[]} profile={profile({
      "application/pdf": { name: "pymupdf", version: "1" },
    })} />);
    expect(screen.getByText("pymupdf v1")).toBeInTheDocument();
    expect(screen.getByText("스캔 PDF OCR 미설정")).toBeInTheDocument();
  });

  it("does not invent raster limits when saved options are missing", () => {
    render(<DocumentProcessingDetails models={[]} profile={profile({
      "application/pdf": { name: "pymupdf-ocr", version: "1" },
    })} />);
    expect(screen.getAllByText("미지정")).toHaveLength(4);
  });
});
