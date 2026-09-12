# 비공개 Learning 1단계 구현·검증

- 상태: 코드·자동 검증·최종 독립 재리뷰 완료 — 개발 DB 적용·실제 브라우저 확인 대기
- 작업 브랜치: main, 기존 변경 보존, 자동 commit/push 없음
- 설계: [학습·서비스 연결](../superpowers/specs/2026-09-07-learning-service-link-design.md)
- 실행 계획: [Private Learning](../superpowers/plans/2026-09-07-private-learning.md)
- 경계 결정: [ADR 0016](../decisions/0016-private-learning-records.md)

## 역할과 범위

사용자 요청에 따라 역할별 에이전트가 직접 구현하고 별도 에이전트가 독립 검토한다.
도메인 담당→DB 담당→Python API 담당→프론트 담당 순으로 계약을 인계한다.
오케스트레이터는 범위·문서·통합·검증 증거를 관리하며 구현자의 결함 수정을 대신하지 않는다.
테스트 설계와 독립 리뷰를 구현 책임과 분리한다. 모델·Docker 담당은 활성화하지 않았다.

자유 메모와 구조화된 실험은 사용자 소유의 비공개 기록이다. RAG·파인튜닝은 기술 주제이며
자산운용 등 전문 도메인 라벨과 구분한다. 기록은 모델 실행이나 성공 여부를 생성하지 않는다.
공개 Publishing·캐릭터 연결·학습 데이터 선별·실제 비교 및 훈련은 후속 범위다.

## 확인된 구현

- 불변 기록 snapshot, note→experiment 전환, revision 충돌, 보관·복원 도메인.
- PostgreSQL 현재 기록·revision 테이블, owner 필터와 안정적인 keyset 목록,
  CAS UPDATE 및 revision INSERT의 원자적 저장, 0024 additive migration.
- 로그인 사용자별 API, 설정 기반 입력·페이지 한계, actor/filter에 귀속된 서명 cursor.
- 일반 참조 포트와 기술별 조립부 분리. 실제 RAG 평가 detail 권한 경로를 재사용한다.
- 현재·과거 읽기에서 참조 권한을 재검사하고 접근 불가 대상의 key·label·href를 비운다.
  편집용 draft의 해당 참조도 제외하되 저장 이력은 보존한다.

## 검증과 리뷰

| 범위 | 확인 결과 |
|---|---|
| 도메인 | 20건 통과, 독립 리뷰 승인 |
| DB 저장·migration | 격리 PostgreSQL 5건 통과, 리뷰 보강 후 12.77초 실행·승인 |
| Learning 단위·API·OpenAPI | 리뷰 수정 후 64건 통과 |
| 기존 인증·오류·RAG 평가 권한 | 16건 통과 |
| 백엔드 전체 Ruff | src/tests 통과 |
| 백엔드 전체 mypy | 최종 재실행 193개 소스 파일 통과 |
| 백엔드 전체 unit/contract | 최종 재실행 837건 통과, 기존 deprecation warning 1건 |
| OpenAPI 타입 생성·일치 | 통과, 기존 RAG domains 계약을 함께 보존 |
| UI 변경 전 기준선 | 타입 검사 및 내비게이션·경로 6건 통과 |
| 학습 화면 | 최종 수정 후 담당 범위 44건 통과·독립 재검토 승인 |
| Next.js build | 최종 수정 소스로 재실행 exit 0, 컴파일·타입·14페이지 생성·학습 목록/상세 경로 포함 |
| 평가 생성 시각 계약 | 집중 10건·Ruff·mypy 3개 파일·API 계약 통과·독립 승인 |
| API+DB lifecycle | 실제 격리 DB·FastAPI 1건 통과; 저장·migration 포함 최종 재실행 총 6건 통과(11.25초) |
| UI lifecycle | 실제 컴포넌트+HTTP mock 포함 최종 Learning·전체 navigation·routes 46건/12파일 통과(67.41초), exit 0; 실제 브라우저 E2E 아님 |
| 프론트 최종 정적 검사 | typecheck·전체 ESLint·api:check 모두 exit 0 |

