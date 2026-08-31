# 로컬 개발 실행서

- 상태: 현재 구현 기준
- 기준일: 2026-08-31

이 문서는 AI Workshop 기반을 로컬에서 설치하고 실행·검증하는 절차의 정본이다. 원본 문서와 비밀값은 Git에 추가하지 않는다.

## 1. 준비물

- Docker Desktop과 Docker Compose v2
- Node.js 22.12 이상과 pnpm 11.20
- 호스트에서 Python 명령을 실행할 경우 Python 3.13과 uv
- Elasticsearch 1 GiB heap과 E5 worker를 함께 실행할 수 있도록 Docker Desktop에 최소 4 GiB, smoke 중에는 6 GiB 이상 메모리 권장

저장소 루트에서 `.env.example`을 `.env`로 복사하고 `AI_WORKSHOP_SECRET_KEY`를 32자 이상의 로컬 비밀값으로 교체한다.

```powershell
Copy-Item .env.example .env
pnpm install
cd backend
uv sync --all-groups
cd ..
```

## 2. 권장 실행: 백엔드 컨테이너 + 호스트 프론트엔드

API, worker, beat와 migration은 모두 `backend/Dockerfile`로 만든 같은 이미지를 쓴다. API, worker나 beat가 스키마를 자동 변경하지 않으며 migration은 매번 명시적으로 한 번 실행한다. Elasticsearch는 1 GiB 고정 heap의 single-node 로컬 인스턴스다.

```powershell
docker compose -f infrastructure/compose/compose.yaml build api
docker compose -f infrastructure/compose/compose.yaml up -d --wait postgres redis elasticsearch
docker compose -f infrastructure/compose/compose.yaml --profile tools run --rm migrate
```

Elasticsearch가 yellow 이상인지 확인한다. single-node 환경의 yellow는 replica가 배치되지 않은 정상 로컬 상태다.

```powershell
Invoke-RestMethod "http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow&timeout=10s"
```

커밋된 공개 모델 정의를 멱등 등록한다. 이 명령은 저장 RAG 구성을 자동 생성하지 않는다.

```powershell
docker compose -f infrastructure/compose/compose.yaml --profile model-tools run --rm model-tools
```

E5 hybrid를 사용할 때만 pinned 모델을 shared `model-cache` volume에 한 번 내려받는다. worker는 `local_files_only`로 cache를 읽으며 실행 중 다른 모델이나 revision으로 조용히 전환하지 않는다. 네트워크가 허용된 초기화 시점에만 다음 명령을 사용한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml --profile model-tools run --rm --no-deps --user 0:0 model-tools chown -R 10001:10001 /models
docker compose -f infrastructure/compose/compose.yaml --profile model-tools run --rm --no-deps model-tools python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='intfloat/multilingual-e5-base', revision='d128750597153bb5987e10b1c3493a34e5a4502a', cache_dir='/models')"
```

최초 한 번 소유자를 만든다. 비밀번호는 명령행이나 로그에 남지 않도록 대화형 입력을 사용한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml run --rm api ai-workshop bootstrap-owner --name "Local Owner" --email "owner@example.com"
```

API, worker와 주기적 검증·handoff·outbox reconciler를 실행하는 beat를 시작한 뒤 별도 터미널에서 프론트엔드를 실행한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml up -d api worker beat
pnpm --dir frontend dev
```

- 프론트엔드: `http://127.0.0.1:5173`
- API 상태: `http://127.0.0.1:8000/api/v1/health`
- API 문서: `http://127.0.0.1:8000/api/docs`
- Elasticsearch 상태: `http://127.0.0.1:9200/_cluster/health`
- 근거 검색: `http://127.0.0.1:5173/rag/search`
- RAG 구성·평가 스튜디오: `http://127.0.0.1:5173/rag/configurations`

