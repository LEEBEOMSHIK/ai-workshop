# 로컬 개발 실행서

- 상태: 현재 구현 기준
- 기준일: 2026-09-03

이 문서는 AI Workshop 기반을 로컬에서 설치하고 실행·검증하는 절차의 정본이다. 원본 문서와 비밀값은 Git에 추가하지 않는다.

## 1. 준비물

- Docker Desktop과 Docker Compose v2
- Node.js 22.13 이상과 pnpm 11.20
- 호스트에서 Python 명령을 실행할 경우 Python 3.13과 uv
- Elasticsearch 1 GiB heap과 E5 worker를 함께 실행할 수 있도록 Docker Desktop에 최소 4 GiB, smoke 중에는 6 GiB 이상 메모리 권장

저장소 루트에서 `.env.example`을 `.env`로 복사하고 `AI_WORKSHOP_SECRET_KEY`를 32자 이상의 로컬 비밀값으로 교체한다.

```powershell
Copy-Item .env.example .env
pnpm --dir frontend install --frozen-lockfile
cd backend
uv sync --all-groups
cd ..
```

## 2. 로컬 인프라 준비

로컬 개발에서는 PostgreSQL, Redis와 Elasticsearch만 Docker로 실행한다. React, FastAPI, Celery worker와 beat는 호스트에서 실행하며 애플리케이션 컨테이너를 함께 띄우지 않는다. API, worker와 beat는 스키마를 자동 변경하지 않으므로 migration은 명시적으로 한 번 실행한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml up -d --wait postgres redis elasticsearch
```

각 호스트 터미널을 저장소 루트에서 열고 Git 제외 `.env`를 해당 프로세스 환경으로 읽는다. 이 명령은 값 자체를 출력하지 않는다.

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^([^#][^=]*)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
  }
}
```

Windows에서는 psycopg async 연결에 Selector 이벤트 루프를 사용해 migration과 초기화 명령을 실행한다.

```powershell
backend\.venv\Scripts\python.exe -c "import asyncio; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); from alembic.config import main; main(argv=['-c','backend/alembic.ini','upgrade','head'])"
backend\.venv\Scripts\python.exe -c "import asyncio; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); from ai_workshop.cli import main; main(['register-rag-models'])"
```

Elasticsearch가 yellow 이상인지 확인한다. single-node 환경의 yellow는 replica가 배치되지 않은 정상 로컬 상태다.

```powershell
Invoke-RestMethod "http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow&timeout=10s"
```

커밋된 공개 모델 정의 등록은 멱등하며 저장 RAG 구성을 자동 생성하지 않는다.

E5 hybrid를 사용할 때만 pinned 모델을 shared `model-cache` volume에 한 번 내려받는다. worker는 `local_files_only`로 cache를 읽으며 실행 중 다른 모델이나 revision으로 조용히 전환하지 않는다. 네트워크가 허용된 초기화 시점에만 다음 명령을 사용한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml --profile model-tools run --rm --no-deps --user 0:0 model-tools chown -R 10001:10001 /models
docker compose -f infrastructure/compose/compose.yaml --profile model-tools run --rm --no-deps model-tools python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='intfloat/multilingual-e5-base', revision='d128750597153bb5987e10b1c3493a34e5a4502a', cache_dir='/models')"
```

## 3. 호스트 애플리케이션 실행

각각 별도 터미널에서 위 `.env` 로드 블록을 먼저 실행한다. Windows Celery worker는 `--pool=solo`를 사용하며 애플리케이션 진입 시 psycopg와 호환되는 Selector 정책을 설정한다.

```powershell
backend\.venv\Scripts\python.exe -m uvicorn ai_workshop.main:app --reload --host 127.0.0.1 --port $env:API_PORT
```

```powershell
backend\.venv\Scripts\python.exe -m celery -A ai_workshop.worker:celery_app worker --pool=solo --loglevel=INFO
```

```powershell
backend\.venv\Scripts\python.exe -m celery -A ai_workshop.worker:celery_app beat --loglevel=INFO --schedule .local-data/celerybeat-schedule
```

```powershell
pnpm --dir frontend dev
```

Next.js는 루트 `.env`의 `API_PORT`를 읽어 `/api` rewrite 대상을 구성하므로 다른 프로젝트와 포트가 충돌하면 `.env`의 값만 바꾸고 프론트와 API를 재시작한다.

- 프론트엔드: `http://127.0.0.1:5173`
- API 상태: `http://127.0.0.1:$env:API_PORT/api/v1/health`
- API 문서: `http://127.0.0.1:$env:API_PORT/api/docs`
- Elasticsearch 상태: `http://127.0.0.1:9200/_cluster/health`
- 공개 홈: `http://127.0.0.1:5173/`
- 공개 AI Lab: `http://127.0.0.1:5173/labs`
- 공개 RAG 기술 소개: `http://127.0.0.1:5173/labs/rag`
- 사용자 지식 공간: `http://127.0.0.1:5173/workshop/workspaces`
- 근거 검색: `http://127.0.0.1:5173/workshop/rag/search`
- RAG 구성·평가 스튜디오: `http://127.0.0.1:5173/admin/rag/configurations`
- 관리자 모델 레지스트리: `http://127.0.0.1:5173/admin/rag/models`

