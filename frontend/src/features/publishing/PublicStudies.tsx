import Link from "next/link";

import { PublicNavigation } from "../navigation/PublicNavigation";
import { routes } from "../../shared/routing/routes";
import { catalogPages, catalogPath, studyCatalogPath, type CatalogQuery } from "./catalog-query";
import { CategoryPicker } from "./CategoryPicker";
import { StudyBody } from "./StudyBody";
import type { PublicStudyCatalog, StudySnapshot } from "./types";
import styles from "./Publishing.module.css";

export type PublicStudyListResult =
  | { status: "ready"; items: StudySnapshot[]; catalog?: Omit<PublicStudyCatalog, "items"> }
  | { status: "unavailable" };

export function PublicStudyList({ result, query }: { result: PublicStudyListResult; query?: CatalogQuery }) {
  const catalog = result.status === "ready" ? result.catalog : undefined;
  const currentQuery = catalog ? { page: catalog.page, topic: query?.topic } : query;
  return (
    <main className={`${styles.shell} ${styles.publicShell}`}>
      <PublicNavigation />
      <div className={styles.publicContent}>
        <header className={styles.header}>
          <p>PUBLIC RAG STUDIES</p>
          <h1>공개 연구 기록</h1>
          <p>승인되어 공개 저장소에 적용된 RAG 개발·실험 기록만 제공합니다.</p>
        </header>
        {catalog && <>
          <CategoryPicker key={`${currentQuery?.page}:${query?.topic ?? ""}`} topics={catalog.topics} selectedTopic={query?.topic} />
          <p className={styles.muted}>총 {catalog.total}개 기록</p>
        </>}
        {result.status === "unavailable" ? (
          <p className={styles.error} role="alert">공개 연구 서비스를 불러올 수 없습니다. 잠시 후 새로고침해 주세요.</p>
        ) : result.items.length === 0 ? (
          <p className={styles.status}>{query?.topic ? "선택한 카테고리에 공개된 연구 기록이 없습니다." : "공개된 연구 기록이 아직 없습니다."}</p>
        ) : (
          <ul className={styles.cards}>
            {result.items.map((snapshot) => (
              <li className={styles.studyCardItem} key={snapshot.content.slug}>
                <Link
                  className={styles.studyCard}
                  href={studyCatalogPath(snapshot.content.slug, currentQuery)}
                  prefetch={false}
                  data-prefetch="false"
                  aria-label={`${snapshot.content.title} 읽기`}
                >
                  <div className={styles.topics} aria-label="기술 주제">
                    {snapshot.content.topic_keys.map((topic) => <span key={topic}>{topic}</span>)}
                  </div>
                  <h2>{snapshot.content.title}</h2>
                  <p className={styles.plainText}>{snapshot.content.summary}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {catalog && catalog.total_pages > 0 && <nav className={styles.catalogPager} aria-label="연구 기록 페이지">
          {catalog.page > 1 ? <Link href={catalogPath({ ...currentQuery, page: catalog.page - 1 })} prefetch={false} aria-label="이전 페이지">← 이전</Link> : <span aria-label="이전 페이지" aria-disabled="true">← 이전</span>}
          {catalogPages(catalog.page, catalog.total_pages).map((page) => typeof page === "number" ? <Link key={page} href={catalogPath({ ...currentQuery, page })} prefetch={false} aria-label={`${page}페이지`} aria-current={page === catalog.page ? "page" : undefined}>{page}</Link> : <span key={page} aria-hidden="true">…</span>)}
          {catalog.page < catalog.total_pages ? <Link href={catalogPath({ ...currentQuery, page: catalog.page + 1 })} prefetch={false} aria-label="다음 페이지">다음 →</Link> : <span aria-label="다음 페이지" aria-disabled="true">다음 →</span>}
        </nav>}
      </div>
    </main>
  );
}

export function PublicStudyDetail({ snapshot, query }: { snapshot: StudySnapshot; query?: CatalogQuery }) {
  return (
    <main className={`${styles.shell} ${styles.publicShell}`}>
      <PublicNavigation />
      <div className={`${styles.publicContent} ${styles.detailContent}`}>
        <Link className={styles.readIndicator} href={catalogPath(query)}>공개 연구 기록으로 돌아가기</Link>
        <StudyBody snapshot={snapshot} />
        <p className={styles.help}>
          철회 후 새 탐색이나 새로고침에서는 이 기록을 다시 조회하지 않습니다. 이미 열었거나 복사한 내용은 되돌려 회수할 수 없습니다.
        </p>
      </div>
    </main>
  );
}

export function PublicStudyNotFound() {
  return (
    <main className={`${styles.shell} ${styles.publicShell}`}>
      <PublicNavigation />
      <div className={styles.publicContent}>
        <h1>연구 기록을 찾을 수 없습니다</h1>
        <p>존재하지 않거나 공개가 철회된 기록입니다.</p>
        <Link href={routes.ragStudies}>공개 연구 기록 보기</Link>
      </div>
    </main>
  );
}

export function PublicStudyUnavailable() {
  return (
    <main className={`${styles.shell} ${styles.publicShell}`}>
      <PublicNavigation />
      <div className={styles.publicContent}>
        <h1>공개 연구 서비스를 사용할 수 없습니다</h1>
        <p role="alert">잠시 후 새로고침해 주세요.</p>
      </div>
    </main>
  );
}
