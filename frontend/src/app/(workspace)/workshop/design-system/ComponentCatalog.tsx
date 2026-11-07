"use client";

import { useState, type ReactNode } from "react";
import { Button, ButtonLink } from "@/shared/ui/Button";
import { ChoiceGroup } from "@/shared/ui/ChoiceGroup";
import { CheckboxField } from "@/shared/ui/CheckboxField";
import { SelectField, TextAreaField, TextField } from "@/shared/ui/Fields";
import { Disclosure, EmptyState, Notice, StatusBadge } from "@/shared/ui/Feedback";
import { Pagination } from "@/shared/ui/Pagination";
import styles from "./Gallery.module.css";

type SpecimenProps = {
  name: string;
  source?: string;
  purpose: string;
  usage: string;
  code: string;
  children: ReactNode;
};

function Specimen({ name, source = name, purpose, usage, code, children }: SpecimenProps) {
  return <article id={name} aria-labelledby={`title-${name}`} className={styles.specimen}>
    <h3 id={`title-${name}`}>{name}</h3>
    <p>{purpose}</p>
    <div className={styles.sample}>{children}</div>
    <small>사용 화면 · {usage}</small>
    <Disclosure className={styles.codePanel} summary="사용 코드">
      <pre><code>{`import { ${name} } from "@/shared/ui/${source}";\n\n${code}`}</code></pre>
    </Disclosure>
  </article>;
}

