# Claude 연결과 고급 관리 화면 정리

- 날짜: 2026-10-31
- 관련 문제: [ISSUE-00046](http://127.0.0.1:5173/admin/system/issues?offset=0&issue=a884a457-f700-4772-935e-235d0a804dcd)
- 설계: [ADR-0053](../decisions/0053-claude-and-admin-workflows.md), [구현 계획](../superpowers/plans/2026-10-31-claude-admin-workflows.md)
- 이전 작업: [관리자 모델 연결·RAG 설정 통합](2026-10-30-admin-model-setup.md)

## 결과와 수용 범위

통합 설정에서 Claude를 신규 후보로 등록할 수 있는 native Anthropic API 경로를 추가했다. 고급 RAG 모델·구성 화면은 작업을 먼저 선택하고 상세를 펼치는 구조로 정리했다. 본래 API와 기존 관리자 화면에 반영했으며 기존 DB 행·환경·정책 승인·활성 연결과 생성형 수용 기준은 보존했다.

Claude의 서버 연결·인증 참조는 아직 준비되지 않았다. 실제 Claude 등록·유료 생성·답변 품질 평가·기본 연결 적용은 수행하지 않았다. 이번 모델 호출과 추가 API 비용은 0이며, 아래 mock 회귀 결과를 Claude 실제 답변 품질 통과로 해석하지 않는다.

## 사용 경로

| 목적 | 진입과 변경 |
| --- | --- |
| 일반 모델 연결·변경 | [모델 연결·RAG 설정](http://127.0.0.1:5173/admin/rag/setup) → 새 연결 등록 → 로컬·사내 / OpenAI / Claude·Anthropic 선택. 기존 구성 복사·연결/답변 평가·정확한 후보 적용 흐름 재사용 |
| 세부 모델 관리 | [RAG 모델·고급](http://127.0.0.1:5173/admin/rag/models) → 등록 현황 / 모델 연결 / 처리 설정 / 데이터 정책. 모델 정의·실행 배포·프로파일 등록을 작업별로 분리 |
| 구성 확인·신규 설계 | [RAG 구성·고급](http://127.0.0.1:5173/admin/rag/configurations) → 저장 구성 확인 / 새 구성 만들기. 구성 이름·지식 공간과 문서→색인→검색→답변 순서를 먼저 표시 |

기존 두 고급 메뉴와 URL을 유지한다. 모델·프로파일·배포 목록, JSON/YAML, 평가와 비교의 접근을 제거하지 않았다. 처음 연결하는 사용자는 통합 설정으로 안내하며 고급 화면의 업무 규칙과 저장 handler는 그대로 사용한다.

## 공급자 구현

- `anthropic_messages` 공급자와 `anthropic` endpoint dialect, native Messages adapter를 추가했다. 외부 위치·secret 참조·별도 처리 고지와 설치/공간 정책 승인을 요구한다. 기존 OpenAI 승인이 Anthropic을 승인하지 않는다.
- 서버 reference map에서 URL과 workspace 범위 키를 해석하고 브라우저에는 참조 이름만 반환한다. 기존 키를 이동하거나 환경 파일에 추가하지 않았다. 초기 지원은 직접 Anthropic API이며 Bedrock·Vertex·organization 범위 키는 포함하지 않는다.
- API version `2026-10-21`, `/v1/messages`, top-level system/messages와 구조화 출력 계약을 사용한다. 기존 schema1 prompt/parser와 답변·인용 검증을 재사용한다. Claude는 명시한 `provider_default`와 temperature1 메타데이터를 요구하며 wire에는 sampling 파라미터를 보내지 않는다.
- 전용 `grounded-anthropic-schema1-v1` 프리셋을 후보로 제공한다. SDK 위임·로컬 전용 옵션·미지원 키를 자동 삭제하거나 변환하지 않고 등록/readiness/runtime에서 거절한다. 기존 모델 프로파일은 수정하지 않는다.
- 정확한 모델 ID, 종료 상태, 텍스트 JSON과 필수 사용량을 확인한다. refusal·truncation·tool·알 수 없는 block은 실패로 처리한다. thinking/redacted thinking은 답변·실행 결과·오류 본문에 보존하지 않는다.
- 캐시 생성/읽기를 포함한 입력 토큰과 출력 토큰을 기록하며 미측정 내부 시간·비용을 임의 0으로 만들지 않는다. HTTP/디코더 오류에는 공급자 응답·키·비공개 본문을 노출하지 않는다.
- 독립 검증에서 발견한 잘못된 block discriminator의 TypeError와 JSON decoder RecursionError를 안전한 경계 오류로 바꾸고 영구 회귀 검사를 추가했다.

## 선택과 화면

Claude 공개 카탈로그는 공식 확인일 2026-10-31, 공개일 최신순 4개다. 빈 초기 선택, 정확한 ID·날짜·공식 출처·직접 입력·계정 접근 미확인 표시를 제공한다. 모델/공급자/입력 방식 변경 시 이전 ID·정의·기능 확인을 초기화한다. 별도 보관 조건은 선택 아래 표시한다. 이 순서는 성능 추천이나 계정별 사용 가능성 보장이 아니다.

통합 폼은 서버 참조가 없으면 등록을 막는다. 고급 HTTP 폼에서도 공급자를 구분하며 기존 OpenAI 고급 등록의 schema2 기본 선택을 schema1로 수정했다. 기존 OpenAI 런타임의 sampling 호환성 문제 ISSUE-00047은 이 변경으로 해결했다고 보지 않는다.

RAG 모델의 첫 화면에는 세 가지 작업 카드와 접힌 등록 현황을 둔다. 모델 연결에서 정의 등록·배포 등록·등록 배포 확인 중 하나를 표시하고 처리 설정도 등록/생성/원문 입력을 분리한다. RAG 구성 카드에는 이름·버전·모델·준비 상태를 먼저 두고 내부 식별자와 전체 파이프라인은 펼침에 둔다.

작업·탭 이동에는 폼을 숨긴 채 유지해 미저장 입력을 보존한다. 구성 builder는 첫 진입 때 만들고 이후 탭 이동에 재생성하지 않는다. 탭의 방향키·Home/End·선택 상태·포커스를 유지하고 안내 카드에서 작업을 열면 해당 탭에 초점을 옮긴다. 이동 자체로 등록·연결 검사·추론·정책 승인·적용을 실행하지 않는다.

## 검증

다음 수치는 실행 범위가 중복되므로 합산한 고유 테스트 수로 보고하지 않는다. 단위/통합 컴포넌트 검사는 합성 입력과 mock transport/fetch를 사용했다.

| 범위 | 결과 |
| --- | --- |
| 서버 최종 관련 회귀 | 558개 통과, 37.43초. native·등록·readiness·offline migration·기존 OpenAI/local·프로파일·정책 포함 |
| 서버 정적 검사 | 17개 소스 strict Mypy 통과, 변경 소스·migration·6개 테스트 Ruff 통과 |
| 독립 서버 검증 | 관련 189개 통과. 추가 디코더 경계 RED 확인 뒤 최종 native/독립 62개 통과 |
| 프론트 통합 검증 | root 관련 132개 통과, 독립 공급자/후보/정책/적용 등 139개 통과 |
| 고급 관리 구조 | 구현 담당 44개 통과, 독립 구조·초안·엄격 후보 52개 통과 |
| 프론트 정적 검사 | 전체 TypeScript·변경 ESLint 통과, OpenAPI 생성 완료 |
| 기존 파일 보존 | 독립 검사에서 .env·기존 OpenAI/local/schema1 관련 5개 파일 SHA 동일 |

독립 검토의 해결된 발견, 실제 명령과 로그는 로컬 작업 증거 `claude-admin-20261031/independent/review.md`에 있다. 외부 모델 호출이나 DB를 쓰지 않은 독립 검증을 본래 DB/화면 검증과 구분한다.

### 본래 DB와 API

이력 쓰기 전 원래 환경의 124개 표·162,091행을 읽기 전용 해시로 비교했다. migration0068 추가와 되돌리기를 단일 트랜잭션에서 수행한 뒤 모두 롤백하여 제약 복원·전체 행 보존을 확인했다. 실제 적용은 리허설과 migration SHA를 묶고 잠금/문장 시간 제한을 둔 연결에서 수행했다.

- `0067_stored_model_comparisons` → `0068_anthropic_messages` 적용 완료.
- migration SHA-256: `1db3d3b32768ef4d98d18f021020cb997041134aa8c9f078f4a737720b701ec7`.
- 공급자·실행 참조·정책의 네 제약 확장과 신규 공급자 계약만 추가했다. 기존 행 DML 없음. downgrade는 Claude 참조가 생기면 거절한다.
- 실제 API 프로세스/포트/실행 파일을 확인하고 API만 재기동했다. frontend·worker·Ollama 설정은 유지했다.
- `/api/v1/health=ok`, `/api/v1/ready=ready`, 실제 OpenAPI에 `anthropic_messages` 포함 확인.
- 최종 DB 비교 `changed_tables=[]`, 124표162,091행 동일. 환경 파일·기존 수용 기준 해시 동일.
- 그 뒤 ISSUE-00046의 후속 진행 이력과 수정/남은 작업을 정상 관리자 UI로 저장하고 새로고침으로 재조회했다. 이 기록 쓰기 이후까지 모든 DB 행이 불변이라고 주장하지 않는다.

### 본래 브라우저

기존 관리자 계정과 기존 자료를 사용했다. 별도 DB·사용자·환경을 만들지 않았다.

- Claude 선택의 빈 초기값·모델 4개·정확한 Sonnet ID·Anthropic 고지와 서버 참조 미설정 시 등록 차단 확인. 실제 등록/연결 검사/생성 없음.
- 구성 초안에 합성 이름을 입력한 후 비교 실험→RAG 구성→저장 구성 확인→새 구성 만들기 왕복에서 동일 값 확인. 검증 후 입력을 비웠다.
- 모델 정의 초안을 입력한 뒤 실행 배포 작업→처리 설정 탭→모델 연결 탭→정의 등록 왕복에서 동일 값 확인. 검증 후 입력을 비웠다.
- 실제 Chrome viewport 320/375px에서 모델/구성 화면의 관측 범위 가로 넘침0. 구성 선택 입력 약45.39px, 모델 탭 약46.39px. 방향키 선택·2px 초점과 안내 카드의 탭 초점 이동 확인.
- viewport를 원래 크기로 복원했다. 실제 모바일 기기와 전체 업무의 모든 상태 E2E는 미검증이다.
- 오래된 탭의 CDP 시간 초과는 같은 Chrome의 새 탭에서 기존 로그인으로 복구했으며 별도 계정으로 대체하지 않았다.

## 기록과 남은 운영 작업

[디자인 정본](../guidelines/ui-style-guide.md#고급-관리의-작업-선택), [적용 현황](../guidelines/design-system-coverage.md#2026-10-31-claude와-고급-관리-화면), [연결 실행서](../runbooks/local-development.md#claude-직접-api-연결)를 갱신했다. ISSUE-00046에 이번 날짜의 검증과 한계를 저장·재조회했다. 기존 이력·상태와 별도 ISSUE-00047을 유지했다.

다음 운영 단계는 승인된 Claude workspace 키/서버 참조와 해당 공급자 정책을 준비하고, 공개 승인 자료로 새 후보의 답변·인용 품질·사용량을 평가하는 것이다. 통과한 정확한 버전만 명시 적용한다. 모델 목록 표시나 연결 검사만으로 기본 모델을 바꾸지 않는다. Claude SDK 자율 위임·모든 문서/질문 품질·실제 비용 청구 대조는 이 작업의 완료 범위가 아니다.

로컬 증거 위치: `.local-data/project-agent-work/claude-admin-20261031/`. `database-verification.json`, `migration-rehearsal.json`, `migration-receipt.json`, `runtime-receipt.json`, `issue46-readback.txt`, 테스트/정적 검사 로그와 `models-overview-desktop.png`, `models-320.png`, `configuration-320.png`를 보존한다. 비밀값과 원문 본문은 기록하지 않는다. 커밋/푸시·캐시 삭제는 하지 않았다.

## 공식 확인 출처

2026-10-31에 [공식 모델](https://platform.claude.com/docs/en/models/overview)과 [릴리스 노트](https://platform.claude.com/docs/en/release-notes/overview)에서 카탈로그와 공개일을 확인했다. [Messages API](https://platform.claude.com/docs/en/api/messages/create), [2026-10-21 API 변경](https://platform.claude.com/docs/en/api/migration-2026-10-21), [구조화 출력](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [workspace 인증](https://platform.claude.com/docs/en/manage-claude/authentication#select-a-workspace)을 native 계약과 대조했다. 자세한 독립 대조는 `independent/source-audit.md`에 있다.
