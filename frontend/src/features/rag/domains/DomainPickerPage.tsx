import Link from "next/link";

import { routes, ragDomainChatPath, ragDomainFilesPath } from "../../../shared/routing/routes";
import type { Domain } from "./api";

export function DomainPickerPage({ domains, isOwner }: { domains: Domain[]; isOwner: boolean }) {
  const canAccessFiles = (domain: Domain): boolean =>
    domain.active && domain.connection_version !== null && domain.workspace_options.length > 0;

  return (
    <main className="domain-picker-shell">
      <header className="domain-picker-header">
        <p className="eyebrow">전문 도메인 RAG</p>
        <h1>전문 도메인을 선택하세요</h1>
        <p>허용된 지식 범위와 검증된 생성 구성이 연결된 도메인에서 대화를 시작합니다.</p>
        <div className="domain-picker-actions">
          <Link href={routes.workshopHome}>문서함 홈</Link>
        </div>
      </header>

      {domains.length === 0 ? (
        <section className="domain-empty" aria-label="도메인 준비 상태">
          <h2>{isOwner ? "도메인 준비가 필요합니다" : "사용 가능한 도메인이 아직 없습니다"}</h2>
          <p>
            {isOwner
              ? "도메인을 생성하고 연결/평가/생성 구성을 마쳐야 대화형 RAG를 시작할 수 있습니다."
              : "권한이 허용된 준비 완료 도메인이 아직 없습니다. 관리자에게 도메인 상태 확인을 요청해 주세요."}
          </p>
          {isOwner ? <Link href={routes.adminRagDomains}>도메인 관리</Link> : null}
        </section>
      ) : (
        <section className="domain-grid" aria-label="사용 가능한 전문 도메인">
          {domains.map((domain) => (
            <article className={`domain-card${domain.ready ? "" : " is-unready"}`} key={domain.id}>
              <div>
                <span className="domain-state">{domain.ready ? "대화 가능" : "준비 필요"}</span>
                {domain.ready ? null : <p className="domain-state-hint">{domainReasonMessage(domain)}</p>}
                <h2>{domain.display_name}</h2>
                <p>{domain.description || "이 도메인에 대한 설명이 아직 없습니다."}</p>
              </div>
              <div className="domain-card-actions">
                {canAccessFiles(domain) ? (
                  <>
                    <Link href={ragDomainFilesPath(domain.slug)} aria-label={`${domain.display_name} 파일함`}>파일함</Link>
                    {domain.ready ? <Link href={ragDomainChatPath(domain.slug)} aria-label={`${domain.display_name} 대화 시작`}>대화 시작</Link> : null}
                  </>
                ) : (
                  <span className="domain-disabled" aria-disabled="true">{domainDisabledReason(domain)}</span>
                )}
                {domain.ready ? null : (
                  <span className="domain-disabled" aria-live="polite">
                    {isOwner ? "도메인 관리에서 연결/구성/평가를 완료해야 대화 시작이 가능합니다." : "관리자 설정이 완료되면 대화 시작이 가능합니다."}
                  </span>
                )}
                {isOwner ? <Link href={routes.adminRagDomains} aria-label={`${domain.display_name} 도메인 관리`}>도메인 관리</Link> : null}
              </div>
            </article>
          ))}
        </section>
      )}
    </main>
  );
}

function domainReasonMessage(domain: Domain): string {
  const reasons = domain.readiness.reason_codes;
  if (reasons.includes("configuration_not_evaluated")) return "구성 검증이 필요합니다.";
  if (reasons.includes("generation_not_configured")) return "생성 구성 누락으로 대화가 제한됩니다.";
  if (reasons.includes("domain_inactive")) return "도메인 연결이 비활성 상태입니다.";
  if (reasons.includes("domain_connection_missing")) return "연결 버전이 없습니다. 관리자 메뉴에서 연결을 생성하세요.";
  if (reasons.includes("domain_scope_unavailable")) return "워크스페이스 권한 또는 구성이 맞지 않습니다.";
  if (reasons.some((reason) => reason.includes("index") || reason.includes("search"))) return "검색 인덱스가 준비되지 않았습니다.";
  return "준비 중입니다.";
}

function domainDisabledReason(domain: Domain): string {
  if (domain.connection_version === null) return "연결 준비 중";
  if (!domain.active) return "도메인 비활성";
  if (domain.workspace_options.length === 0) return "권한이 허용되는 작업 공간이 없어 파일 접근을 비활성화했습니다.";
  return "연결 준비 중";
}
