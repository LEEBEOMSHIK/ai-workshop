# 기존 RAG 변경과 실패 진단의 공개 main 통합 — 2026-09-30

사용자는 공개 저장소와 대상 main 안내를 받은 뒤 기존 변경도 내용을 확인해 커밋·푸시하도록 범위를 확장했다. 대상은 기존 `https://github.com/LEEBEOMSHIK/ai-workshop.git`의 `main`이다. 기본 브랜치 설정 변경은 별도 확인 대상이므로 수행하지 않는다. force push·브랜치 삭제·보호 해제·배포도 수행하지 않는다.

## 공개 전 대상 재확인

- 로컬 main의 추적 브랜치는 origin/main이다. origin fetch/push URL은 승인된 주소와 같고 별도 upstream 원격은 없다.
- 확인 당시 로컬 HEAD·추적 참조·실제 원격 main 모두 `6e5ed288070c0a8ab036c83055ca55152514a20a`이며 staging은 비어 있었다.
- GitHub 공개 API에서 소유자 LEEBEOMSHIK·public·main protected=false·main 적용 규칙 0개를 재확인했다. 기본 브랜치는 feature/rag-ai-search-first-slice였다.
- GitHub CLI 메타데이터 인증의 HTTP401과 Git push 인증은 별개다. 새 인증정보를 만들거나 설정하지 않고 기존 Git 인증으로 일반 push를 수행할 범위다.

## 포함할 기존 변경과 용도

- `generation/codex_command.py`와 회귀: 검증된 CLI 0.158.0 정확 버전만 호환 목록에 추가한다. 인접 버전·beta 거부, 실행 파일 해시·Origin·요청 정책을 유지한다.
- `configurations/generative-api.ts`와 회귀: 평가 재시도 mutation에 JSON 빈 객체를 전달해 application/json 계약을 충족한다. 기존 승인 헤더·credentials를 유지한다.
- 비교 UI와 CSS/회귀: 질문 상태·반복 선택 컨트롤, 질문 5행·페이지 이동·키보드 탭·URL 복원과 단순화한 상태 표시를 유지한다.
- 모니터링 UI와 CSS/회귀: 공통 스타일·상태별 표시·접힌 사용 안내·필요할 때 여는 상세 진단을 반영한다.
- `evaluation/generative_monitoring.py`와 회귀: 요청별 run 묶음 읽기로 같은 평가 전체 결과의 반복 조회를 줄인다. 현재 소유권/원문 권한 재검증과 attempt/execution ID 대조를 유지하고 요청간 캐시는 만들지 않는다.
- 직전 두 작업: 인용 실패 안전 사유·종료된 실패 단계 보존, 선택 완료 후 실패의 정확한 근거 ID·검색/문맥 지표 보존과 지표별 화면 표시를 포함한다.
- WORKBOARD와 날짜별 기록: 사용자 기존 실행/검증 기록 및 실제 품질 미완료 경계를 보존한다. 과거 사용자 실검증 기록을 이번 새 검증으로 재표현하지 않는다.

## 제외와 개인정보 검토

`references/images/img.png`는 현재 코드에서 참조하지 않는 로컬 UI 참고 캡처라 제외하며 삭제하지 않는다. `.env`, 원본 문서·DB dump·브라우저 캡처·캐시·임시 테스트 산출물은 추가하지 않는다.

승인된 변경 30개 파일을 경로별로 검토했다. 비밀값 패턴은 값 출력 없이 검사했고 독립 리뷰에서 인증정보·비공개 문서 본문·새 라이선스 차단 항목을 찾지 못했다. 신규 인용/측정값 worklog의 로컬 계정명이 포함된 경로는 공개 전에 비식별화했고 실제 로그는 로컬에 보존했다.

## 검증 증거

| 검사 | 결과 |
| --- | --- |
| 이번 공개 전 직접 회귀 | Codex 명령·monitoring·직전 두 회귀, 131 passed in 4.73s |
| 이번 Python lint | 변경 소스 6개·테스트 4개 Ruff 통과 |
| 이번 Python 타입 | 변경 소스 6개 Mypy 오류 없음 |
| 이번 프론트 정적 검사 | 전체 TypeScript와 변경 TS/TSX 10개 ESLint 통과 |
| 앞서 같은 구현의 전체 백엔드 단위 | 2977 passed, 6 skipped, 1 warning in 79.74s. 이후 제품 코드는 수정하지 않음 |
| 앞서 같은 구현의 관련 프론트 | configurations·executions 13파일·112 통과, 80.92초 |
| 독립 기능·개인정보 리뷰 | 코드 차단/중요 항목 없음. 로컬 계정 경로 비식별화 보완 완료 후 공개 차단 해소 |

무거운 검사는 순차 실행했다. 새 외부 LLM·실제 DB·브라우저 검증·설치·설정 변경은 이번 통합에서 수행하지 않았다. 기존 TestClient 경고 1개와 6개 skipped는 통과 건수에 넣지 않는다.

## 반영 경계와 다음 작업

이 문서는 커밋 전 검증 기록이다. 실제 commit SHA와 origin/main 반영 여부는 일반 push 후 원격 refs 조회로 확인하고 최종 보고와 다음 작업 기록에 남긴다. 미확인 상태에서 push 완료를 기록하지 않는다.

다음 한 작업은 근거 부족/거절 상태 계약이다. 실제 API/worker 반영·DB/브라우저·문제 DB 문서 연결, 기존 실패 backfill, 비교 결론 누락과 모델 품질 검증은 별도 미완료이다.
