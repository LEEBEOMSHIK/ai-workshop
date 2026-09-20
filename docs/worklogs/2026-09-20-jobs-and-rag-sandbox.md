# Jobs 메타데이터 추적과 RAG sandbox 검증

- 날짜: 2026-09-20
- 요청: 다음 개발 진행 및 RAG 테스트 준비. 기존 커밋·푸시 인계 승인 유지.
- 범위: 일반 Jobs 소유권, 변경 revision, dispatch, 읽기 inventory와 격리 합성 RAG 환경.
- 역할: 메인 계약·통합·목록·문서, DBA 영속성/검색 계약, RAG 담당 실행 환경, 별도 독립 검토.
- 기존 checkout 사용 예외를 유지했다. 사용자 references와 기존 .env/자료/개발 DB는 보존한다.

## 구현

신규 Jobs에 source 보존 pin과 revision을 추가했다. repository의 생성·갱신은 현재 provenance와
같은 transaction이며 오래된 revision과 identity 변경은 거절한다. dispatch도 같은 경로를 쓴다.
legacy revision은 NULL로 남기며 RESTRICT pin을 추정 생성하지 않는다. inventory는 모든 버전과
owner/relation으로 발견한 작업을 대조하고 별도 snapshot 사이 변경을 검출한다. Jobs 종료 상태는
파일 writer의 종료 증명이 아니므로 writer_unconfirmed와 실제 삭제 비활성 경계를 유지한다.

기존 RAG ingestion fixture를 실제 artifact admission/publisher 계약에 맞춰 14건 통과시켰다.
게시 확정 전 실패는 예약과 원본 바이트를 보존하고 재시도에 임의 인수를 허용하지 않는다.
실제 선택 문서 검색에서 발견된 처리 프로파일 누락은 저장 구성의 의미상 ID와 물리 alias 이름을
분리해 수정했다. legacy/frozen alias와 선택 문서 권한 검증을 유지한다.

## 실행 검증

메인이 확인한 서로 다른 테스트 묶음:

- Jobs/assets/RAG ingestion 단위 488건 통과.
- Jobs·tracked upload·HTTP intake·temporary·RAG ingestion 격리 PostgreSQL 통합 37건 통과.
- 검색/retrieval/configurations/evaluation 및 sandbox 스크립트 단위 322건 통과.
- sandbox 안전성·출처 거절 23건을 마지막에 재확인했다(앞 묶음과 중복이므로 합산하지 않는다).
- 제품 Python 타입 9파일, sandbox strict 타입 2파일과 관련 Ruff 통과.
- 프로젝트 에이전트 계약 검사와 git diff 공백 검사 통과.
- 기존 Starlette/httpx 사용 중단 예고 경고가 있으며 테스트 실패는 아니다.

최종 스크립트 타입 명령은 backend cwd에서 MYPYPATH에 backend/src와 scripts를 지정하고
`python -m mypy --strict --explicit-package-bases ../scripts/prepare_rag_sandbox.py ../scripts/smoke_rag_sandbox.py`를 사용한다.
처음 root cwd에서 실행한 타입 검사는 모듈 경로 미설정으로 실패했으며 위 정식 경로로 통과했다.

## RAG 사용 준비

새 Compose project와 loopback 전용 포트, 새 DB/파일 root/marker만 사용했다.
DB는 0048이고 기존 cached 이미지·고정 E5를 offline으로 사용했다. 모델 다운로드나 외부 추론은 없다.
메인이 재사용 smoke를 직접 실행해 선택 문서 BM25와 E5 hybrid의 HTTP200, 정확한 문서·불변 버전·
Projection 출처, generation=not_requested를 확인했다. 기존 합성 문서를 재사용하므로 중복 업로드가 없다.
API/worker/beat/frontend와 세 인프라는 사용자가 테스트하도록 유지한다.

- 접속: http://127.0.0.1:5173/login
- 합성 로그인 정보: Git 제외 `.local-data/rag-sandbox/credentials.json`
- 실행 정본: [RAG sandbox](../runbooks/rag-sandbox.md)
- 재검증: `backend/.venv/Scripts/python.exe scripts/smoke_rag_sandbox.py`

검토에서 .env fallback과 기존 Docker project 인수 위험을 찾아 실행 전용 설정 격리와
기존 container/volume/network 거절을 보강했다. publishing API는 호출하지 않았고 그 public store도
생성하지 않았다. frontend의 API 대상은 sandbox로 고정했다. 기존 frontend 추적 파일의 생성 차이는 복원했다.

현재 카탈로그 retrieval YAML의 optional 필드와 extractive 검증 계약 불일치는 sandbox 전용
불변 profile에서 reranker disabled-only 설정으로 명시했다. 기존 profile이나 모델을 대체하지 않는다.
LLM 답변·인용 및 실제 OCR 품질 검증은 미완료다. 사용할 로컬 LLM endpoint/model 설정이 필요하다.

## 다음 경계

전체 참여자 inventory 조립, 구 writer/파일 writer 종료 증명과 잔존 재검증을 연결한다.
미활성 purge inventory 잠금 순서 검증 후 실제 삭제 API/UI가 필요하다. 이번에는 실사용 DB cutover,
legacy backfill, 물리 삭제와 삭제 활성화를 하지 않았다.

## 독립 검토와 인계

Jobs 기존 독립 검증·리뷰에 이어 sandbox 23+semantic DPP 5, 격리 ingestion 14건을
독립 검토자가 재실행했다(추가 42건 통과). 이전 두 환경 격리 차단을 해소했고 잔여 blocker는 없다.
현재 작업의 27개 파일만 커밋·푸시 대상으로 선별했다. credentials·cache·references는 제외한다.
별도 worktree는 없으며 사용자 테스트용 sandbox는 보존한다.
