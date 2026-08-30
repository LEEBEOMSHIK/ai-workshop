# 로컬 개발 실행서

- 상태: 현재 구현 기준
- 기준일: 2026-08-29

이 문서는 AI Workshop 기반을 로컬에서 설치하고 실행·검증하는 절차의 정본이다. 원본 문서와 비밀값은 Git에 추가하지 않는다.

## 1. 준비물

- Docker Desktop과 Docker Compose v2
- Node.js 22.12 이상과 pnpm 11.20
- 호스트에서 Python 명령을 실행할 경우 Python 3.13과 uv

저장소 루트에서 `.env.example`을 `.env`로 복사하고 `AI_WORKSHOP_SECRET_KEY`를 32자 이상의 로컬 비밀값으로 교체한다.

```powershell
Copy-Item .env.example .env
pnpm install
cd backend
uv sync --all-groups
cd ..
```

## 2. 권장 실행: 백엔드 컨테이너 + 호스트 프론트엔드

API, worker, beat와 migration은 모두 `backend/Dockerfile`로 만든 같은 이미지를 쓴다. API, worker나 beat가 스키마를 자동 변경하지 않으며 migration은 매번 명시적으로 한 번 실행한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml build api
docker compose -f infrastructure/compose/compose.yaml up -d postgres redis
docker compose -f infrastructure/compose/compose.yaml --profile tools run --rm migrate
```

최초 한 번 소유자를 만든다. 비밀번호는 명령행이나 로그에 남지 않도록 대화형 입력을 사용한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml run --rm api ai-workshop bootstrap-owner --name "Local Owner" --email "owner@example.com"
```

API, worker와 주기적 outbox reconciler를 실행하는 beat를 시작한 뒤 별도 터미널에서 프론트엔드를 실행한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml up -d api worker beat
pnpm --dir frontend dev
```

- 프론트엔드: `http://127.0.0.1:5173`
- API 상태: `http://127.0.0.1:8000/api/v1/health`
- API 문서: `http://127.0.0.1:8000/api/docs`

종료할 때는 데이터 볼륨을 유지한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml down
```

## 3. 호스트 백엔드 실행

PostgreSQL과 Redis만 컨테이너로 시작한 다음 아래 명령을 각각 별도 터미널에서 실행할 수 있다.

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

## 4. 마이그레이션

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

## 5. 테스트와 품질 검사

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

전체 스택 smoke는 격리된 `ai-workshop-smoke` 프로젝트와 별도 포트를 만들고, migration·health·foundation E2E를 실행한 뒤 테스트 컨테이너와 볼륨을 정리한다.

```powershell
cd ..
.\scripts\smoke.ps1
```

E2E 테스트는 `AI_WORKSHOP_E2E=1`과 `AI_WORKSHOP_ENVIRONMENT=test`가 모두 적용된 전용 DB에서만 실행한다. 개발 DB에 직접 이 값을 설정해 실행하지 않는다.

## 6. 로그와 문제 해결

```powershell
docker compose -f infrastructure/compose/compose.yaml ps
docker compose -f infrastructure/compose/compose.yaml logs api worker beat postgres redis
```

- Docker 연결 오류: Docker Desktop을 시작하고 `docker info`가 성공하는지 확인한다.
- 포트 충돌: `.env`의 `API_PORT`, `POSTGRES_PORT`, `REDIS_PORT`를 사용하지 않는 포트로 바꾼다.
- API가 시작되지 않음: migration 명령이 성공했는지 확인하고 API 로그의 오류 코드를 본다.
- worker가 작업을 처리하지 않음: Redis 상태와 worker health/log를 확인한다. 실패 job은 API 상태에서 오류 코드를 확인한다.
- 저장된 RAG 작업이 worker로 전달되지 않음: beat가 실행 중인지 확인하고 beat 로그에서 `ai_workshop.rag.reconcile_dispatches` 실행 여부를 확인한다.
- 객체 저장 권한 오류: `object-store-init` 서비스가 성공 종료했는지 `docker compose ps -a`로 확인한다.
- owner 중복 오류: owner bootstrap은 최초 한 번만 허용된다. 기존 계정으로 로그인한다.
- OpenAPI 타입 불일치: 백엔드 계약을 바꾼 뒤 `pnpm --dir frontend api:generate`를 실행하고 생성 파일을 함께 커밋한다.

볼륨 삭제는 PostgreSQL, Redis와 업로드 문서를 복구하기 어렵게 제거하므로 일반 문제 해결 절차로 사용하지 않는다.