`/app/*`는 이전 북마크를 canonical `/workshop/*` 또는 `/admin/*`로 보내는 compatibility-only
영구 리다이렉트다. 새 문서, 링크와 smoke는 `/app/*`를 진입 주소로 사용하지 않는다.

비로그인 route smoke는 다음 계약을 확인한다.

- `/`, `/labs`, `/labs/rag`는 로그인 없이 `200`을 반환한다.
- `/workshop/workspaces`와 `/admin/rag/configurations`는 `/login` 또는 초기 설정이 필요한
  환경의 `/setup`으로 `307` 이동한다.
- `/app/rag/search`는 `/workshop/rag/search`로, `/app/rag/configurations`는
  `/admin/rag/configurations`로 `308` 이동한다.
- 기존 안전한 owner 세션이 있을 때만 `/workshop/rag/search`와
  `/admin/rag/configurations`의 실제 데이터 렌더링을 확인한다. smoke를 위해 owner를 새로
  만들거나 문서·모델·구성 데이터를 변경하지 않는다.

관리자가 없는 새 로컬 DB에서 보호 화면에 처음 접근하면 `/setup`으로 이동한다. 이름,
이메일, 12자 이상의 비밀번호와 비밀번호 확인을 입력하면 소유자 1명, 전사 지식 공간과
개인 연구 공간을 하나의 DB 트랜잭션으로 만들고 즉시 로그인해 `/workshop/workspaces`로 이동한다.
관리자가 만들어진 뒤에는 `/setup`을 다시 열 수 없으며 `/login`으로 이동한다.

CLI `bootstrap-owner`는 설정 UI를 실행할 수 없는 복구 상황에서만 사용한다. 정상 로컬
초기화 절차로 사용하지 않는다. 복구 명령도 같은 중복 방지 잠금과 기본 공간 생성 계약을
따르며 비밀번호는 명령행이나 로그가 아닌 대화형 입력으로 받는다.

```powershell
backend\.venv\Scripts\python.exe -c "import asyncio; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); from ai_workshop.cli import main; main(['bootstrap-owner','--name','Recovery Owner','--email','owner@example.com'])"
```

종료할 때 호스트 애플리케이션 프로세스를 먼저 중지한다. 인프라도 중지할 경우 `docker compose -f infrastructure/compose/compose.yaml stop postgres redis elasticsearch`를 사용해 데이터 볼륨을 유지한다.

## 4. RAG ingestion, 검색과 평가

업로드가 검증되면 Platform Asset Version이 `stored`에서 `ready`로 전이되고 Document의 active version이 원자적으로 교체된다. 구독된 indexing profile마다 RAG Projection은 `pending → parsing → chunking → embedding → indexing → ready`를 거친다. Job과 Projection이 `failed`이면 오류 코드를 확인하며, READY가 되기 전에는 검색 alias에 포함되지 않는다.

system BM25 기준선은 별도의 불변 indexing 구독으로 모든 활성 `ready` 자산에 기준선
projection 수요를 만든다. 같은 Indexing Profile의 사용자 구독과 겹치면 자산·프로파일당
job 하나만 만든다. migration은 승인된 baseline seed가 전부 없는 기존 DB만 exact seed로
복구하며, 일부만 남았거나 충돌하면 임의로 덮어쓰지 않고 실패한다.

