# RAG 접근 epoch 구현 계획 준비와 검토

- 날짜: 2026-10-01
- 문제: ISSUE-00013
- 상태: 설계 사용자 승인, 구현 계획 자체·독립 보안/계약 검토 완료, 사용자 계획 검토·실행 방식 선택 대기
- 설계: [승인된 계약](../superpowers/specs/2026-10-01-rag-access-epoch-design.md)
- 구현 계획: [6개 작업](../superpowers/plans/2026-10-01-rag-access-epoch.md)
- 선행 기록: [설계 검토](2026-10-01-rag-access-epoch-design-review.md)

사용자의 진행 지시는 승인된 설계에 따른 구현 준비로 반영했다. DB·배포·인증의
고위험 변경으로 분류하고 요구/시스템 설계, Python·DB·Docker, RAG·테스트 설계 역할을
선정했다. 별도 보안·계약 검토는 작성 책임에서 분리했으며 UI·모델 튜닝은 범위 밖이다.

6개 작업에 실제 경로·공유 타입·정확한 v2 필드·검증 명령을 기재했다. 메인 Codex는
설계 전 조항과 자체 검토5개 항목을 직접 대조했다. append-only event와 상태 projection의
구분, launcher 반환 테스트 필드, 본래 Windows selector loop·worker/beat flags,
보호된 floor anchor→DB verified commit의 crash/readback 순서를 구체화했다.

독립 보고서는 `.local-data/project-agent-work/alias-access-epoch-plan-20261001/`에 남긴다.
최종 양쪽 판정은 **Ready for user plan review**다. 계약 검토3건을 수정했다:
pytest는 backend cwd의 새 child에서 inherited settings를 비우고 실행하고, 테스트는
외부 경계만 fake로 두며 실제 repository/launcher/controller/service를 호출한다.
공개 HTTPS·CA·epoch Settings는 DB-only/Alembic/beat에 허용하되 실제 ES factory·admission은
key/role이 없으면 거부하는 paired tests를 포함한다. 보안·계약 재검토는 동일 최종 plan
SHA256 `45b451c36fe53da25b031dec8d7e57c306fdff49195a7ad264a79595c15a66e5`를 확인했다.

문서 상대 링크·미완성 표식·공백, AGENTS200줄, 최근 완료5개, 미래 pytest helper Python 문법을
검사했다. 기존 HOST 구현2파일 SHA는 그대로이며 0062는 아직 없다. 최초 최근 완료 개수
검사기는 목록을 bullet로 오인해 실패했지만 실제 numbered list를 기준으로 수정 후5개를 확인했다. 현재 계획 작성만 수행했으며
제품 코드·테스트·migration·서버·credential·원본 계정/자료는 변경하지 않았다.
이전 HOST369건은 새 v2 검증 결과가 아니다. 현재 원본 상태 설명은 이전 실행의 인계다.

`writing-plans`의 계획 검토·실행 방식 선택 절차가 남아 있다. 결합된6개 작업이므로
메인 Codex가 현재 세션에서 구현하고 별도 독립 검증/리뷰를 하는 방식을 권장한다.
선택 후 오프라인 구현·검증을 진행하고 실제 ES 전환은 별도 구체적 승인으로 다룬다.
본래 관리자 로그인 만료로 문제 DB의 문서 등록·진행 이력 저장은 아직 미완료다.
기능 마감 기준이 남아 있어 품질 개선만 남았다는 보고는 하지 않는다.