DB 테스트는 정확한 UUID 이름과 `current_database()`를 검증한 임시 DB만 생성·회수했다.
개발 DB·사용자 기록을 reset/truncate하지 않았다. 사용자 DB는 읽기 전용 확인에서
`0023_rag_domains`였고 0024를 적용하지 않았다.

리뷰에서 발견한 문제와 조치:

1. DB 목록의 타인 fixture가 다른 필터에서 탈락해 owner 조건을 검증하지 못했다.
   동일 필터 타인 행을 추가하고 모든 페이지의 owner 교집합을 검사했다.
2. migration 검사가 FK·deferred pointer·positive check를 빠뜨렸다.
   PostgreSQL catalog에서 ordered columns·삭제 정책·deferred 상태·check 정의를 확인했다.
3. API 목록 기본 크기가 runtime 설정 대신 초기 상수를 사용했다.
   실패 테스트로 재현한 뒤 주입된 설정을 적용하고 default≤max를 검증했다.
4. 권한·보관·과거 중첩 참조·commit 순서의 명시 계약 테스트를 보강했다.
   과거 참조 테스트의 일부 metadata 부정 assertion이 무의미한 경미 항목은 실제 DB에서
   허용→권한 회수 후 현재·과거·중첩 참조의 UUID·제목·본문 비노출 검증으로 보완했다.
5. UI 독립 리뷰에서 본문 공백 계약, 충돌 재기준화, 늦은 이력 응답, 미저장 폐기, 구조화 비교,
   배열 입력 구분자, 빈 지표의 0 변환, 참조 링크와 평가 표시명 문제를 발견했다.
   원래 프론트 담당이 실패 테스트를 재현해 수정했다. 추가로 지표 행 삭제·최신 draft 동기화·저장 중
   이탈 보호를 재검토·보완했고 39건 GREEN 및 독립 승인을 받았다.
6. 평가 표시명은 기존 DB 생성 시각이 API에서 누락된 계약 한계였다. RAG 책임 검토와 ADR 보완 후
   persisted `created_at`만 additive 응답으로 전달하기로 했다. 검색·평가 기준·모델·DB 구조는 유지한다.
7. 통합 테스트 리뷰에서 보관·복원 참조 내용과 전환 확인창 호출의 직접 assertion이 빠진 점을 발견했다.
   검증 담당이 실제 safe metadata와 정확한 한국어 확인 문구를 검사하도록 보강했다.
   테스트만 수정했고 backend lifecycle 1건(4.57초), frontend lifecycle 1건(7.14초), 정적 검사가 통과했다.
8. 전체 최종 리뷰는 이력 보기 시 미저장 초안·이탈 보호 소실, 연속 이력·최신 비교의 오래된 필드,
   다른 탭 보관 후 저장 충돌에서 복원으로 진행하지 못하는 상태 전이 3건을 지적했다.
   원래 프론트 담당의 재현 테스트 4건이 RED→GREEN이었다. 이력 중 current editor는 mounted 상태로
   숨겨 초안을 보존하고, 읽기 전용 editor는 record/revision key로 갱신하며, 최신 보관 상태와
   사용자 초안을 분리해 복원 후 수동 저장까지 이어지도록 수정했다.
   상세 화면 18건, 담당 범위 44건과 타입·전체 lint·API 검사가 통과했다. root 최종 46건과
   Next build 재실행도 통과했고 독립 최종 재리뷰는 3건 모두 해결·새 Critical/Important 없음으로 승인했다.

## 아직 구분해서 남긴 결과

- 전체 백엔드 unit/contract 초기 기준선은 795건 통과, 기존 설정 테스트 1건 실패였다.
  기본값 테스트가 루트 `.env`를 읽는 원인을 설정 파일 제외 비교로 확인했다.
  실제 서버 설정은 변경하지 않고 해당 테스트의 dotenv·관련 환경 변수만 격리했다.
  재현한 실패 뒤 config 3건 및 전체 unit/contract 837건이 통과했다.
