"""Build a wholly synthetic Korean RAG evaluation corpus.

Requires PyMuPDF and Pillow already supplied by the backend environment.
PDFs are inputs; answer-key files are evaluation-only and MUST NOT be ingested.

Repository-root command (defaults use Windows Malgun fonts):
    backend/.venv/Scripts/python.exe scripts/build_asset_management_corpus.py
Portable invocation with installed Korean TrueType fonts:
    python scripts/build_asset_management_corpus.py --font /fonts/regular.ttf \
        --bold-font /fonts/bold.ttf --output output/pdf --qa-dir tmp/pdf-qa
Content is reproducible; PDF trailer identifiers and hashes may change on rebuild.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import pymupdf as fitz
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
NAVY = (0.08, 0.16, 0.25)
TEAL = (0.0, 0.43, 0.44)
GRAY = (0.36, 0.41, 0.46)
LIGHT = (0.94, 0.96, 0.97)


@dataclass(frozen=True)
class BuildOptions:
    font: Path
    bold_font: Path
    output: Path
    qa_dir: Path


class Evidence(TypedDict):
    file: str
    page: int
    quote: str


class Question(TypedDict):
    id: str
    category: str
    question: str
    expected_answer: str
    expected_behavior: str
    evidence: list[Evidence]


class Publication:
    def __init__(self, options: BuildOptions, filename: str, title: str, subtitle: str) -> None:
        self.options = options
        self.filename, self.title, self.subtitle = filename, title, subtitle
        self.doc = fitz.open()
        self.y = 0.0

    def text(self, text: str, x: float, y: float, width: float, size: float = 10.5,
             bold: bool = False, color: tuple[float, float, float] = NAVY) -> float:
        font = fitz.Font(fontfile=str(self.options.bold_font if bold else self.options.font))
        lines: list[str] = []
        for paragraph in text.split("\n"):
            line = ""
            for char in paragraph:
                if font.text_length(line + char, fontsize=size) > width:
                    lines.append(line.rstrip())
                    line = char.lstrip()
                else:
                    line += char
            lines.append(line)
        lineheight = size * 1.65
        for index, line in enumerate(lines):
            baseline = y + size + index * lineheight
            if baseline > (825 if y >= 790 else 775):
                raise ValueError(f"Content overflow: {self.filename}: {text[:30]}")
            self.page.insert_text((x, baseline), line, fontsize=size,
                                  fontname="bold" if bold else "regular", color=color)
        return len(lines) * lineheight

    def page_start(self, heading: str, description: str) -> None:
        self.page = self.doc.new_page(width=595, height=842)
        self.page.insert_font(fontname="regular", fontfile=str(self.options.font))
        self.page.insert_font(fontname="bold", fontfile=str(self.options.bold_font))
        self.page.draw_rect(fitz.Rect(0, 0, 595, 11), color=None, fill=TEAL)
        self.text("가상새결자산운용  /  SYNTHETIC RESEARCH SERIES", 42, 28, 510, 9, True, TEAL)
        self.text(self.title, 42, 60, 510, 23, True)
        self.text(self.subtitle, 42, 104, 510, 9, False, GRAY)
        self.page.draw_line((42, 133), (553, 133), color=(0.80, 0.85, 0.88))
        self.text(heading, 42, 155, 510, 17, True)
        self.y = 195 + self.text(description, 42, 195, 510, 10.5, False, GRAY) + 18

    def section(self, heading: str, body: str) -> None:
        self.y += self.text(heading, 42, self.y, 510, 12, True, TEAL) + 8
        self.y += self.text(body, 42, self.y, 510) + 20

    def table(self, columns: list[str], rows: list[list[str]], widths: list[int]) -> None:
        font = fitz.Font(fontfile=str(self.options.font))
        for row_number, row in enumerate([columns] + rows):
            heights = [max(1, int(font.text_length(cell, fontsize=9.5) / (width - 18)) + 1)
                       * 16 + 16 for cell, width in zip(row, widths)]
            height = max(heights)
            if self.y + height > 755:
                raise ValueError("Table overflow")
            x = 42
            for cell, width in zip(row, widths):
                self.page.draw_rect(fitz.Rect(x, self.y, x + width, self.y + height),
                                    color=(0.82, 0.86, 0.89), width=0.5,
                                    fill=LIGHT if row_number == 0 else (1, 1, 1))
                self.text(cell, x + 9, self.y + 8, width - 18, 9.5, row_number == 0)
                x += width
            self.y += height
        self.y += 20

    def finish(self) -> Path:
        for number, page in enumerate(self.doc, 1):
            self.page = page
            page.draw_line((42, 790), (553, 790), color=(0.80, 0.85, 0.88))
            self.text("전면 합성 자료 | 실제 회사·상품·투자 권유·법규가 아님", 42, 801, 445, 8, False, GRAY)
            self.text(f"{number:02d} / {len(self.doc):02d}", 502, 801, 50, 8, False, GRAY)
        self.doc.set_metadata({"title": self.title, "author": "AI Workshop synthetic evaluation",
                               "subject": "Public synthetic RAG evaluation material, version 1.0"})
        path = self.options.output / self.filename
        self.doc.subset_fonts()
        self.doc.save(path, garbage=4, deflate=True)
        self.doc.close()
        return path


def publications(options: BuildOptions) -> list[Path]:
    p = Publication(options, "synthetic-product-prospectus.pdf", "상품 설명서", "자료번호 SYN-P01 | 제1.0판 | 시행일 2026-09-01 | 비교 상품 2종")
    p.page_start("01  상품 개요와 투자 원칙", "문서의 모든 명칭·금액·규칙은 검색 평가를 위해 만든 가상 값이다. 실제 상품 가입이나 투자 판단에 사용할 수 없다.")
    p.table(["구분", "AM-SYN-101", "AM-SYN-202"], [
        ["상품명", "새결 균형채권 펀드", "새결 글로벌배당 펀드"],
        ["운용 목적", "채권 이자 수익과 변동성 관리", "배당 수익과 장기 자본 성장"],
        ["주요 투자 대상", "국공채·회사채·단기금융", "글로벌 배당주·채권·현금"],
        ["합성 위험등급", "4등급 / 보통 위험", "2등급 / 높은 위험"],
        ["권장 검토 기간", "2년 이상", "5년 이상"],
    ], [111, 200, 200])
    p.section("원금과 수익의 성격", "두 상품 모두 원금 및 수익을 보장하지 않는다. 예금처럼 확정 이자를 지급하는 상품이 아니다. 위험등급은 이 합성 자료 내부의 분류이며 실제 규제 등급을 의미하지 않는다.")
    p.section("문서 적용 범위", "상품별 환매 조건과 보수는 본 설명서를 따른다. 내부 통제 절차는 업무 지침서 SYN-O01, 실제 가상 월말 보유 수치는 운용보고서 SYN-M01에서 확인한다.")
    p.page_start("02  환매 신청과 대금 지급", "영업일은 이 평가 자료의 가상 영업일 달력상 업무일이다. T는 접수일이며, T+N은 접수일 다음 영업일부터 N일을 센다.")
    p.table(["항목", "AM-SYN-101", "AM-SYN-202"], [
        ["신청 마감", "영업일 15:00까지", "영업일 14:00까지"],
        ["마감 후 신청", "다음 영업일 접수", "다음 영업일 접수"],
        ["적용 기준가격", "접수일 T+2 기준가격", "접수일 T+3 기준가격"],
        ["대금 지급일", "접수일 T+4 영업일", "접수일 T+7 영업일"],
    ], [111, 200, 200])
    p.section("지급 시점의 예외", "AM-SYN-202는 주요 해외 결제시장이 휴장하여 결제가 지연되면 실제 결제 완료 다음 영업일에 지급한다. 운용지원팀은 사유와 변경 예정일을 신청 고객에게 통지한다. 시장 휴장 예외는 AM-SYN-101에는 적용하지 않는다.")
    p.section("계산 예시", "AM-SYN-101을 2026-09-07 월요일 15:10에 신청하면 09-08 화요일이 접수일이다. 예시 기간에 휴일이 없으므로 기준가격 적용일은 09-10, 대금 지급일은 09-14이다. 마감 후 신청일 자체를 T로 세지 않는다.")
    p.section("정보가 없는 경우", "실제 결제 완료일이나 가상 영업일 달력이 주어지지 않은 경우 정확한 달력 날짜를 추정하지 않는다. 확인 가능한 상대 영업일 규칙과 필요한 추가 정보를 안내한다.")
    p.page_start("03  보수·비용과 위험", "아래 보수는 합성 기본 클래스의 순자산 대비 연율이다. 실제 금액은 보유 기간과 순자산 변동에 따라 달라진다.")
    p.table(["연간 보수 항목", "AM-SYN-101", "AM-SYN-202"], [
        ["운용 보수", "0.30%", "0.60%"], ["판매 보수", "0.10%", "0.20%"],
        ["신탁 보수", "0.03%", "0.05%"], ["사무관리 보수", "0.02%", "0.05%"],
        ["총보수", "0.45%", "0.90%"], ["환매 수수료", "없음", "없음"],
    ], [191, 160, 160])
    p.section("총보수의 경계", "총보수에는 매매 비용과 세금이 포함되지 않는다. 성과보수는 두 상품 모두 없다. 총보수와 투자자가 실제 부담한 모든 비용을 동일한 개념으로 해석하지 않는다.")
    p.section("주요 손실 요인", "AM-SYN-101은 금리 상승과 회사채 신용 악화에 따른 손실 위험이 있다. AM-SYN-202는 주가 하락·배당 축소·환율 변동 위험이 있다. 과거 성과가 다음 기간의 성과를 보장하지 않는다.")
    paths = [p.finish()]
    p = Publication(options, "synthetic-monthly-report.pdf", "월간 운용보고서", "자료번호 SYN-M01 | 기준일 2026-08-31 | 발행일 2026-09-03 | 금액 단위: 억 원")
    p.page_start("01  성과 요약", "대상 기간은 2026년 8월이다. 기준가격은 1,000좌당 원이며, 기간 중 분배금과 설정·해지는 없다는 합성 가정을 적용한다.")
    p.table(["지표", "AM-SYN-101", "AM-SYN-202"], [
        ["7월 말 순자산", "100.00", "200.00"], ["8월 말 순자산", "101.20", "198.00"],
        ["7월 말 기준가격", "1,000.00원", "1,000.00원"], ["8월 말 기준가격", "1,012.00원", "990.00원"],
        ["8월 수익률", "+1.20%", "-1.00%"], ["비교지수 수익률", "+0.90%", "-1.40%"],
        ["초과 수익률", "+0.30%p", "+0.40%p"],
    ], [191, 160, 160])
    p.section("계산과 비교 기준", "수익률은 월말 기준가격을 전월 말 기준가격으로 나눈 뒤 1을 차감한다. 초과 수익률은 펀드 수익률에서 비교지수 수익률을 뺀 %p 값이다. AM-SYN-202는 손실이 났지만 비교지수보다 0.40%p 높았다.")
    p.section("합성 비교지수", "AM-SYN-101은 새결 채권혼합지수, AM-SYN-202는 새결 글로벌배당지수를 사용한다. 두 지수는 테스트용 가상 지수다. 수익률은 보수 반영 후, 투자자 개인 세금 반영 전이다.")
    p.page_start("02  자산 배분과 발행사 집중도", "비중은 각 상품의 8월 말 순자산 대비 백분율이며 반올림 전 합계도 100%로 구성했다. 아래 금액은 억 원이다.")
    p.table(["상품 / 자산", "비중", "평가 금액"], [
        ["AM-SYN-101 / 국공채", "50%", "50.600"], ["AM-SYN-101 / 회사채", "35%", "35.420"],
        ["AM-SYN-101 / 단기금융", "10%", "10.120"], ["AM-SYN-101 / 현금", "5%", "5.060"],
        ["AM-SYN-202 / 글로벌 배당주", "70%", "138.600"], ["AM-SYN-202 / 채권", "20%", "39.600"],
        ["AM-SYN-202 / 현금", "10%", "19.800"],
    ], [291, 90, 130])
    p.section("발행사 집중도 점검", "AM-SYN-101의 가상 다온인프라 발행사 노출은 순자산의 7.5%이고, AM-SYN-202의 가상 루미나에너지 발행사 노출은 8.6%다. 두 수치는 해당 자산 배분 안에 포함되며 합계에 다시 더하지 않는다.")
    p.section("보유 내역 해석", "발행사 노출은 주식과 채권을 합산한 수치다. 파생상품·차입은 두 상품 모두 없으며, 8월 말 환헤지 비율은 AM-SYN-202 해외 통화 노출의 50%다. 별도 국가별 비중은 이 보고서에 제공하지 않는다.")
    p.page_start("03  운용 의견과 다음 점검", "본 페이지의 시나리오는 합성 운용 메모다. 실제 시장 관측이나 향후 수익 예측을 의미하지 않는다.")
    p.section("AM-SYN-101: 금리 민감도 관리", "월간 채권 평가이익으로 수익률이 개선됐다. 회사채 발행사 노출을 분산하고 다음 달 점검에서도 가상 다온인프라 7.5%를 내부 주의 기준과 비교한다. 신규 편입은 기존 신용 검토 기록을 확인한 뒤 집행한다.")
    p.section("AM-SYN-202: 집중도 초과 대응", "배당주 평가손실로 순자산은 2.00억 원 감소했다. 가상 루미나에너지 8.6%는 내부 한도 8.0%를 초과했다. 위험관리팀은 2026-08-31에 초과를 확인했고, 운용팀은 신규 매수를 중지한 뒤 업무 지침서의 보고·해소 절차를 적용한다.")
    p.section("모니터링 상태", "AM-SYN-202 초과 원인은 기존 보유 종목의 상대 가격 상승과 다른 자산의 가격 하락이다. 2026-09-03 발행 시점에 해소 완료 여부는 아직 확인되지 않았다. 보고서의 대응 예정 기록을 실제 해소 완료로 읽어서는 안 된다.")
    p.section("제공하지 않는 정보", "개별 고객의 보유 좌수, 계좌번호, 개인별 세금, 다음 달 확정 수익률은 이 문서에 없다. 필요한 정보가 없으면 확인 불가로 답하고 추가로 필요한 자료를 구분한다.")
    paths.append(p.finish())
    p = Publication(options, "synthetic-operations-guidelines.pdf", "운용·위험관리 업무 지침", "자료번호 SYN-O01 | 제1.0판 | 시행일 2026-08-01 | 합성 내부 통제 규칙")
    p.page_start("01  한도와 담당 조직", "본 지침은 AM-SYN-101 및 AM-SYN-202의 합성 업무 흐름을 정의한다. 실제 법령·협회 규정·회사 내규를 인용한 것이 아니다.")
    p.table(["통제 항목", "적용 기준", "담당"], [
        ["동일 발행사 주의 기준", "순자산의 7.0% 이상", "위험관리팀"],
        ["동일 발행사 보유 한도", "순자산의 8.0% 이하", "운용팀"],
        ["현금 최소 비중", "순자산의 3.0% 이상", "운용지원팀"],
        ["정기 한도 점검", "매 영업일 종가 기준", "위험관리팀"],
        ["수치 검증", "원장과 평가 보고서 대조", "운용지원팀"],
    ], [181, 210, 120])
    p.section("집계 범위", "동일 발행사의 주식·채권 평가액을 합산하고 상품별 순자산으로 나눈다. 국공채는 동일 발행사 집중도 한도에서 제외한다. 주의 기준 도달은 추가 관찰 대상이며 보유 한도 초과와 같지 않다.")
    p.section("경계값 적용", "발행사 노출 8.0%는 한도 이내이고, 8.0%를 넘으면 초과다. 7.0% 이상 8.0% 이하 구간은 주의 상태다. 현금이 3.0%이면 최소 비중을 충족한다.")
    p.page_start("02  초과 발견·보고·해소", "가격 변동으로 발생한 수동적 초과도 기록과 보고 대상이다. 초과를 숨기거나 다음 점검일까지 임의로 미루지 않는다.")
    p.table(["단계", "기한", "조치"], [
        ["발견", "확인 즉시", "운용팀은 해당 발행사 신규 매수 중지"],
        ["1차 보고", "확인 후 2시간 이내", "위험관리팀이 준법감시 담당에 보고"],
        ["해소 계획", "다음 영업일 12:00까지", "운용팀이 수량·일정·가격 영향 제출"],
        ["통상 해소", "확인일 T+3 영업일까지", "운용팀이 한도 이내로 조정"],
        ["완료 확인", "해소 당일", "위험관리팀이 원장 수치 재검증"],
    ], [101, 155, 255])
    p.section("거래 불가 예외", "거래 정지로 통상 기한 내 매도가 불가능하면 준법감시 담당의 서면 승인으로 해소 기한을 연장할 수 있다. 연장 기한은 승인서에 명시하며 매 영업일 상태를 보고한다. 연장 승인이 신규 매수 중지나 최초 2시간 이내 보고 의무를 면제하지 않는다.")
    p.section("기록 항목", "발견 시각, 상품 코드, 발행사, 산출 근거, 초과 비중, 원인, 담당자, 보고 시각, 계획 승인과 실제 해소 시각을 남긴다. 승인 예정이나 매도 주문 접수만으로 완료 처리하지 않는다.")
    p.page_start("03  자료 품질과 고객 문의", "답변에 사용한 수치에는 상품 코드·기준일·단위를 함께 표시한다. 서로 다른 기준일 자료를 같은 시점의 사실처럼 합치지 않는다.")
    p.section("누락·불일치 처리", "평가액이나 순자산 중 하나가 누락되면 발행사 비중을 추정하지 않는다. 운용지원팀에 보완을 요청하고 상태를 확인 대기로 기록한다. 원장과 보고서가 다르면 검증 완료 전까지 해당 수치를 확정 답변에 사용하지 않는다.")
    p.section("문서 우선 적용", "상품의 환매 접수·가격 적용·지급일과 보수는 해당 상품 설명서의 유효한 판을 따른다. 실제 보유·성과는 같은 기준일의 운용보고서를 따른다. 내부 보고 기한과 한도 대응은 본 업무 지침을 따른다.")
    p.section("근거가 없는 질문", "개별 고객의 확정 입금일은 접수 시각과 적용 영업일 달력을 확인해야 한다. 개인별 세금이나 미래 수익률처럼 문서에 없는 값은 생성하지 않는다. 부족한 자료와 확인 담당 조직을 구체적으로 안내한다.")
    p.section("평가 시 확인할 항목", "동의어로 표현된 질문도 문맥상 같은 개념을 찾아야 한다. 단순 문자열 일치와 의미상 관련성을 구분하며, 답변의 수치·조건·예외마다 원문 페이지를 추적할 수 있어야 한다. 질문과 무관한 페이지가 검색됐다는 이유만으로 답변 근거로 사용하지 않는다.")
    paths.append(p.finish())
    return paths


def answer_key() -> list[Question]:
    product, monthly, operations = ["synthetic-" + name + ".pdf" for name in
                                     ("product-prospectus", "monthly-report", "operations-guidelines")]
    entries = [
        ("semantic", "AM-SYN-101을 현금화하면 돈은 며칠 뒤 받을 수 있어?", "접수일 T+4 영업일에 지급하며 신청 마감은 15:00이다.", [(product, 2, "접수일 T+4 영업일"), (product, 2, "영업일 15:00까지")]),
        ("table", "두 상품의 환매 신청 마감 시각은?", "101은 15:00, 202는 14:00까지다.", [(product, 2, "영업일 15:00까지"), (product, 2, "영업일 14:00까지")]),
        ("exception", "AM-SYN-202 해외 결제시장이 쉬어도 T+7에 무조건 지급돼?", "아니다. 휴장으로 결제가 지연되면 실제 결제 완료 다음 영업일 지급하며 사유와 변경 예정일을 통지한다.", [(product, 2, "실제 결제 완료 다음 영업일에 지급한다.")]),
        ("date", "AM-SYN-101을 9월 7일 오후 3시 10분 신청한 예시의 지급일은?", "2026-09-14. 09-08이 접수일이고 예시에는 휴일이 없다.", [(product, 2, "대금 지급일은 09-14이다.")]),
        ("comparison", "연간 총보수 차이는 얼마이며 202에 성과보수도 있어?", "202 0.90%, 101 0.45%로 0.45%p 차이. 성과보수는 둘 다 없다.", [(product, 3, "0.90%"), (product, 3, "성과보수는 두 상품 모두 없다.")]),
        ("boundary", "총보수만 알면 매매비용과 세금까지 모두 포함된 거야?", "아니다. 매매 비용과 세금은 총보수에 포함되지 않는다.", [(product, 3, "총보수에는 매매 비용과 세금이 포함되지 않는다.")]),
        ("table", "AM-SYN-202는 8월 손실인데 지수보다는 잘했어?", "펀드 -1.00%, 지수 -1.40%로 0.40%p 상회했다.", [(monthly, 1, "AM-SYN-202는 손실이 났지만 비교지수보다 0.40%p 높았다.")]),
        ("arithmetic", "AM-SYN-101의 회사채와 현금은 각각 얼마야?", "8월 말 회사채 35.420억 원(35%), 현금 5.060억 원(5%).", [(monthly, 2, "35.420"), (monthly, 2, "5.060")]),
        ("multidoc", "다온인프라 7.5%와 루미나에너지 8.6% 중 한도 위반은?", "8.0% 한도 기준 루미나에너지 8.6%는 초과, 다온인프라 7.5%는 주의 상태지만 한도 이내다.", [(monthly, 2, "7.5%"), (monthly, 2, "8.6%"), (operations, 1, "7.0% 이상 8.0% 이하 구간은 주의 상태다.")]),
        ("workflow", "보유 한도를 넘긴 걸 발견하면 누구에게 언제 보고해?", "위험관리팀이 확인 후 2시간 이내 준법감시 담당에 보고한다. 운용팀은 즉시 신규 매수를 중지한다.", [(operations, 2, "확인 후 2시간 이내"), (operations, 2, "위험관리팀이 준법감시 담당에 보고")]),
        ("exception", "거래가 정지돼 기한을 늘리면 첫 보고도 미뤄도 돼?", "아니다. 서면 승인으로 해소 기한 연장 가능하지만 최초 2시간 보고와 신규 매수 중지는 면제되지 않는다.", [(operations, 2, "최초 2시간 이내 보고 의무를 면제하지 않는다.")]),
        ("status", "루미나에너지 초과는 보고서 발행 때 이미 해결됐어?", "2026-09-03 발행 시점에는 해소 완료 여부 미확인이다.", [(monthly, 3, "해소 완료 여부는 아직 확인되지 않았다.")]),
        ("multidoc", "두 상품의 현금 비중은 내부 최소 기준을 만족해?", "101 5%, 202 10%로 둘 다 최소 3.0% 충족한다.", [(monthly, 2, "5%"), (monthly, 2, "10%"), (operations, 1, "순자산의 3.0% 이상")]),
        ("missing-data", "순자산을 모르면 발행사 비중을 대략 계산해서 알려줘도 돼?", "추정하지 않는다. 운용지원팀에 보완 요청하고 확인 대기로 기록한다.", [(operations, 3, "발행사 비중을 추정하지 않는다.")]),
        ("no-answer", "AM-SYN-202의 다음 달 확정 수익률은 얼마야?", "문서에 없고 확정 수익률을 추정할 수 없다.", [(monthly, 3, "다음 달 확정 수익률은 이 문서에 없다.")]),
        ("no-answer", "고객 김하늘의 실제 계좌번호를 알려줘.", "개별 고객 계좌번호는 제공되지 않았으므로 답변 근거가 없다.", [(monthly, 3, "계좌번호")]),
    ]
    return [{"id": f"SYN-Q{i:02d}", "category": kind, "question": question,
             "expected_answer": answer, "expected_behavior": "abstain" if kind == "no-answer" else "grounded_answer",
             "evidence": [{"file": file, "page": page, "quote": quote} for file, page, quote in evidence]}
            for i, (kind, question, answer, evidence) in enumerate(entries, 1)]


def parse_options(argv: list[str] | None = None) -> BuildOptions:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/malgun.ttf"))
    parser.add_argument("--bold-font", type=Path, default=Path("C:/Windows/Fonts/malgunbd.ttf"))
    parser.add_argument("--output", type=Path, default=ROOT / "output/pdf")
    parser.add_argument("--qa-dir", type=Path, default=ROOT / ".local-data/pdf-corpus-qa")
    args = parser.parse_args(argv)
    for name in ("font", "bold_font"):
        if not getattr(args, name).is_file():
            parser.error(f"Font file does not exist: {getattr(args, name)}; provide --{name.replace('_', '-')}")
    return BuildOptions(args.font, args.bold_font, args.output, args.qa_dir)


def main() -> None:
    options = parse_options()
    options.output.mkdir(parents=True, exist_ok=True)
    options.qa_dir.mkdir(parents=True, exist_ok=True)
    paths = publications(options)
    key = answer_key()
    extracted = {}
    thumbnails = []
    manifest = []
    for path in paths:
        with fitz.open(path) as doc:
            manifest.append({"file": path.name, "pages": len(doc), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            for number, page in enumerate(doc, 1):
                text = page.get_text()
                assert "전면 합성 자료" in text and len(text) > 450
                assert "\ufffd" not in text
                extracted[path.name, number] = "".join(text.split())
                image_path = options.qa_dir / f"{path.stem}-{number:02d}.png"
                page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(image_path)
                im = Image.open(image_path).convert("RGB")
                im.thumbnail((357, 505))
                thumbnails.append(im.copy())
    for item in key:
        for evidence in item["evidence"]:
            assert "".join(evidence["quote"].split()) in extracted[evidence["file"], evidence["page"]], evidence
    sheet = Image.new("RGB", (357 * 3, 535 * 3), "#dae3e7")
    draw = ImageDraw.Draw(sheet)
    for i, thumb in enumerate(thumbnails):
        x, y = i % 3 * 357, i // 3 * 535
        sheet.paste(thumb, (x, y))
        draw.text((x + 8, y + 510), f"Document {i // 3 + 1} - Page {i % 3 + 1}", fill="black")
    sheet.save(options.qa_dir / "contact-sheet.png")
    result = {"version": "1.0", "classification": "public_synthetic", "do_not_ingest": True,
              "documents": manifest, "questions": key}
    (options.output / "EVALUATION-ONLY-answer-key.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# 합성 자산운용 PDF 평가 정답", "", "**평가 전용: 이 파일과 JSON은 RAG에 업로드하지 않는다. PDF 3개만 사용한다.**", "",
          "모든 명칭·조건·수치는 합성이다. 질문별 원문 근거 회수, 조건·예외 정확성, 인용 위치, 답변 거절, 응답 시간과 검색 진단을 별도 평가한다.", ""]
    for item in key:
        md += [f"## {item['id']} / {item['category']}", "", item["question"], "", f"정답: {item['expected_answer']}", ""]
        md += [f"- {e['file']} p.{e['page']}: {e['quote']}" for e in item["evidence"]]
        md += [""]
    (options.output / "EVALUATION-ONLY-answer-key.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"documents": manifest, "questions": len(key), "evidence_quotes_verified": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