종료할 때는 데이터 볼륨을 유지한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml down
```

## 3. 호스트 백엔드 실행

PostgreSQL, Redis와 Elasticsearch를 컨테이너로 시작하고 migration·모델 등록·필요한 로컬 모델 cache를 위 절차대로 준비한 다음 아래 명령을 각각 별도 터미널에서 실행할 수 있다. 호스트 worker의 `AI_WORKSHOP_MODEL_CACHE_ROOT`는 같은 cache를 가리켜야 한다.

```powershell
cd backend
uv run alembic upgrade head
uv run ai-workshop bootstrap-owner --name "Local Owner" --email "owner@example.com"
uv run uvicorn ai_workshop.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
cd backend
uv run celery -A ai_workshop.worker:celery_app worker --loglevel=INFO
```

```powershell
cd backend
uv run celery -A ai_workshop.worker:celery_app beat --loglevel=INFO
```

Windows ARM64에서 psycopg 바이너리를 불러오지 못하거나 `WinError 193`이 발생하면 호스트 백엔드 대신 권장 컨테이너 실행을 사용한다.

## 4. RAG ingestion, 검색과 평가

업로드가 검증되면 Platform Asset Version이 `stored`에서 `ready`로 전이되고 Document의 active version이 원자적으로 교체된다. 구독된 indexing profile마다 RAG Projection은 `pending → parsing → chunking → embedding → indexing → ready`를 거친다. Job과 Projection이 `failed`이면 오류 코드를 확인하며, READY가 되기 전에는 검색 alias에 포함되지 않는다.

1. `/rag/configurations`에서 indexing·retrieval profile을 조합한 저장 구성을 만들고 대상 workspace를 명시한다.
2. `/rag/search`에서 BM25 기준선 또는 접근 가능한 저장 구성을 선택하고 workspace·folder 범위를 직접 지정한다.
3. 검색 결과의 keyword highlight와 semantic highlight를 구분하고, 원문 뷰어가 같은 immutable Asset Version과 Projection을 가리키는지 확인한다.
4. 구성 스튜디오에서 Evaluation Run을 시작한다. 비교에는 system BM25 기준선이 항상 포함되며 저장 구성의 정확한 version을 평가한다. 통과한 정책 결과가 없으면 기본 승격은 거절된다.

Evaluation과 ingestion은 worker가 처리하고 beat가 영속 outbox·handoff를 재조정한다. 진행 중에는 API의 run/job 상태와 아래 로그를 함께 본다. DB 레코드나 Elasticsearch alias를 수동 수정해 성공 상태를 만들지 않는다.

## 5. 마이그레이션

현재 revision 확인과 신규 migration 검사는 다음과 같이 실행한다.

```powershell
cd backend
uv run alembic current
uv run alembic check
```

컨테이너 실행에서는 항상 다음 일회성 명령으로 upgrade한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml --profile tools run --rm migrate
```

API, worker와 beat를 여러 개 실행해도 migration을 자동 수행하지 않는다.

## 6. 테스트와 품질 검사

빠른 로컬 검사는 다음 명령을 사용한다. 기본 pytest에서 실제 DB E2E는 건너뛴다.

```powershell
cd backend
uv lock --check
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run alembic check

cd ..\frontend
pnpm test --run
pnpm typecheck
pnpm lint
pnpm build
pnpm api:check
```

전체 스택 smoke는 격리된 `ai-workshop-smoke` 프로젝트와 별도 PostgreSQL·Redis·Elasticsearch 포트를 만들고, migration, pinned E5 cache, API/worker/beat health, foundation 및 RAG E2E를 실행한다. 종료 시 해당 프로젝트의 컨테이너와 네트워크만 제거하고 named volume은 보존한다.

```powershell
cd ..
.\scripts\smoke.ps1
```

E2E 테스트는 `AI_WORKSHOP_E2E=1`과 `AI_WORKSHOP_ENVIRONMENT=test`가 모두 적용된 전용 DB에서만 실행한다. 개발 DB에 직접 이 값을 설정해 실행하지 않는다.

## 7. 로그와 문제 해결

```powershell
docker compose -f infrastructure/compose/compose.yaml ps
docker compose -f infrastructure/compose/compose.yaml logs api worker beat postgres redis elasticsearch
```

