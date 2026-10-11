# 검증 결과와 증거

문서 구조 검증과 사용자의 학습·실습 검증을 분리한다. 초기에는 모든 Day가 미시작이며 학습 통과 기록은 없다.

## 문서 구조 준비 — 2026-10-11

- 변경 범위: 이 폴더의 학습 Markdown 8개와 WORKBOARD 최소 참조. 코드·기존 설계·기존 worklog는 수정하지 않는다.
- 초기 git status 확인: 기존 미커밋/미추적 파일이 다수였으며 해시 보존 기준선 452개를 수집했다. 이후 검사는 해당 기준선과 이번 파일 목록을 대조한다.
- 역할: 메인 문서 작성/통합, 별도 독립 읽기 리뷰. 문서 구조 신호 selector의 결과는 design-adr-documentation-manager.
- 실행 도구 제한: 최초 시스템 Python의 역할 selector는 PyYAML 부재로 실패했다. 설치하지 않고 기존 backend 가상환경으로 같은 selector를 실행해 성공했다.
- 작성 중 WORKBOARD 줄바꿈 가정 검사가 한 번 실패했다. 당시 학습 파일 5개만 생성됐고 WORKBOARD는 쓰기 전에 중단됐다. 원래 LF와 사전 SHA 일치를 확인한 뒤 기존 바이트를 보존해 한 줄 참조를 추가했다.
- 날짜·내용·링크·diff·기존 파일 보존·독립 검토 결과는 아래 최종 검사 기록에 남긴다.

## 최종 검사 기록

다음은 이번 작업에서 실제 실행한 문서 검사다. 아래 수치는 학습 성적이나 제품 테스트 수가 아니다.

| 검사 | 실행 방법 | 확인 결과 |
|---|---|---|
| 역할 선택 | 기존 `backend/.venv/Scripts/python.exe scripts/verify_project_agent_contracts.py select --root . --signal design-adr-or-document-structure` | 문서 관리자 역할 선택, exit 0 |
| 날짜·순서·내용 | 표준 라이브러리 Python으로 Markdown heading/필드 파싱·date/timedelta 대조 | 84일, 12주 각 7일, 2026-10-12~2027-01-03 연속, 672필드, 다음 Day 연결83개 |
| 진도 분리 | 커리큘럼 날짜·제목과 progress 행 대조 | 84행 모두 미시작·미평가, 읽기 미실행/실행 미승인 |
| 로컬 참조 | 각 문서 기준 상대 경로를 resolve 후 exists 검사 | 로컬 링크253개 모두 존재 |
| 새 파일 품질 | 새 Markdown8개 UTF-8 읽기, trailing whitespace 검사; 독립 conflict marker 검사 | 통과 |
| 기존 파일 보존 | 초기 452개 SHA-256 중 WORKBOARD 제외451개 재계산 | 전부 동일 |
| WORKBOARD 보존 | 이번 추가한 빈 줄/참조 줄을 메모리에서 제외한 원문 SHA 대조 | 원래 본문 바이트 동일, 최근 완료5개 그대로 유지 |
| Git 변경 범위 | 초기/종료 porcelain 경로·상태 비교 | 기존 상태 유지, 새 파일은 학습 Markdown8개만, 예상 밖 신규0 |
| diff 공백 | `git diff --check -- WORKBOARD.md docs/learning` | exit 0; Git의 LF→CRLF 안내 경고만, 자동 줄바꿈 변환은 하지 않음 |
| 독립 문서 검토 | 별도 읽기 전용 검토자의 전체 내용·날짜·경로·범위 검사 | 차단 없음. REGISTRY 경로, Day73 분기, Q004 날짜 연결, 끝 문장 마침표 권고 반영 |

해시 기준선/작성 보조/검사기는 Windows Temp의 `ai-workshop-learning-84-*`에 두고 제품 코드는 import하지 않았다. 실행한 검사 명령은 `python "$env:TEMP/ai-workshop-learning-84-verify.py"`이며 결과는 같은 위치의 validation JSON에 보존했다. 검사기 개발 중 최근 완료의 번호 목록을 처음에는 bullet만 세어 0으로 표시한 오류를 발견했다. 번호 목록도 세도록 고친 뒤 실제 5개와 원문 보존을 다시 확인했다. 이 준비 문서만 검증한 것으로 전체 저장소 테스트를 통과했다고 보고하지 않는다.

외부 공식 개요 페이지11개는 접근·읽기 확인만 했다. 모든 외부 문서의 하위 링크·API·현재 장치 호환성을 검증한 것은 아니다. .agents/skills 경로는 이 작업 공간에 없어 추가 로컬 스킬을 읽지 않았다.

## 학습 검증 원장

아직 실제 학습 검증 없음. 결과를 미리 성공으로 채우지 않는다.

| V-ID | 실제 날짜(KST) | Day/Q-ID | 종류 | 기대 결과 | 관찰/증거 | 판정 | 제한·다음 조치 |
|---|---|---|---|---|---|---|---|
| — | — | — | 미실행 | — | — | 미실행 | Day01 진단부터 기록 |

종류는 재설명 / 흐름 재현 / 손계산 / 새 사례 적용 / 승인 실행 실습 / 제품 검증으로 구분한다. 판정은 통과·실패·부분·미실행·차단이며 실행 실습의 성공을 제품 완료로 확대하지 않는다. V-ID를 일일 기록과 progress 행, 필요한 Q-ID에 연결한다. 보충 후 재검증은 새 행을 추가하며 이전 실패를 삭제하지 않는다.

## 실행하지 않은 항목

제품 단위·통합·E2E 테스트, Python/TypeScript 타입 검사·lint, 모델 실행, SDK/라이브러리 설치, migration, DB/ES/Redis/Docker 상태 조회·변경, 서버 재시작, 계정/환경 생성, git staging/commit/push, 외부 예약 변경은 수행하지 않았다. 과거 개발 worklog의 성공은 이번 실행 성공이 아니다.
