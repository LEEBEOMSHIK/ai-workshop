"""Build fictional Korean PDF fixtures; requires existing PyMuPDF, no network."""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

INK = (0.12, 0.18, 0.25)
TEAL = (0.02, 0.39, 0.43)
PALE = (0.92, 0.96, 0.96)
GREY = (0.40, 0.45, 0.49)
PAGE_SIZE = (595, 842)


class FixtureBuilder:
    def __init__(self, font_path: Path) -> None:
        self.font_path = font_path
        self.font = pymupdf.Font(fontfile=str(font_path))

    def text(
        self,
        page: pymupdf.Page,
        text: str,
        x: float,
        y: float,
        size: float = 11,
        color: tuple[float, float, float] = INK,
    ) -> None:
        page.insert_text((x, y), text, fontname="Korean", fontsize=size, color=color)

    def paragraph(self, page: pymupdf.Page, text: str, y: float) -> float:
        line = ""
        for character in text:
            if self.font.text_length(line + character, fontsize=11) > 490:
                self.text(page, line, 52, y)
                line = ""
                y += 19
            line += character
        if line:
            self.text(page, line, 52, y)
        return y + 30

    def page(
        self, document: pymupdf.Document, number: int, title: str, subtitle: str
    ) -> pymupdf.Page:
        page = document.new_page(width=PAGE_SIZE[0], height=PAGE_SIZE[1])
        page.insert_font(fontname="Korean", fontfile=str(self.font_path))
        page.draw_rect(pymupdf.Rect(0, 0, 595, 10), color=TEAL, fill=TEAL)
        self.text(page, "AI WORKSHOP  /  RAG VALIDATION", 52, 49, 10, TEAL)
        self.text(page, title, 52, 96, 23)
        self.text(page, subtitle, 52, 122, 10, GREY)
        page.draw_line((52, 143), (543, 143), color=TEAL, width=1)
        page.draw_line((52, 770), (543, 770), color=PALE, width=1)
        self.text(
            page, "가상 자산운용 검증 자료 | 실제 상품·고객·투자 권유와 무관", 52, 791, 9, GREY
        )
        self.text(page, str(number), 528, 791, 9, GREY)
        return page

    def overview(self, document: pymupdf.Document) -> None:
        page = self.page(
            document,
            1,
            "자산운용 업무 참고 자료",
            "문서 ID AM-LAB-PDF-001 | 기준일 2026-09-13 | 버전 1.0",
        )
        y = 182
        for title, body in [
            (
                "자료의 성격",
                "이 문서는 검색·인용·후속 질문·OCR 검증을 위한 합성 자료입니다. "
                "새봄 AI 연구운용은 가상의 조직이며, 모든 상품명·수치·절차는 "
                "이 테스트만을 위해 만든 예시입니다.",
            ),
            (
                "업무 범위",
                "가상 공모펀드의 상품 정보 조회, 환매 일정 안내, 위험 한도 확인과 "
                "운용 보고 절차를 다룹니다. 실제 회사의 운영 규정이나 법적 기준을 "
                "설명하는 자료가 아닙니다.",
            ),
            (
                "환매 일정의 해석",
                "D는 환매 신청이 접수된 영업일입니다. D+4는 신청일 이후 네 번째 영업일을 뜻합니다. "
                "이 문서에는 공휴일 달력이 없으므로 구체적인 달력 날짜를 계산할 수 없습니다.",
            ),
            (
                "보고 절차",
                "운용지원팀은 매 영업일 17:00에 일별 위험 점검 보고서를 작성합니다. "
                "한도 초과가 확인되면 당일 18:00까지 위험관리 담당자에게 알립니다.",
            ),
            (
                "기재하지 않은 정보",
                "과거 수익률, 미래 수익률 전망, 고객 개인정보, 계좌번호, 실제 운용사 연락처와 "
                "법률상 의무는 기재하지 않았습니다. 이 정보를 질문받으면 "
                "문서에서 확인할 수 없다고 답해야 합니다.",
            ),
        ]:
            self.text(page, title, 52, y, 14, TEAL)
            y = self.paragraph(page, body, y + 28) + 13

    def products(self, document: pymupdf.Document) -> None:
        page = self.page(
            document, 2, "상품별 조건 비교", "가상 상품 2종 | 표의 열과 단위를 함께 확인"
        )
        rows = [
            ["항목", "AM-LAB-730", "AM-LAB-840"],
            ["상품명", "오로라 연구 채권형", "해오름 연구 혼합형"],
            ["환매 대금 지급", "D+4 영업일", "D+7 영업일"],
            ["연간 총보수", "0.37%", "0.82%"],
            ["위험등급", "6등급 중 4등급", "6등급 중 2등급"],
            ["단일 발행사 한도", "순자산의 10%", "순자산의 8%"],
            ["월간 보고 기준일", "매월 마지막 영업일", "매월 마지막 영업일"],
        ]
        xs = [52, 205, 374, 543]
        for index, row in enumerate(rows):
            y = 174 + index * 49
            for column, value in enumerate(row):
                rect = pymupdf.Rect(xs[column], y, xs[column + 1], y + 49)
                page.draw_rect(
                    rect,
                    color=(0.77, 0.84, 0.84),
                    fill=PALE if index % 2 == 0 else (1, 1, 1),
                    width=0.6,
                )
                self.text(page, value, xs[column] + 10, y + 29, 10)
        y = self.paragraph(
            page,
            "표 해석: 총보수의 단위는 연간 %이며, "
            "단일 발행사 한도는 해당 상품 순자산 대비 비율입니다. "
            "두 비율은 의미가 다르므로 혼동하지 않습니다.",
            565,
        )
        self.paragraph(
            page,
            "유의: 이 표는 가상 상품의 검증용 조건입니다. "
            "다른 문서나 실제 금융상품의 조건으로 일반화하지 않습니다.",
            y + 12,
        )

    def workflow(self, document: pymupdf.Document, *, raster: bool) -> None:
        page = self.page(
            document,
            3,
            "위험 점검과 예외 처리",
            "이미지 포함 버전에서는 아래 업무 카드가 래스터 이미지입니다."
            if raster
            else "텍스트 기반 업무 흐름 | 카드 순서와 예외 조건",
        )
        self.paragraph(
            page,
            "아래 카드의 시각과 담당자를 확인합니다. 한도 초과는 환매 지급 일정과 다른 업무이며, "
            "두 절차를 섞어 답하지 않습니다.",
            180,
        )
        canvas = pymupdf.open()
        card = canvas.new_page(width=491, height=310)
        card.insert_font(fontname="Korean", fontfile=str(self.font_path))
        steps = [
            ("01  운용지원팀", "17:00 일별 위험 점검 보고서 작성"),
            ("02  위험관리 담당자", "18:00까지 한도 초과 알림 접수"),
            ("03  조치 기록", "다음 영업일 10:00까지 원인과 조치 기록"),
        ]
        for index, (title, detail) in enumerate(steps):
            top = index * 103
            card.draw_rect(pymupdf.Rect(1, top + 1, 490, top + 86), color=TEAL, fill=PALE)
            self.text(card, title, 20, top + 30, 13, TEAL)
            self.text(card, detail, 20, top + 60, 12)
        rect = pymupdf.Rect(52, 250, 543, 560)
        if raster:
            page.insert_image(
                rect, stream=card.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
            )
        else:
            page.show_pdf_page(rect, canvas, 0)
        canvas.close()
        self.paragraph(
            page,
            "예외 처리: 자료가 누락됐다고 위험 수치를 0으로 입력하지 않습니다. "
            "'자료 미수신'으로 기록하고 담당자에게 확인을 요청합니다.",
            616,
        )

    def scanned_appendix(self, document: pymupdf.Document) -> None:
        source = pymupdf.open()
        page = self.page(
            source,
            4,
            "스캔 부록 - 내부 검증 메모",
            "이 페이지 전체는 이미지입니다. 검색에는 OCR이 필요합니다.",
        )
        y = 195
        for text in [
            "검증 메모 ID: SCAN-AM-219",
            "가상 결재 담당자는 리서치운영팀입니다.",
            "월간 운용보고서 초안 제출 시각은 다음 달 세 번째 영업일 15:30입니다.",
            "오류 정정 내역에는 원인, 수정 전 값, 수정 후 값과 확인자를 기록합니다.",
            "이 메모는 상품 환매 지급일이나 연간 총보수를 변경하지 않습니다.",
        ]:
            y = self.paragraph(page, text, y) + 25
        target = document.new_page(width=PAGE_SIZE[0], height=PAGE_SIZE[1])
        target.insert_image(
            target.rect, stream=page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
        )
        source.close()

    def build(self, destination: Path, *, mixed: bool) -> None:
        with pymupdf.open() as document:
            self.overview(document)
            self.products(document)
            self.workflow(document, raster=mixed)
            if mixed:
                self.scanned_appendix(document)
            document.set_metadata(
                {
                    "title": "AI Workshop 가상 자산운용 검증 자료",
                    "author": "AI Workshop",
                    "subject": "Synthetic RAG test fixture; not investment advice",
                }
            )
            document.subset_fonts()
            document.save(destination, garbage=4, deflate=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True, help="Korean TrueType font path")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    builder = FixtureBuilder(args.font)
    builder.build(args.output / "asset-management-text-v1.pdf", mixed=False)
    builder.build(args.output / "asset-management-ocr-v1.pdf", mixed=True)


if __name__ == "__main__":
    main()