const orderOptions = [{ value: "recent", label: "최근순" }, { value: "name", label: "이름순" }];
export function ComponentCatalog() {
  const [order, setOrder] = useState("recent");
  const [page, setPage] = useState(1);
  const [buttonMessage, setButtonMessage] = useState("");
  return <>
    <nav aria-label="컴포넌트 분류" className={styles.index}>
      <a href="#actions">버튼과 선택</a><a href="#fields">입력과 폼</a>
      <a href="#feedback">상태와 안내</a><a href="#navigation">탐색과 펼침</a>
    </nav>
    <h3 id="actions" className={styles.subhead}>버튼과 선택</h3>
    <div className={styles.specimens}>
      <Specimen name="Button" purpose="한 영역에서 가장 중요한 동작 하나를 채운 버튼으로 강조합니다." usage="로그인 · 학습 기록" code={'<Button variant="primary" onClick={onSave}>저장</Button>'}>
        <div className={styles.buttonRow}>{([["primary","저장"],["secondary","취소"],["quiet","더 보기"],["danger","삭제"]] as const).map(([variant,label]) =>
          <Button key={variant} variant={variant} onClick={() => setButtonMessage(`${label} 버튼을 눌렀습니다.`)}>{label}</Button>
        )}<Button disabled>비활성</Button></div>
        {buttonMessage && <small role="status">{buttonMessage}</small>}
      </Specimen>
      <Specimen name="ButtonLink" source="Button" purpose="화면 이동을 버튼으로 강조할 때 씁니다. 링크로 열기와 키보드 탐색을 지원합니다." usage="모델 관리 · RAG 구성" code={'<ButtonLink href="/admin/rag/setup">간편 설정</ButtonLink>'}>
        <div className={styles.buttonRow}><ButtonLink href="#fields">입력과 폼으로 이동</ButtonLink></div>
      </Specimen>
      <Specimen name="ChoiceGroup" purpose="짧은 선택지를 한눈에 비교하며 하나만 고를 때 사용합니다." usage="모델 설정 · 비교 결과" code={'<ChoiceGroup legend="정렬" variant="segmented"\n  options={options} value={order} onChange={setOrder} />'}>
        <ChoiceGroup legend="정렬" variant="segmented" options={orderOptions} value={order} onChange={setOrder} />
      </Specimen>
      <Specimen name="CheckboxField" purpose="독립된 항목을 선택합니다. 라벨 전체가 클릭 영역이며 선택·포커스·비활성을 구분합니다." usage="학습 기록 · 실험 항목 · 기술 주제" code={'<CheckboxField label="실험 항목 추가"\n  checked={enabled} onChange={event => setEnabled(event.target.checked)} />'}>
        <CheckboxField label="선택하지 않은 항목" />
        <CheckboxField label="선택한 항목" defaultChecked />
        <CheckboxField label="여러 줄로 이어지는 긴 설명도 체크 표시와 첫 줄의 위치를 맞춰 읽을 수 있습니다." />
        <CheckboxField label="비활성 항목" disabled />
        <CheckboxField label="선택된 비활성 항목" defaultChecked disabled />
      </Specimen>
    </div>
    <h3 id="fields" className={styles.subhead}>입력과 폼</h3>
    <div className={styles.specimens}>
      <Specimen name="TextField" source="Fields" purpose="이름이나 제목처럼 한 줄로 입력하는 값에 씁니다." usage="공간 만들기 · 기록 편집" code={'<TextField label="공간 이름" name="name" required />'}>
        <TextField label="공간 이름" placeholder="예: 연구 자료" />
      </Specimen>
      <Specimen name="SelectField" source="Fields" purpose="항목을 선택하면 해당 행에만 보라색 강조가 표시됩니다." usage="공간 유형 · 기록 종류" code={'<SelectField label="공간 유형" name="type" defaultValue="">\n  <option value="" disabled hidden>공간 유형을 선택하세요</option>\n  <option value="personal" data-icon="personal">개인 공간</option>\n  <option value="company" data-icon="company">회사 공간</option>\n</SelectField>'}>
        <SelectField label="공간 유형" defaultValue="">
          <option value="" disabled hidden>공간 유형을 선택하세요</option>
          <option value="personal" data-icon="personal">개인 공간</option>
          <option value="company" data-icon="company">회사 공간</option>
          <option value="temporary" data-icon="temporary">임시 공간</option>
        </SelectField>
      </Specimen>
      <Specimen name="TextAreaField" source="Fields" purpose="줄바꿈을 포함하는 본문이나 설명에 사용합니다." usage="학습 기록 편집" code={'<TextAreaField label="본문" name="body" rows={4} />'}>
        <TextAreaField label="본문" placeholder="관찰한 내용을 입력하세요" rows={2} />
      </Specimen>
    </div>
    <h3 id="feedback" className={styles.subhead}>상태와 안내</h3>
    <div className={styles.specimens}>
      <Specimen name="StatusBadge" source="Feedback" purpose="개별 항목의 상태를 짧은 글자와 색으로 구분합니다." usage="문제 및 개선 이력" code={'<StatusBadge tone="success">완료</StatusBadge>'}>
        <div className={styles.buttonRow}><StatusBadge>대기</StatusBadge><StatusBadge tone="info">진행 중</StatusBadge><StatusBadge tone="success">완료</StatusBadge><StatusBadge tone="danger">실패</StatusBadge></div>
      </Specimen>
      <Specimen name="Notice" source="Feedback" purpose="사용자가 알아야 할 상태와 다음 행동을 함께 설명합니다." usage="실행 모니터링" code={'<Notice tone="warning">파일 형식을 확인해 주세요.</Notice>'}>
        <Notice tone="warning">파일 형식을 확인해 주세요.</Notice>
      </Specimen>
      <Specimen name="EmptyState" source="Feedback" purpose="목록이 비었을 때 이유와 다음 단계를 안내합니다." usage="문제 이력 · 실행 모니터링" code={'<EmptyState title="검색 결과가 없습니다"\n  description="다른 검색어로 다시 찾아보세요." />'}>
        <EmptyState title="검색 결과가 없습니다" description="다른 검색어로 다시 찾아보세요." />
      </Specimen>
    </div>
    <h3 id="navigation" className={styles.subhead}>탐색과 펼침</h3>
    <div className={styles.specimens}>
      <Specimen name="Disclosure" source="Feedback" purpose="결과를 먼저 보여주고 보조 설명은 필요할 때 펼칩니다." usage="실행 모니터링 사용 방법" code={'<Disclosure summary="처리 정보">상세 내용</Disclosure>'}>
        <Disclosure summary="처리 정보">문서에서 선택한 범위의 처리 결과입니다.</Disclosure>
      </Specimen>
      <Specimen name="Pagination" purpose="이전·다음 이동과 현재 위치를 함께 표시합니다." usage="PDF 미리보기 · 공개 연구 관리" code={'<Pagination label="문서 페이지" position={`${page} / ${total}`}\n  canGoBack={page > 1} canGoForward={page < total}\n  onPrevious={previousPage} onNext={nextPage} />'}>
        <Pagination label="예시 페이지" position={`${page} / 3`} canGoBack={page > 1} canGoForward={page < 3} onPrevious={() => setPage(page - 1)} onNext={() => setPage(page + 1)} />
      </Specimen>
    </div>
  </>;
}