- 전체 기본 frontend Vitest 실행은 배너 이후 결과가 없어 해당 작업 세션만 중단했다.
  assertion 실패로 판정하지 않았다. 범위를 한정한 package test 스크립트의 threads pool 실행은
  통과했다. `pnpm ... exec vitest`는 현재 wrapper에서 인식되지 않았다.
- 기존 Starlette TestClient의 deprecation warning 1건은 이번 변경으로 생긴 오류가 아니다.
- 실제 브라우저 E2E, 개발 DB 반영, 모델 호출·OCR·훈련 검증을 위 결과에 포함하지 않는다.

## 적용 판단

코드의 로컬 활성화 검토 게이트는 통과했다. 다만 개발 DB는 아직 `0023_rag_domains`이며
학습 기록용 `0024_learning_records`를 적용하지 않았으므로 현재 화면에서 저장할 준비가
완료됐다고 안내하지 않는다. 적용 승인 후 로컬 실행서의 current→명시 upgrade→재확인 절차를
따르고 실제 로그인 브라우저에서 저장·새로고침·이력·보관·복원을 확인한다.
이후 기능 단계는 별도 승인·snapshot 기반 Publishing 2단계이며 모델 비교·훈련 실행은 별도다.
캐시·임시 기록 정리는 검증·정본 인계 후 CACHE_POLICY의 정확 경로 조사·승인 경계를 따른다.

## 구현 중 내린 결정과 영향

1. main·기존 변경을 유지하고 자동 커밋·새 worktree를 만들지 않았다. 대신 경로별 리뷰가 필요하다.
2. 도메인은 현재 불변 snapshot만 보유하고 이력은 저장소가 관리한다. 이력 보존은 DB 통합 검사로 확인했다.
3. 공통 스키마 오류 `validation_error`와 Learning 업무 오류 `learning_invalid_input`을 유지한다.
   클라이언트는 문서화된 두 422 범주를 처리해야 한다.
4. 접근 불가 참조는 응답 draft에서 제외하되 저장 이력은 유지한다. 확인 후 저장하면 연결이 빠지며,
   권한이 돌아와도 사용자가 다시 연결해야 한다.
5. 설정 가능한 초기 한계는 제목 200·본문 100000·기타 텍스트 20000자, 배열 100·참조 20,
   draft 262144 UTF-8 bytes, 페이지 기본 20·최대 100, cursor 4096이다. 큰 기록은 설정 조정이 필요할 수 있다.
6. RAG 평가 표시에는 실제 DB `created_at`을 응답에 추가했다. 알고리즘·DB 구조는 유지하되
   생성 타입과 합성 응답 fixture의 호환성 갱신이 필요했다.
7. 평가 시각은 생성 응답 계약·공통 mapper 검사와 실제 DB detail/list 검사로 나눠 확인했다.
   Task 5의 명시적 seeded-read 범위를 따르며 실제 `create_run`/`start_run` SQL 실행까지
   검증했다고 주장하지 않는다. 실제 평가 생성 통합 검증은 잔여 범위다.

## 이번 임시 산출물 조사

- 정확 경로: `C:\projects\ai-workshop\.local-data\project-agent-work\private-learning`
- 최종 재리뷰 후 조사: 24개 파일, 906473 bytes(약 0.86 MiB), 루트·하위 reparse point 없음.
- 상태: validating. 코드 검증·독립 리뷰·정본 인계는 완료됐지만 migration 적용 판단과 실제 화면 인계가 남았다.
- 잔여 절차 완료 후 정확 경로의 정리 승인을 받아 제거한다. 현재 삭제하지 않았으며,
  조사 이후 원장 마감이 추가되므로 삭제 직전에 파일 수·크기·사용 상태를 재확인한다.
- 보존: 제품 소스·회귀 테스트·정본 문서·사용자 DB·원본·모델·실행 서버와 `.next`.
- Docker와 공유 캐시는 이번 조사 범위가 아니다. 테스트 DB만 fixture의 exact 생성·삭제 절차로 회수했다.
