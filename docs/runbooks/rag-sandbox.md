# 합성 RAG sandbox

실사용 `.env`, DB, 업로드 데이터와 기존 Docker 서비스를 바꾸지 않는 Windows 전용 검증 환경이다.
현재 원본/임시/RAG 산출물 쓰기는 Windows native adapter를 요구하므로 Docker에는 PostgreSQL,
Redis, Elasticsearch만 두고 API, worker, beat와 frontend는 호스트에서 실행한다.

## 범위와 보존

- Compose project: `ai-workshop-rag-sandbox`
- 전용 root: 저장소의 `.local-data/rag-sandbox/` (Git 제외)
- PostgreSQL: `127.0.0.1:55474`, DB `ai_workshop_rag_sandbox`, 사용자 `rag_sandbox`
- Redis: `127.0.0.1:16379/0`; Elasticsearch: `127.0.0.1:19200`
- API: `http://127.0.0.1:18000`; frontend: `http://127.0.0.1:5173`
- 모델: 기존 `.local-data/models`의 고정 E5 snapshot만 offline으로 읽는다.
- 실제 사용자 자료, 외부 LLM/Codex, 모델 다운로드와 기존 cache 정리는 범위 밖이다.

`environment.json`, `compose.env`, `credentials.json`에는 합성 환경의 비밀값이 있으므로 내용을
로그·Git·채팅에 출력하지 않는다. 로그인 정보는 사용자가 로컬 `credentials.json`에서 확인한다.
포트가 이미 사용 중이면 해당 프로세스를 중지하거나 우회하지 않고 준비를 중단한다.
이 환경의 root, DB와 volume은 테스트 이후에도 유지한다. reset/삭제 기능은 제공하지 않는다.

## 최초 준비

저장소 루트에서 실행한다. `Prepare`는 root가 이미 있으면 인수하지 않고 거절한다.
세 Docker image (`postgres:17-alpine`, `redis:8-alpine`, Elasticsearch `9.5.2`)가 이미 있어야 한다.
이미지를 pull하거나 build하지 않는다.

```powershell
.\scripts\prepare_rag_sandbox.ps1 -Phase Prepare
.\scripts\prepare_rag_sandbox.ps1 -Phase Infrastructure
.\scripts\prepare_rag_sandbox.ps1 -Phase Migrate
.\scripts\prepare_rag_sandbox.ps1 -Phase Runtime
```

`Infrastructure`는 sandbox의 정확한 Compose project만 시작하고 healthy를 기다린다.
실제 Elasticsearch `cluster_uuid`를 읽어 저장하며 기존 값과 다르면 자동 인수하지 않는다.
`Migrate`는 sandbox DB에만 `upgrade head`와 `register-rag-models`를 적용한다.
새 migration을 적용하기 전에는 이 sandbox의 writer 종료와 코드 버전 일치를 확인한다.
실사용 DB cutover는 [로컬 개발 실행서](local-development.md)의 별도 절차를 따른다.

`Runtime`은 `Start-Process -WindowStyle Hidden`으로 실행하며 wrapper PID를 `processes.json`에,
로그를 `logs/`에 남긴다. 기록된 프로세스가 살아 있으면 중복 실행하지 않는다.
frontend를 별도로 실행 중이면 `-WithoutFrontend`를 사용한다. 기존 frontend를 중지하지 않는다.