1. `/admin/rag/configurations`에서 indexing·retrieval profile을 조합한 저장 구성을 만들고 대상 workspace를 명시한다.
2. `/workshop/rag/search`에서 BM25 기준선 또는 접근 가능한 저장 구성을 선택하고 workspace·folder 범위를 직접 지정한다.
3. 검색 결과의 keyword highlight와 semantic highlight를 구분하고, 원문 뷰어가 같은 immutable Asset Version과 Projection을 가리키는지 확인한다.
4. 구성 스튜디오에서 Evaluation Run을 시작한다. 비교에는 system BM25 기준선이 항상 포함되며 저장 구성의 정확한 version을 평가한다. 통과한 정책 결과가 없으면 기본 승격은 거절된다.

Evaluation과 ingestion은 worker가 처리하고 beat가 영속 outbox·handoff를 재조정한다. 진행 중에는 API의 run/job 상태와 아래 로그를 함께 본다. DB 레코드나 Elasticsearch alias를 수동 수정해 성공 상태를 만들지 않는다.

검색 질의가 고정 embedding model의 token 한도를 넘으면 API는
`query_token_limit_exceeded`, tokenizer가 준비되지 않으면
`query_tokenizer_unavailable` 오류 코드를 반환한다. 질의를 조용히 truncate하거나 다른
tokenizer로 대체하지 말고 선택 Configuration Version과 model cache를 확인한다.

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

백엔드 이미지를 변경했으면 build check와 실제 image footprint 회귀 검사를 함께 실행한다. 기본 검사는 image 7 GiB 이하, 내장 `/root/.cache/uv` 1 MiB 이하, 비권한 runtime import와 `/data/objects`의 `10001:10001` 소유권을 요구한다.

```powershell
docker buildx build --check -f backend/Dockerfile backend
docker build -f backend/Dockerfile -t ai-workshop-backend:local backend
.\scripts\verify-backend-image-footprint.ps1 -Image ai-workshop-backend:local
```

Windows에서 `pnpm api:check`가 현재 worktree의 `backend/.venv/Scripts/python.exe`가 없거나 잘못된 실행 파일이라 실패하면 그 명령을 성공으로 기록하지 않는다. 현재 worktree backend image로 OpenAPI를 내보낸 뒤 같은 `openapi-typescript --check` 계약을 직접 실행한다. 다음은 2026-09-01에 실제로 재실행해 통과한 fallback이다.

```powershell
$repositoryRoot = (Resolve-Path .).Path
docker run --rm --volume "${repositoryRoot}\backend\build:/app/build" ai-workshop-backend:local python tools/export_openapi.py
node frontend\node_modules\openapi-typescript\bin\cli.js backend\build\openapi.json --output frontend\src\shared\api\schema.d.ts --alphabetize --check
```

전체 스택 smoke는 격리된 `ai-workshop-smoke` 프로젝트와 별도 PostgreSQL·Redis·Elasticsearch 포트를 만든다. 실제 E2E fixture는 prepared state를 검증할 뿐 broad reset을 수행하지 않는다. reset은 `environment=test`, `AI_WORKSHOP_E2E_PREPARED=1`, `AI_WORKSHOP_E2E_RESET=1`, 격리 프로젝트명과 Compose 내부 host가 모두 일치할 때만 허용되는 단일 명령이며, 실행 중인 API·worker·beat가 없는 상태에서만 smoke가 호출한다.

1. infrastructure, migration과 pinned E5 cache를 준비하고 API·worker·beat가 중지됐는지 확인한다.
2. reset container가 PostgreSQL·Redis·Elasticsearch를 같은 Compose network에서 확인한 뒤 정확한 E2E 테이블, 격리 Redis DB 0과 해당 프로젝트의 RAG index prefix만 초기화한다.
3. beat 없이 API와 worker만 시작해 foundation E2E를 끝내고 모든 영속 job이 terminal인지 확인한 뒤 둘을 중지한다.
4. committed `model-tools` catalog 등록 명령을 명시적으로 실행한다.
5. beat 없이 API와 worker를 다시 시작해 RAG E2E를 끝낸 뒤 둘을 중지한다. E2E prepared-state helper는 production Celery task name으로 handoff, durable queued 확인, dispatch 순서를 broker에 명시적으로 전달한다.
6. 모든 E2E가 끝난 뒤에만 beat를 시작하고 실행 상태를 확인한 다음 중지한다.
7. finally에서 runtime 중지를 다시 확인하고 같은 격리 reset을 실행한 뒤 해당 프로젝트의 컨테이너와 네트워크만 제거한다. named volume과 model cache는 보존한다.

