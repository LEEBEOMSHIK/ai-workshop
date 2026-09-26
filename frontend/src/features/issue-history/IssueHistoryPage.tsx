"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Category, IssueDetail, IssueList } from "./types";
import type { IssueFilters } from "./api";
import { IssueManagement } from "./IssueManagement";
import { CategorySelect, categoryPath } from "./CategorySelect";
import styles from "./IssueHistoryPage.module.css";
export const statuses = { open: "진행 중", implemented: "구현됨 · 검증 남음", verified: "검증 완료" } as const;
export function IssueHistoryPage({ list, categories, selected, filters, legacy }: {
    list: IssueList;
    categories: Category[];
    selected: IssueDetail | null;
    filters: IssueFilters;
    legacy?: boolean;
}) {
    const router = useRouter();
    const [manage, setManage] = useState(false);
    const total = Object.values(list.status_counts).reduce((a, b) => a + b, 0);
    const href = (changes: Record<string, string | number>) => { const p = new URLSearchParams(); for (const [key, value] of Object.entries({ ...filters, ...changes }))
        if (value !== undefined && value !== "")
            p.set(key, String(value)); return `/admin/system/issues?${p}`; };
    const category = (id: string) => categoryPath(categories, id);
    return <div className={styles.page}>
 <header className={styles.heading}><div><p className={styles.eyebrow}>시스템 관리</p><h1>문제·개선 이력</h1><p>문제의 수정·검증 기록과 당시 문서 버전을 함께 보존합니다.</p></div><button onClick={() => setManage(!manage)} aria-expanded={manage}>{manage ? "관리 닫기" : "이력 관리"}</button></header>
 {legacy && <p role="status">이전 문서 링크입니다. 문제 상세에서 관련 문서를 다시 선택해 주세요.</p>}
 {manage && <IssueManagement categories={categories} issue={selected} onSaved={() => router.refresh()}/>}
 <dl className={styles.summary} aria-label="전체 문제 현황"><div><dt>전체</dt><dd>{total}</dd></div>{Object.entries(statuses).map(([value, label]) => <div key={value}><dt>{label}</dt><dd>{list.status_counts[value as keyof typeof statuses]}</dd></div>)}</dl>
 <form className={styles.filters} action="/admin/system/issues">
 <label className={styles.search}>문제 검색<input type="search" name="q" defaultValue={filters.q} placeholder="현재·이전 번호, 제목, 증상, 원인"/></label>
 <label>처리 상태<select name="status" defaultValue={filters.status}><option value="">전체 상태</option>{Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
 <CategorySelect key={`${filters.parent_category_id ?? ""}:${filters.category_id ?? ""}`} categories={categories} initialParent={filters.parent_category_id} initialChild={filters.category_id} mode="filter"/><button type="submit">검색</button><a href="/admin/system/issues">필터 초기화</a></form>
 <p className={styles.resultCount} role="status">조건에 맞는 문제 {list.total}개 · 전체 {total}개</p>
 {!list.items.length && <p className={styles.empty}>{total ? "조건에 맞는 문제가 없습니다." : "등록된 문제 이력이 없습니다."}</p>}
 <div className={styles.layout}><div><ul className={styles.issueList} aria-label="문제 목록">{list.items.map(issue => <li key={issue.id}><a className={styles.issueButton} aria-current={selected?.id === issue.id ? "true" : undefined} href={href({ issue: issue.id })}><span className={styles.issueId}>{issue.issue_key}</span><strong>{issue.title}</strong><span className={styles.issueMeta}><span className={`${styles.badge} ${styles[issue.status]}`}>{statuses[issue.status]}</span>{category(issue.category_id)}</span></a></li>)}</ul><nav className={styles.actions} aria-label="문제 목록 페이지">{(filters.offset ?? 0) > 0 && <a href={href({ offset: Math.max(0, (filters.offset ?? 0) - 20) })}>이전</a>}{(filters.offset ?? 0) + 20 < list.total && <a href={href({ offset: (filters.offset ?? 0) + 20 })}>다음</a>}</nav></div>
 {selected && <section className={styles.detail} aria-label="문제 상세"><header className={styles.detailHeader}><p className={styles.issueId}>{selected.issue_key} · {category(selected.category_id)}</p>{(selected.legacy_keys ?? []).length > 0 && <p className={styles.issueId}>이전 번호: {selected.legacy_keys?.join(", ")}</p>}<h2>{selected.title}</h2><span className={`${styles.badge} ${styles[selected.status]}`}>{statuses[selected.status]}</span></header>
 <section><h3>증상</h3><p>{selected.symptom}</p></section><section><h3>원인</h3><p>{selected.cause}</p></section><section><h3>수정 내용과 방향</h3><p>{selected.resolution}</p></section>
 <div className={styles.checks}><section><h3>검증 기록</h3><TextList items={selected.verification ?? []}/></section><section className={styles.remaining}><h3>남은 작업</h3><TextList items={selected.remaining ?? []}/></section></div>
 <section><h3>진행 이력</h3><ol className={styles.timeline}>{selected.events.map(event => <li key={event.id}><time>{event.event_date}</time><p>{event.description}</p></li>)}</ol></section>
 <section><h3>관련 문서</h3>{selected.documents.length ? <ul className={styles.sources}>{selected.documents.map(doc => <li key={`${doc.document_id}-${doc.version}`}><a href={href({ issue: selected.id, document_id: doc.document_id, version: doc.version })}>{doc.title} · 버전 {doc.version}</a>{doc.current_version !== doc.version && <span> (현재 버전 {doc.current_version}, 과거 근거 유지)</span>}<div className={styles.muted}>{doc.source_path}</div></li>)}</ul> : <p>연결된 문서가 없습니다.</p>}</section>
 <section><h3>관련 커밋</h3><TextList items={selected.commits ?? []}/></section></section>}</div></div>;
}
function TextList({ items }: {
    items: string[];
}) { return items.length ? <ul className={styles.textList}>{items.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p className={styles.muted}>기록이 없습니다.</p>; }