환경은 고정된 sandbox DB·root·loopback 주소를 검증하면서 `AI_WORKSHOP_ENVIRONMENT=local`을
쓴다. `test`는 Celery의 eager 실행을 강제하므로 실제 Redis→worker 전달 검증에 사용하지 않는다.
격리 DB를 별도 단위/통합 테스트에 활용할 때만 테스트 프로세스에서 `test`로 지정한다.
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`이 모델 다운로드를 차단한다.

## 저장소 소유권

`objects/`의 `.ai-workshop-original-store.json`과 `.ai-workshop-store.json`,
별도 `temporary/`의 `.ai-workshop-temporary-store.json`을 각각 새 machine identifier와
UUID로 생성한다. marker에는 `schema_version=1`, `store_id`, `binding_id`만 둔다.
기존 `.local-data/objects`나 임시 파일을 인수하지 않는다.

## 검증과 제한

먼저 `/api/v1/health`, 세 인프라 health, 현재 DB revision을 확인한다.
최초 `/api/v1/setup/owner`로 합성 owner를 생성한 뒤 합성 TXT를 업로드한다.
검증 Job `succeeded/ready`, RAG Projection 및 Build `ready`, BM25 결과의 정확한 문서/버전
출처를 확인한다. 이후 cached E5를 사용하는 별도 실험 구성으로 hybrid 검색을 비교한다.
실험 구성을 일반 검색 기본값으로 승격하거나 LLM 답변 준비 완료로 표시하지 않는다.

기존 `scripts/smoke.ps1`은 Linux application container와 broad E2E reset을 사용하므로 이 환경에
실행하지 않는다. 기존 `test_e5_smoke.py`의 `local_files_only=False` 호출도 offline 환경 없이
실행하지 않는다. ingestion 구형 fixture의 `artifact_binding_missing`는 환경 설정만으로 해결되지
않으며 명시적 artifact admission/publisher 인계가 필요하다.

## 검색 smoke 실행

준비된 환경에서 다음 명령은 저장된 합성 owner로 로그인하고, 처음 한 번만 공개 합성 TXT를
업로드한다. 이후 실행은 `smoke-state.json`의 같은 문서를 재사용한다.

```powershell
backend\.venv\Scripts\python.exe scripts\smoke_rag_sandbox.py
```

명령은 BM25와 `Sandbox E5 hybrid` 실험 구성을 각각 `document_ids`로 제한하여 검색하고,
답변 출처와 selected scope의 문서·Asset Version·Projection 일치 및 `generation=not_requested`를
검사한다. stdout에는 상태만, `smoke-state.json`에는 opaque ID와 안전한 결과만 남긴다.
E5의 최초 로드와 CPU 추론에는 시간이 걸릴 수 있다. 다른 모델이나 외부 서비스로 전환하지 않는다.

hybrid용 retrieval profile은 카탈로그의 RRF 설정을 사용하되 이 제품의 extractive 계약에 맞춰
`reranker: {enabled: false}`로 명시한다. 현재 카탈로그 YAML의 추가 `optional: true`는 저장 구성
검증과 맞지 않으므로 sandbox 전용 새 불변 profile에 포함하지 않는다. 카탈로그나 기존 profile을
변경하지 않고, reranker를 호출하지도 않는다.

## 확인된 상태 (2026-09-20)

- 격리 DB revision `0048_job_metadata_ownership`; 같은 코드의 Windows API/worker/beat 사용.
- PostgreSQL·Redis·Elasticsearch healthy, API 및 frontend 경유 health HTTP 200.
- 합성 TXT 업로드 HTTP 201; Asset 검증 Job와 두 RAG ingestion Job 모두 `succeeded/ready`.
- 두 Projection과 두 활성 Build `ready`.
- 선택 문서 BM25와 E5 hybrid 모두 HTTP 200, `supported`, 정확한 문서/버전/Projection 출처 확인.
- 외부 generation은 요청하지 않았다. BGE-M3, LLM 답변·인용 검증, OCR 품질은 이번 검증 범위 밖이다.
- 재현 스크립트 안전성·출처 불일치 거절 테스트 23개 통과; 스크립트 타입 검사와 Ruff 통과.

초기 workspace 검색 확인 뒤 legacy alias에서 document-processing 의미 ID가 빠지는 선택 문서
버그를 별도 회귀 테스트와 함께 수정하고 API만 다시 시작하여 위 최종 selected-document 결과를
확인했다. 상세 값과 현재 PID는 로컬 `smoke-state.json`, `processes.json`, `logs/`를 사용한다.

## 설정 격리와 재시작

런처는 상속된 `AI_WORKSHOP_*` 값을 제거하고 검증한 sandbox 설정만 설치한다. 같은 Python
프로세스에서 `Settings.model_config['env_file']=None`을 적용한 뒤 API/Celery/migration을
실행하므로 개발 `.env`로 fallback하지 않는다. 외부 provider/secret/Codex runner 참조는 빈 매핑,
생성 endpoint/key는 미설정이다. Publishing은 sandbox `public/studies.sqlite3`와 `manual` 전달로
고정하며, 이번 작업에서는 publishing 요청을 보내지 않았다. frontend의 private/public API target도
모두 sandbox API로 지정한다. 기존 public reader로 연결하지 않는다.

최초 준비는 같은 project의 기존 컨테이너(중지 상태 포함)·volume·network가 있으면 거절한다.
이전 환경을 이름만으로 인수하거나 비우지 않는다. 현재 실행 프로세스를 교체할 때는 기록된 PID,
생성 시각과 `prepare_rag_sandbox.py <phase>` 명령을 함께 대조하고 그 프로세스의 자식만 대상으로
한다. 진행 중 Job/writer가 끝났는지 먼저 확인한다. 포트 소유자를 이름만 보고 종료하지 않으며,
이 스크립트에는 자동 종료·DB reset·volume 삭제 기능이 없다. frontend는 기존 `.next`를 그대로
사용하고 추적 파일이나 다른 인스턴스의 cache를 지우지 않는다.