실패하면 smoke는 정리 전에 정확한 프로젝트의 `docker compose ps --all`과 API, worker, beat, PostgreSQL, Redis, Elasticsearch의 마지막 80줄 로그를 출력한다. finally는 runtime을 먼저 중지한 뒤 reset하고 cleanup 오류를 원래 실패와 별도로 보고한다. 진단·reset 실패는 원래 실패를 가리지 않으며, `down -v`나 `down --volumes`는 사용하지 않는다.

```powershell
cd ..
.\scripts\smoke.ps1
```

E2E 테스트는 `AI_WORKSHOP_E2E=1`, `AI_WORKSHOP_ENVIRONMENT=test`, `AI_WORKSHOP_E2E_PREPARED=1`이 smoke가 준비한 전용 DB에 적용된 상태에서만 실행한다. Compose `e2e` service는 API·worker·beat를 자동 시작하지 않으며 prepared flag 없이 fixture를 실행하면 DB를 바꾸기 전에 `scripts/smoke.ps1` 사용 안내와 함께 실패한다. 개발 DB에 이 값을 직접 설정하거나 reset opt-in을 적용하지 않는다.

## 7. 로그와 문제 해결

### 로컬 생성 LLM 실행기

생성형 RAG는 별도 로컬 OpenAI-compatible HTTP 실행기를 사용한다. 특정 제품이나 모델명을
코드에 고정하지 않으며 관리자가 Model Registry에 `provider=openai_compatible`,
`data_policy=local_only`, 정확한 `runtime_model`을 등록하고 Generation Profile에 연결한다.
로컬 `.env`에 다음 값을 설정한 뒤 API를 재시작한다.

```dotenv
AI_WORKSHOP_GENERATION_BASE_URL=http://127.0.0.1:<local-port>
# 실행기가 인증을 요구할 때만 설정
AI_WORKSHOP_GENERATION_API_KEY=<local-secret>
```

endpoint는 loopback 주소만 허용한다. 준비 상태 확인은 `/v1/models`가 등록된
`runtime_model`과 정확히 일치하는지 검사한다. 문맥 질의 확정과 답변 생성은
`/v1/chat/completions`의 JSON 응답을 사용하며, 실행기 연결 실패·모델 불일치·잘못된
구조화 출력은 다른 모델이나 추출식 답변으로 전환하지 않는다. 리랭커를 구성하지 않은
상태는 정상이며 Hybrid RRF 결과가 곧바로 근거 선별 단계로 전달된다.

### Deployment Registry와 OpenAI Responses 운영

새 Deployment는 endpoint와 인증정보의 실제 값을 DB에 저장하지 않는다. 루트 `.env` 또는
승인된 Secret Manager에서 안전한 reference 이름을 실제 값으로 해석하고, 관리자 화면에는
reference의 존재 여부만 표시한다. JSON은 한 줄 객체여야 하며 실제 credential이 포함된
`.env`를 출력·공유·커밋하지 않는다.

```dotenv
AI_WORKSHOP_PROVIDER_ENDPOINT_REFS={"provider-endpoint":"https://api.openai.com/v1"}
AI_WORKSHOP_PROVIDER_SECRET_REFS={"provider-credential":"<approved-secret-value>"}
```

로컬 OpenAI-compatible 실행기도 같은 reference map을 사용해 loopback endpoint를 등록할 수
있다. 이전 `AI_WORKSHOP_GENERATION_BASE_URL`과 `AI_WORKSHOP_GENERATION_API_KEY`는 legacy
model-bound Generation Profile을 읽기 위한 호환 경로이며 새 Deployment에는 사용하지 않는다.
reference map을 바꾼 뒤에는 API 프로세스를 재시작한다.

owner는 `/admin/rag/configurations`에서 다음 순서로 설정한다.

`/api/v1/rag/deployments/options`와 Generation Profile 기술 카탈로그는 owner 설정 화면만
사용한다. 일반 사용자 `/workshop/rag/search`는 `/api/v1/rag/configurations`에 포함된 서버 계산
안전 실행 미리보기만 읽으며, Deployment/Profile UUID, 원시 Provider 모델 ID, endpoint·secret
reference를 조회하거나 브라우저에서 조합하지 않는다. 생성형 구성의 미리보기가 없으면 제출을
막고 관리자에게 구성 상태 확인을 안내한다. 추출형 구성은 미리보기가 없어도 정상이다.