- Docker 연결 오류: Docker Desktop을 시작하고 `docker info`가 성공하는지 확인한다.
- 포트 충돌: `.env`의 `API_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, `ELASTICSEARCH_PORT`를 사용하지 않는 포트로 바꾼다.
- Elasticsearch가 healthy가 아님: Docker 메모리와 `ES_JAVA_OPTS`의 1 GiB heap을 확인하고 `_cluster/health` 응답 및 Elasticsearch 로그를 본다. data volume을 삭제해 우회하지 않는다.
- API가 시작되지 않음: migration 명령이 성공했는지 확인하고 API 로그의 오류 코드를 본다.
- worker가 작업을 처리하지 않음: Redis 상태와 worker health/log를 확인한다. 실패 job은 API 상태에서 오류 코드를 확인한다.
- E5 embedding이 시작되지 않음: 등록된 model revision과 `model-cache`의 pinned snapshot을 확인한다. 외부 API나 다른 모델로 전환하지 말고 cache 초기화 명령을 다시 실행한다.
- 저장된 Asset 검증이 시작·재개되지 않음: beat 로그에서 `ai_workshop.assets.reconcile_dispatches` 실행 여부를 확인한다. `verification_dispatch_retry`는 broker 전달 실패, `retrying_verification`은 재시도 가능한 객체·DB 오류를 뜻한다.
- READY Asset의 구독별 RAG job이 누락됨: beat 로그에서 `ai_workshop.rag.reconcile_asset_handoffs` 실행 여부를 확인한다. reconciler는 현재 active READY 버전의 누락 프로파일만 기존 멱등 키로 생성한다.
- RAG handoff beat가 실패함: `rag_asset_handoff_reconcile_failed` 로그의 집계 수와 `rag_asset_handoff_failures`의 `status`, `error_class`, `error_code`, `attempt_count`, `last_attempt_at`, `next_retry_at`만 확인한다. `last_error_message`는 진단용으로 제한된 안전한 문구이며 원문·비밀값을 넣지 않는다.
- `retrying`: DB나 운영 의존성을 복구한 뒤 `next_retry_at` 이후 beat가 기존 멱등 키로 재시도한다. `quarantined`: 프로파일/구독 같은 결정적 원인을 먼저 수정하고 정상 API/worker 흐름으로 다시 요청한다. `cancelled`: Asset Version이 더 이상 active source가 아닌 정상적인 종결 상태이므로 재시도하지 않는다. 성공하면 같은 exact identity 레코드는 `resolved`가 된다.
- RAG alias parity beat가 실패함: `rag_alias_parity_reconcile_failed` 로그의 bounded `profile UUID:error_code:retryable` 항목으로 프로파일을 찾고, PostgreSQL의 current active READY Asset Version·READY Projection·READY Build와 Elasticsearch alias target만 비교한다. `is_active`나 alias를 수동 수정하지 않는다. 외부 alias 호출 동안 source/profile lock이 유지되므로 검색 연결 지연도 함께 확인하고, 원인을 복구한 뒤 다음 beat가 alias와 모든 Build flag를 함께 수렴하게 한다.
- 비활성 source의 RAG Job/Projection이 남음: beat가 둘을 `index_source_inactive`로 실패시키고 dispatch를 `cancelled`로 만든다. DB에서 상태나 attempt를 직접 되돌리거나 새 outbox를 수동 삽입하지 말고, active 버전의 정상 구독/handoff가 새 멱등 command를 만들게 한다.
- Projection이 `failed`임: Job의 bounded `error_code`와 stage, worker 로그의 안전한 예외 분류를 확인한다. `parsed_document_empty`와 `chunking_result_empty`는 입력·파싱 또는 chunking 계약을 수정한 새 Asset Version/Profile로 재처리해야 하는 terminal 오류다. 기존 terminal Projection을 READY나 PENDING으로 되돌리지 않는다. transient 의존성 오류는 원인을 복구한 뒤 영속 dispatch/reconciler의 기존 멱등 흐름으로 재시도한다.
- 저장된 RAG 작업이 worker로 전달되지 않음: beat가 실행 중인지 확인하고 beat 로그에서 `ai_workshop.rag.reconcile_dispatches` 실행 여부를 확인한다.
- 객체 저장 권한 오류: `object-store-init` 서비스가 성공 종료했는지 `docker compose ps -a`로 확인한다.
- owner 중복 오류: owner bootstrap은 최초 한 번만 허용된다. 기존 계정으로 로그인한다.
- OpenAPI 타입 불일치: 백엔드 계약을 바꾼 뒤 `pnpm --dir frontend api:generate`를 실행하고 생성 파일을 함께 커밋한다.

볼륨 삭제는 PostgreSQL, Redis, Elasticsearch 색인, 모델 cache와 업로드 문서를 복구하기 어렵게 제거하므로 일반 문제 해결 절차로 사용하지 않는다. smoke에서도 `down -v`나 `down --volumes`를 사용하지 않는다.
