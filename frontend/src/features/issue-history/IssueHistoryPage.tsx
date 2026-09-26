"use client";

import { useState } from "react";

import type { IssueLedger } from "./types";
import styles from "./IssueHistoryPage.module.css";

const statuses = { open: "진행 중", implemented: "구현됨 · 검증 남음", verified: "검증 완료" } as const;

export function IssueHistoryPage({ ledger, initialIssueId }: { ledger: IssueLedger; initialIssueId?: string }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [area, setArea] = useState("");
  const [selectedId, setSelectedId] = useState(initialIssueId ?? ledger.issues[0]?.id);
  const areas = [...new Set(ledger.issues.map((issue) => issue.area))].sort();
  const needle = query.trim().toLocaleLowerCase();
  const filtered = ledger.issues.filter((issue) => (!status || issue.status === status) && (!area || issue.area === area) && [issue.id, issue.title, issue.area, issue.symptom, issue.cause, issue.resolution, ...issue.remaining].join(" ").toLocaleLowerCase().includes(needle));
  const selected = filtered.find((issue) => issue.id === selectedId) ?? filtered[0];
  const resetFilters = () => { setQuery(""); setStatus(""); setArea(""); };

  return <div className={styles.page}>
    <header className={styles.heading}>
      <div><p className={styles.eyebrow}>시스템 관리</p><h1>문제·개선 이력</h1><p>발견한 문제부터 수정과 검증까지, 같은 문제의 후속 작업을 함께 확인합니다.</p></div>
      <p className={styles.updated}>내부 관리용 · 기준일 <time dateTime={ledger.updated_at}>{ledger.updated_at}</time></p>
    </header>
    <dl className={styles.summary} aria-label="전체 문제 현황">
      <div><dt>전체</dt><dd>{ledger.issues.length}</dd></div>
      {Object.entries(statuses).map(([value, label]) => <div key={value}><dt>{label}</dt><dd>{ledger.issues.filter((issue) => issue.status === value).length}</dd></div>)}
    </dl>
    <div className={styles.filters}>
      <label className={styles.search}>문제 검색<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="제목, 문제 번호, 증상 또는 원인" /></label>
      <label>처리 상태<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">전체 상태</option>{Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>영역<select value={area} onChange={(event) => setArea(event.target.value)}><option value="">전체 영역</option>{areas.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      {(query || status || area) && <button type="button" onClick={resetFilters}>필터 초기화</button>}
    </div>
    <p className={styles.resultCount} role="status">{filtered.length}개 문제 표시 · 전체 {ledger.issues.length}개</p>
    {filtered.length === 0 ? <p className={styles.empty}>{ledger.issues.length ? "조건에 맞는 문제가 없습니다." : "등록된 문제 이력이 없습니다."}</p> : <div className={styles.layout}>
      <ul className={styles.issueList} aria-label="문제 목록">{filtered.map((issue) => <li key={issue.id}><button type="button" aria-label={`${issue.id} ${issue.title} ${statuses[issue.status]}`} aria-pressed={issue.id === selected?.id} onClick={() => setSelectedId(issue.id)} className={styles.issueButton}>
        <span className={styles.issueId}>{issue.id}</span><strong>{issue.title}</strong><span className={styles.issueMeta}><span className={`${styles.badge} ${styles[issue.status]}`}>{statuses[issue.status]}</span><span>{issue.area}</span></span>
      </button></li>)}</ul>
      {selected && <section className={styles.detail} aria-label="문제 상세">
        <header className={styles.detailHeader}><p className={styles.issueId}>{selected.id} · {selected.area}</p><h2>{selected.title}</h2><span className={`${styles.badge} ${styles[selected.status]}`}>{statuses[selected.status]}</span></header>
        <section><h3>증상</h3><p>{selected.symptom}</p></section>
        <section><h3>원인</h3><p>{selected.cause}</p></section>
        <section><h3>수정 내용과 방향</h3><p>{selected.resolution}</p></section>
        <div className={styles.checks}>
          <section><h3>검증 기록</h3><TextList items={selected.verification} empty="아직 기록된 검증이 없습니다." /></section>
          <section className={styles.remaining}><h3>남은 작업</h3><TextList items={selected.remaining} empty="기록된 남은 작업이 없습니다." /></section>
        </div>
        <section><h3>진행 이력</h3>{selected.history.length ? <ol className={styles.timeline}>{selected.history.map((entry, index) => <li key={`${entry.date}-${index}`}><time dateTime={entry.date}>{entry.date}</time><p>{entry.event}</p></li>)}</ol> : <p className={styles.muted}>아직 기록된 진행 이력이 없습니다.</p>}</section>
        <section><h3>관련 문서</h3>{selected.evidence.length ? <ul className={styles.sources}>{selected.evidence.map((document, index) => <li key={`${document}-${index}`}><a href={`/admin/system/issues?issue=${encodeURIComponent(selected.id)}&document=${index}`}>{document}</a></li>)}</ul> : <p className={styles.muted}>연결된 문서가 없습니다.</p>}</section>
        <section><h3>관련 커밋</h3>{selected.commits.length ? <ul className={styles.commits}>{selected.commits.map((commit, index) => <li key={`${commit}-${index}`}><code>{commit}</code></li>)}</ul> : <p className={styles.muted}>연결된 커밋이 없습니다.</p>}</section>
      </section>}
    </div>}
  </div>;
}

function TextList({ items, empty }: { items: string[]; empty: string }) {
  return items.length ? <ul className={styles.textList}>{items.map((text, index) => <li key={index}>{text}</li>)}</ul> : <p className={styles.muted}>{empty}</p>;
}
