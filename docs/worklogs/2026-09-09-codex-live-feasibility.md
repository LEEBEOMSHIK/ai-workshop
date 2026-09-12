# Codex 실제 합성 연결 검사와 사용자 테스트 선행 조건

## 목적과 승인 범위

사용자는 중간 내부 계층이 아닌 실제 대화형 RAG를 테스트할 수 있을 때까지 작업을 요청했다.
이미 승인된 개인 owner용 제한 실행과 gpt-5.5·합성 입력 전송·계정 사용량 범위에서
설치 CLI의 실제 호환성을 먼저 조사했다. RAG/AI/아키텍처 담당이 연결 공백을 조사하고,
독립 보안/privacy 담당이 설계 및 진단 스크립트의 경계를 검토했다.

앱의 승인 gate를 우회하여 사용자 검색을 실행한 것이 아니다. 별도로 명시 승인된 합성
진단이며, 코드의 UUID는 DB에 저장되지 않는 상관 라벨이다. 실제 사용자 권한/승인 레코드나
준비 상태를 위조하지 않았다. 사용자 DB·도메인·프로파일·설정·인증·UI는 변경하지 않았다.

## 측정 방법

- 실제 설치 파일의 `--version`: codex-cli 0.153.4.
- 기존 runner registry·명령 조립·workspace·strict stream·Windows Job 계층 재사용.
- 관련 오프라인 검사: 175 passed (7.93초).
- 요청 모델: 명시 gpt-5.5. 모델명은 진단 명령 인자로만 전달하며 업무 코드에 고정하지 않았다.
- 입력: 합성 테스트 펀드 수수료 질문 한 문장, 빈 이력·빈 근거, 저장소의 신뢰된 서비스 지침.
- 각 실행 45초 제한, read-only/ephemeral/strict config/기존 비활성 설정 유지.
- 원시 stdout/stderr는 제한된 메모리에서만 검사 후 폐기. 본문·추론·인증을 저장하거나 표시하지 않았다.
- 오류 분류는 고정 marker, 이벤트 종류, 숫자 사용량, schema 통과 여부만 보고했다.
- 임시 진단 스크립트는 `.local-data/project-agent-work/codex-live-feasibility/probe.py`이며
  제품 실행기·공개 API·준비 상태 근거 전체를 대신하지 않는다.

## 실행 결과

1. 최초 제한 환경의 답변 요청은 네트워크 오류로 실패했다. 도구 권한 검토 후 같은 제한
   설정으로 검사했으며 CLI의 sandbox/관리 정책은 해제하지 않았다.
2. 답변 요청은 CLI 오류를 반환했다. 원시 로그 비저장 때문에 오류 분류를 stdout에도 적용한
   명시 진단에서 `schema_rejected`를 확인했다. 현재 답변용 정본 JSON schema의 호환성 보완이 필요하다.
   원문 오류를 보존하지 않았으므로 특정 keyword만 유일한 원인이라고 단정하지 않는다.
3. 기존 단순 contextualization schema로 요청하면 실제 agent 응답과 turn.completed가 도착했다.
   첫 진단은 사용량 계약에서 거절됐고, 메타데이터만 수집한 후속 진단에서도 재현됐다.
   이벤트 순서는 thread.started → turn.started → item.completed → turn.completed였다.
4. 최종 진단의 합성 응답은 기존 `parse_contextualization_v1`을 통과했다. 사용량은 input=8564,
   cached=0, output=65, reasoning_output=43이었다. 현재 수신기 허용 목록 외 usage 필드 1개가 있어
   `invalid_usage`로 답변을 폐기했다. 그 필드명/값은 수집하지 않아 추가 계약 확인이 필요하다.
5. 이번 결과에서 실제 응답 모델 ID는 확인하지 못했다. 최상위 model/model_id/observed_model
   필드는 감지되지 않았지만, 모든 중첩 필드·다른 공식 증거의 부재까지 입증한 것은 아니다.
   요청 모델 gpt-5.5를 관측 모델로 복사하지 않았다.

모두 요청 소유 프로세스 회수 및 workspace cleanup_verified=True였다. strict observer가 오류
이벤트에서 중단하므로 exit_code=None을 정상 CLI exit 0으로 기록하지 않는다. 합성 후속 질문
JSON이 파싱됐다는 사실도 전체 실행 검증 또는 RAG 답변 성공을 뜻하지 않는다.

## 사용자 승인과 호환성 수정 후 재검증

2026-09-09 사용자가 개인 개발용 Codex의 관측 모델 미확인 예외를 승인했다.
요청/관측 모델은 분리하고 다른 Provider 및 나머지 검증은 유지한다.
새 `rag-codex-answer-v3`와 `codex-grounded-wire-v1`을 추가해 기존 semantic v2로
엄격 변환한다. 실제 추가 usage 필드는 `cache_write_input_tokens`였으며 해당 필드만 수용한다.

- 독립 코드 리뷰 승인. main 재검증 188 passed (1.36초), mypy 5개 파일·Ruff 통과.
- 실제 근거 없는 합성 질문: `insufficient_evidence`, input=7968/output=40.
- 실제 합성 근거 한 문장(연 수수료 0.25%): `answered`, 인용 validator `answered`,
  input=8015/output=69. 출처 UUID와 provenance는 진단용 합성 값이며 DB/원문 뷰어 검증이 아니다.
- 실제 합성 질의 재작성: 기존 contextualization parser 통과, input=7696/output=55.
  이번 입력 이력은 비어 있어 실제 대화 후속 문맥 검증을 대신하지 않는다.
- 세 실행 모두 strict event stream 통과, CLI exit=0, stderr=0, cleanup_verified=True.
  `cache_write_input_tokens`는 세 실행 모두 정수 0이었다. 관측 모델은 계속 None이다.
- 실제 본문/원시 이벤트/추론은 저장하지 않았다. 사용자 DB/설정/준비 상태는 변경하지 않았다.

## 후속 구현

관측 모델 예외와 CLI schema/usage 호환성은 해결했다. 승인과 runner 지문 결합,
프로세스 간 동시 실행 제한·취소, runtime/API/관리자 설정 배선, 실제 사용자 DB의 정확한
migration 범위 확인 및 자산운용 Hybrid/생성/도메인 연결·평가를 이어간다.
최종 답변·인용/하이라이트·후속 질문·근거 부족·실패 안내를 실제 화면에서 검증한 뒤에만
사용자에게 전체 테스트를 요청한다.

## 근거와 보존

- [공식 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode): JSONL·사용량·schema·저장 CLI 인증 사용.
  예시에 모델 필드가 없다는 사실과 설치 버전의 실측은 구분한다.
- [승인 설계](../superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md) §7·10.
- 요청 전용 임시 루트는 Windows Temp의 `ai-workshop-codex-feasibility-d05c676fd7fb4a28b83ebd350054441c`이다.
  요청 child/schema는 기존 소유권 정리 계약으로 제거됐으며, 빈 루트와 최소 진단 스크립트는
  후속 정확 경로 정리 대상 확인 전 보존한다. 전역 캐시·기존 사용자 파일은 제거하지 않았다.