저장 구성의 `answer_ready`는 단순히 Generation Profile 존재 여부가 아니다. 로컬·온프레미스는
정확한 Deployment health와 환경 호환성이 준비돼야 하고, 외부 실행은 최신 Installation 및 모든
Workspace 정책과 저장된 exact 승인 snapshot까지 일치해야 한다. 정책 강화 또는 승인 불일치는
다음 구성 조회부터 fail-closed로 반영되며 이 확인 과정에서는 Provider를 호출하지 않는다.
`service_ready`가 거짓이면 `answer_reasons`의 안전 코드부터 확인한다.

1. Model Definition을 선택하고 Provider, 실행 위치, 정확한 Provider 모델 ID, 허용 환경,
   기능, timeout·retry와 reference 이름을 가진 새 불변 Deployment Version을 등록한다.
2. Installation Data Policy의 새 version에서 외부 전송 모드와 허용 Provider를 확정한다.
3. 사용할 각 Workspace 정책을 회사 기본과 같거나 더 강하게 설정한다. 회사 기본보다
   완화하는 version은 저장되지 않는다.
4. Deployment health check를 실행해 설정한 정확한 모델 identity와 readiness를 확인한다.
5. 정확한 Deployment Version에 연결된 새 Generation Profile을 만들고 Saved RAG
   Configuration의 새 version을 저장한다. 외부 Deployment이면 화면의 Provider, 전송 데이터
   범주, 대상 Workspace와 disclosure version을 확인하고 명시 승인한다.
6. `/workshop/rag/search`에서 제출 전 처리 위치 고지를 확인하고, 답변 뒤 실제 Provider,
   모델·버전, 실행 위치와 외부 전송 여부가 표시되는지 확인한다.

정책을 되돌릴 때 기존 행을 수정하거나 삭제하지 않는다. Installation 또는 Workspace에
`deny`인 새 policy version을 추가하면 과거 구성도 다음 실행부터 즉시 차단된다. 필요한 경우
Secret Manager에서 credential을 폐기하고 reference map을 제거한 뒤 API를 재시작한다. 과거
Deployment·Generation Profile·구성 version과 metadata-only 감사 기록은 재현을 위해 남긴다.

외부 OpenAI smoke는 owner가 외부 전송을 명시 승인하고 비민감 합성 질문·문서만 준비한 경우에
별도로 수행한다. 질문, 문서 근거, prompt, Provider request/response와 API key를 캡처하거나
로그에 남기지 않는다. 자동 테스트는 mock transport만 사용하며 실제 또는 과금 가능한 API를
호출하지 않는다. 확인 항목은 exact Deployment 1회 실행, 구조화 출력, 문장별 인용, 원문 이동,
응답 execution snapshot과 metadata-only audit이다.

- `workspace_external_transfer_denied` 또는 `provider_not_allowed`: 현재 Installation과 모든
  선택 Workspace의 최신 정책 version을 확인한다. 일부 문서만 제외해 우회하지 않는다.
- `deployment_not_ready`: 현재 환경, reference 구성, 필수 capability, 최신 health, exact 승인
  snapshot과 Generation Profile binding을 확인한다.
- `provider_authentication_failed`: 화면이나 로그에 credential을 출력하지 말고 Secret Manager의
  활성 상태와 reference 연결을 확인한다.
- `provider_rate_limited`, `provider_timeout`: 같은 Deployment의 명시된 retry만 적용된다. 다른
  모델이나 Provider로 자동 전환하지 않는다.
- `provider_invalid_response`, `structured_output_invalid`, `citation_validation_failed`: 원문 응답을
  보존하거나 사용자에게 노출하지 말고 안전 오류 코드, correlation ID와 해당 불변 구성
  version으로 재현한다.

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
- 관리자 설정 중복 오류: `/setup`은 최초 한 번만 허용된다. 기존 계정으로 `/login`에서 로그인한다. UI를 사용할 수 없는 복구 상황에서만 `bootstrap-owner`를 사용한다.
- OpenAPI 타입 불일치: 백엔드 계약을 바꾼 뒤 `pnpm --dir frontend api:generate`를 실행하고 생성 파일을 함께 커밋한다.

볼륨 삭제는 PostgreSQL, Redis, Elasticsearch 색인, 모델 cache와 업로드 문서를 복구하기 어렵게 제거하므로 일반 문제 해결 절차로 사용하지 않는다. smoke에서도 `down -v`나 `down --volumes`를 사용하지 않는다.
