# 로컬 개발 실행서

- 상태: 현재 구현 기준
- 기준일: 2026-09-20

이 문서는 AI Workshop 기반을 로컬에서 설치하고 실행·검증하는 절차의 정본이다. 원본 문서와 비밀값은 Git에 추가하지 않는다.

### 현재 본래 환경 적용 상태 (2026-09-20)

기존 `.env`의 PostgreSQL `127.0.0.1:15432/ai_workshop_local_clean`, Redis `6379/3`,
Elasticsearch `9200`과 `.local-data/objects`를 유지한다. API `18000`, frontend `5173`은
이 본래 환경이며 기존 마스터 계정을 사용한다. sandbox 계정으로 안내하지 않는다.
백업의 실제 복원과 0034→0048 리허설 후 본래 DB에도 `0048_job_metadata_ownership`을 적용했다.
계정·권한과 기존 데이터는 보존했으며 원본/RAG/임시 저장소 marker와 실제 ES cluster binding을
설정했다. 기존 원본·색인·Jobs의 추적 revision은 임의 backfill하지 않았다.
시작 명령은 [WORKBOARD 상단](../../WORKBOARD.md)에 있다. 평상시 시작에 migration·bootstrap을 반복하지 않는다.
별도 sandbox는 런타임만 중지했으며 본래 환경 검증과 필요한 내용 인계가 끝나기 전 삭제하지 않는다.

### 게임형 공개 입구 실행

공개 `/`의 Office MVP는 백엔드·Docker·로그인 없이 실행할 수 있다.
`pnpm --dir frontend install --frozen-lockfile` 후
`pnpm --dir frontend dev`로 `http://127.0.0.1:5173/`에 접속한다.
화면 준비 후 최초 자동 포커스가 적용되면 바로 WASD/방향키로 이동한다.
로딩 중 메뉴를 선택하거나 창을 떠났다면 포커스를 빼앗지 않는다. 이때는 화면을 클릭하거나
Tab으로 이동 공간에 초점을 두어 이동을 시작한다.
로비의 통로에서 사장실 또는 RAG 연구소로 이동한다. Founder와 RAG 총괄 캐릭터를 클릭하거나
가까이에서 E를 눌러 React 대화창을 연다. Founder는 공개 연구 방향을 소개하며 실제 명령을
  실행하지 않는다. RAG 총괄의 `RAG 연구소 들어가기`는 `/labs/rag`의 담당자 작업실로 연결된다.
닫기 또는 Escape로 복귀한다. 대화 중·포커스 이탈 중에는 이동하지 않는다.
로비 아래 연결 복도에는 파인튜닝 연구소·AI 공부실·온톨로지 연구소가 준비 공간으로 있다.
각 방의 모집 안내판을 클릭하거나 가까이에서 E로 목적과 준비 상태를 확인한다.
세 공간은 둘러보기만 가능하며 서비스 실행·신청·관리자 NPC는 제공하지 않는다.

검증 명령은 `pnpm --dir frontend test --run src/features/office-game`,
`pnpm --dir frontend typecheck`, `pnpm --dir frontend lint`, `pnpm --dir frontend build`다.
실행 중인 프론트를 대상으로 `pnpm --dir frontend test:office`로 실제 브라우저를 검증한다.
기본 브라우저는 설치된 Edge이며 `OFFICE_TEST_BROWSER=chrome` 등 Playwright channel과
`OFFICE_TEST_BASE_URL`로 테스트 환경을 변경할 수 있다. 브라우저를 자동 설치하지 않는다.
테스트는 공개 입구만 사용하며 로그인·업로드·모델 요청을 하지 않는다.
실패 진단 산출물은 `.local-data/browser-verification/office-game/`에 한정한다.
후속 그래픽 교체 시 `frontend/public/office/maps/office.json`을 Tiled로 편집하고
맵과 tileset 상대 경로를 함께 유지한다.

## 개발·실험 기록 공개 저장소

Publishing은 비공개 PostgreSQL의 편집본·승인·명령과 별도 SQLite의 공개 게시본을 분리한다.
로컬 private API와 공개 reader가 사용하는 아래 두 경로는 같은 절대 경로로 지정한다.
상대 경로를 쓰면 프로세스 작업 디렉터리에 따라 서로 다른 파일을 바라볼 수 있다.

- private API: `AI_WORKSHOP_PUBLISHING_PUBLIC_STORE_PATH`
- 공개 reader: `AI_WORKSHOP_PUBLIC_STORE_PATH`
- 로컬 전달: `AI_WORKSHOP_PUBLISHING_DELIVERY_MODE=local`
- 관리자 변경 Origin: `AI_WORKSHOP_PUBLISHING_ALLOWED_ADMIN_ORIGINS`
  (JSON 배열, 기본 `http://127.0.0.1:5173`, `http://localhost:5173`)
- 공개 표시 인물: `AI_WORKSHOP_PUBLISHING_APPROVED_PUBLIC_PERSONAS`
  (승인된 `{slug,label}`의 JSON 배열, 기본 빈 배열). 로그인 계정에서 자동 생성하지 않는다.

관리자 변경 요청은 기존 owner 인증 외에 허용 Origin, JSON Content-Type,
`X-Publishing-Request: 1`을 요구한다. 다른 포트로 관리자 화면을 실행하면 정확한 Origin을
추가해야 하며 와일드카드를 사용하지 않는다.

독립 reader 진입점은 `ai_workshop.public_app:app`이다. 이 프로세스에는 루트 `.env`나
private DB·모델 비밀값을 주입하지 않고 공개 SQLite 경로만 전달한다. 공개 reader는 파일을
읽기 전용으로 열며 파일이 없거나 사용할 수 없으면 빈 목록 대신 서비스 오류를 반환한다.
게시 적용은 private 측에서 수행하고 적용 확인 전에는 관리자 화면에서 대기로 표시한다.
SQLite 파일과 sidecar는 캐시가 아닌 공개 서비스 데이터이므로 `CACHE_POLICY.md`를 따른다.

같은 Windows 계정의 별도 프로세스는 기능 분리만 확인한다. 실제 파일 접근권한 격리를
입증하지 않으며 운영 배포 전 별도 사용자/ACL 등으로 검증해야 한다. 운영 환경은
`manual` 전달 모드를 요구한다. 수동 반출·반입·receipt 운영 도구와 실제 격리 검증은
로컬 UI 확인과 별도의 배포 준비 사항이다.

프론트 실행 모드는 `AI_WORKSHOP_FRONTEND_RUNTIME=combined|public`이다. 통합 로컬 모드는
기존 `API_PORT`로 private API를 찾는다. 공개 reader는 `AI_WORKSHOP_PUBLIC_API_TARGET`의
HTTP(S) origin을 사용하거나, 미설정 시 `PUBLIC_API_PORT`(기본 18001)의 loopback 주소를
사용한다. 이 값에는 인증정보·경로·query를 넣지 않는다.

공개 전용 모드는 루트 `.env`를 읽지 않고 private API rewrite를 만들지 않으며 관리자·작업소·
로그인·설정 경로와 private API 요청을 제공하지 않는다. 이 모드의 설정은 루트 `.env`가 아닌
해당 프로세스 환경으로 전달해야 한다. 기능 분리와 별개로 운영 서버의 권한 격리는 필요하다.

같은 소스에서 검증용 프론트를 별도로 실행할 때는 프로세스 환경에
`AI_WORKSHOP_FRONTEND_INSTANCE`를 안전한 인스턴스 이름으로 지정한다. 기본값은 기존 `.next`이며,
지정한 인스턴스의 빌드는 `frontend/.next/instances/<이름>/`에서 분리한다. 포트만 바꾸면 기존
개발 서버의 빌드 잠금과 충돌할 수 있다. 경로 자체를 입력하지 않으며 기존 서버를 종료하지 않는다.
Next.js의 [별도 빌드 디렉터리 설정](https://nextjs.org/docs/pages/api-reference/config/next-config-js/distDir)을 사용한다.

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
uv sync --all-groups --extra embedding-cpu --extra ocr-cpu
cd ..
```

## 2. 로컬 인프라 준비

### 기술별 권한 기반 배포 전 주의

[ADR-0022](../decisions/0022-technology-permissions.md)의 권한 기반은 단계별 구현 중이다.
권한 테이블·설치 완료 상태를 추가하는 migration과 실행 중인 로컬 DB 반영은 별도 작업이다.
코드 검증만으로 적용 완료를 추정하지 말고 `WORKBOARD.md`의 실제 반영 상태를 확인한다.

실제 반영은 아래 순서를 포함하는 하나의 조정된 유지보수 cutover로 별도 승인받아 수행한다.
승인 범위에는 정확한 대상 DB, 백업 산출물과 복원 대상, 중단 시간, 함께 배포할 backend/frontend
버전을 포함한다. 코드·문서 변경은 이 승인이나 실제 migration·재시작·계정 작업을 대신하지 않는다.

1. 신규 setup 및 identity 쓰기가 들어오지 않도록 진입 경로를 차단한다.
2. 구 API가 새 요청을 받지 않게 하고 진행 중인 setup/identity 쓰기를 drain한 뒤 구 API를 중지한다.
   구 버전 `bootstrap-owner`, CLI, 자동화 등 사용자를 쓰는 모든 bootstrap writer도 함께 중지한다.
3. 구 API와 구 bootstrap writer가 모두 중지됐음을 확인한 뒤에만 승인된 `0030` migration을 적용한다.
4. DB의 현재 revision이 `0030_technology_permissions`인지 읽기 전용으로 확인한다.
5. 확인 후 같은 릴리스의 새 backend와 frontend만 시작하고 health, setup 완료 상태, 기존 마스터
   로그인 응답과 `/admin/system/access` 조회를 읽기 전용으로 확인한다.

구·신 backend writer를 동시에 실행하지 않으며 migration 후 구 bootstrap/CLI를 다시 사용하지 않는다.
새 권한 UI를 구 API와 조합하면 관련 route가 없어 사용할 수 없는 상태이며 활성화로 간주하지 않는다.
새 backend를 migration 전에 시작하거나 구 writer를 migration 뒤 다시 시작하지 않는다.
자동 startup migration이나 기존 사용자 자동 승격·활성화로 오류를 우회하지 않는다.
기존 사용자에 활성 마스터가 없거나 역할 데이터가 불일치하면 migration을 중단하고 조사한다.
빈 설치는 공개 setup을 한 번만 허용하며, 완료 후 계정이 손상돼도 setup을 다시 열지 않는다.

최초 권한 관리 화면은 기존 사용자만 대상으로 한다. 한 명이면 마스터 본인과 보호 안내만
보이는 것이 정상이며, 테스트를 위해 실사용 DB에 회원을 만들거나 권한을 변경하지 않는다.
기술 권한의 저장과 RAG 경로 위임 연결은 구별된다. `적용 준비 중` 기술은 저장하더라도
기존 마스터 전용 경로가 일반 사용자에게 열리지 않는다.
권한 migration의 downgrade는 감사·권한·설치 완료 상태를 없앨 수 있으므로 자동 복구 수단으로
사용하지 않는다. 백업·서비스 중단·복원 대상 검토와 별도 승인이 선행되어야 한다.
`0030_technology_permissions`는 `0029_codex_verification` 다음 단계다. 권한/감사 또는
변경된 revision이 있으면 downgrade를 거절한다. 이를 우회하려고 감사 행을 지우지 않는다.
실제 반영 승인을 받은 경우에만 위의 쓰기 차단과 구 writer 중지를 완료한 뒤 목표 revision을
명시해 실행한다.

```powershell
backend\.venv\Scripts\python.exe -c "import asyncio; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); from alembic.config import main; main(argv=['-c','backend/alembic.ini','upgrade','0030_technology_permissions'])"
```

migration 또는 새 애플리케이션 시작이 실패하면 그 지점에서 중단한다. 검토되지 않은 downgrade,
데이터 삭제, 사용자 수리나 호환되지 않는 구 writer 재시작을 복구 수단으로 사용하지 않는다.
승인된 백업·복원 절차와 원인 검토 뒤 다음 조치를 다시 승인받는다. 읽기 전용 확인에서는 마스터
한 명일 때 비활성화·강등 버튼의 보호 안내를 확인하되, 실사용 계정으로 변경을 시험하지 않는다.

### 인프라 실행

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

### DOCX 내장 이미지 OCR 준비

DOCX 이미지 OCR은 API 컨테이너가 아니라 호스트 Celery worker에서 실행한다. 런타임은
`paddlepaddle==3.2.2`, `paddleocr==3.7.0`, `paddlex[ocr]==3.7.2`와 저장된
Document Processing Profile의 정확한
모델 조합을 사용한다. 운영에서도 같은 profile·모델 revision·산출물 SHA-256 계약을 사용하며,
실행 장치만 CPU 또는 승인된 GPU 환경으로 달라질 수 있다.

모델 산출물은 실행 중 내려받지 않는다. 정본 manifest는
`model-profiles/rag/ocr/pp-structure-v3-v1.json`이며 공식 저장소, revision, 파일 크기와
파일별 SHA-256을 고정한다. 승인된 준비 단계에서 manifest의 `runtime_role` 이름으로 구성한
staging 디렉터리를 검증·설치한다.

```powershell
backend\.venv\Scripts\python.exe scripts\provision_rag_ocr_models.py --manifest model-profiles\rag\ocr\pp-structure-v3-v1.json --source-root .local-data\models\p --cache-root .local-data\models
```

프로비저너는 전체 source를 먼저 검증하고 다음 불변 경로에 필요한 runtime 파일만 설치한다.

```text
<model-cache>/ocr/ocr_layout_detection/<sha256>
<model-cache>/ocr/ocr_text_detection/<sha256>
<model-cache>/ocr/ocr_text_recognition/<sha256>
<model-cache>/ocr/ocr_textline_orientation/<sha256>
<model-cache>/ocr/ocr_table_classification/<sha256>
<model-cache>/ocr/ocr_table_structure_wired/<sha256>
<model-cache>/ocr/ocr_table_structure/<sha256>
<model-cache>/ocr/ocr_table_cells_wired/<sha256>
<model-cache>/ocr/ocr_table_cells_wireless/<sha256>
<model-cache>/ocr/ocr_table_orientation/<sha256>
```

각 디렉터리는 관리자가 승인한 source·revision과 SHA-256 manifest로 프로비저닝한다. 하나라도
없으면 worker는 `ocr_model_artifact_missing`으로 실패하며 네트워크 다운로드, Tesseract 또는
다른 모델로 자동 전환하지 않는다. confidence 기준 미달 텍스트는 파싱 결과와 경고에는 남지만
검색 근거와 LLM 인용 후보에서는 제외된다. 같은 Asset Version 안의 동일 이미지 바이트는
SHA-256으로 OCR 실행을 한 번만 수행하되, 원문 위치별 요소는 각각 유지한다.

관리자는 `/admin/rag/configurations`의 `문서 처리 구성`에서 parser route, PP-StructureV3
pipeline, layout·detector·한국어 recognizer·표 분류·유선/무선 구조·셀 검출·방향 모델,
언어, confidence, 실행 위치와 산출물 등록
정보를 확인한다. 문서 처리 profile을 바꾸면 새 Projection·색인이 필요하며 LLM만 바꾸는 경우는
재색인하지 않는다.

프로파일 v1은 표 하위 text-line orientation 모델을 전역 비활성으로 표현한 이력 때문에
`failed`로 보존한다. 관리·평가 대상은 같은 10개 모델을 사용하면서 표 하위 방향 모듈과 일반
OCR 최상위 방향 모듈을 구분한 비기본 `pp-structure-v3-docx v2`다. 마이그레이션 `0020`은
기존 v1을 수정하지 않고 v2를 새 불변 버전으로 추가한다.

실제 Windows CPU 검증은 준비된 불변 모델 경로만 사용하며 다음 명령으로 실행한다.
`AI_WORKSHOP_OCR_ACTUAL_SMOKE=1`이 없으면 실제 검증 3개가 건너뛰어진다. 활성화한 상태에서
모델 산출물이 없거나 손상됐다면 실패하므로, 앞의 프로비저닝 명령과 출력 경로 10개를 먼저
확인한다. 아래 명령은 실제 검증 3개를 선택하므로 `3 passed, 0 skipped`를 확인한다.

```powershell
$env:AI_WORKSHOP_OCR_ACTUAL_SMOKE = "1"
backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\labs\rag\ocr\test_paddle_structure_smoke.py -q -m integration
```

Linux CPU 배포 검증은 PaddlePaddle 공식 지원 아키텍처에 맞춘 `linux/amd64` OCR image를
사용한다. 호스트 staging 원본은 승인된 준비 단계에서만 읽고, 크기와 SHA-256을 검증해 worker와
공유하는 `model-cache` named volume에 설치한다. 실제 smoke는 해당 volume과 profile을 읽기
전용으로 연결하고 네트워크를 차단한다.

```powershell
docker compose -f infrastructure\compose\compose.yaml build model-tools
docker compose -f infrastructure\compose\compose.yaml --profile model-tools run --rm --no-deps --user 0:0 --volume "${PWD}\.local-data\models\p:/source:ro" model-tools ai-workshop provision-rag-ocr-models --manifest /app/model-profiles/rag/ocr/pp-structure-v3-v1.json --source-root /source --cache-root /models
docker compose -f infrastructure\compose\compose.yaml build ocr-linux-cpu-smoke
docker compose -f infrastructure\compose\compose.yaml run --rm ocr-linux-cpu-smoke
```

ARM64 Docker 엔진은 이미지를 AMD64로 에뮬레이션하므로 전체 추론 smoke가 매우 느릴 수 있다.
실행 전 `docker info --format '{{.Architecture}}'`로 서버가 `x86_64` 또는 `amd64`인지 확인한다.
위 Compose smoke는 설정·fixture 2개와 실제 검증 3개를 모두 실행하므로
`5 passed, 0 skipped`를 확인한다. Linux fixture는 영문 합성 데이터이며 bbox는 `[0,1]`
범위를 검사한다. 이 결과만으로 한국어 품질이나 좌표 위치 정밀도까지 검증됐다고 판단하지 않는다.
이미지·package·artifact 검증만으로 Linux CPU를 검증 완료로 승격하지 않는다. native Linux
x86_64에서 text·table·bbox 실제 추론과 처리 시간을 통과해야 하며, 그 전에는 관리자 화면에
`미구현/미검증`으로 표시한다. Linux GPU는 별도 engine·CUDA·NVIDIA hardware gate다.

## 3. 호스트 애플리케이션 실행

각각 별도 터미널에서 위 `.env` 로드 블록을 먼저 실행한다. Windows Celery worker는 `--pool=solo`를 사용하며 애플리케이션 진입 시 psycopg와 호환되는 Selector 정책을 설정한다.

Windows API는 아래 명시적 loop factory를 사용한다. Uvicorn의 `--loop asyncio`는 reload 없는 Windows 실행에서 정책과 무관하게 Proactor 루프를 선택하므로, Selector 정책 설정만으로는 psycopg async 호환성이 보장되지 않는다. 같은 factory를 유지하면 `--reload`를 생략한 실행도 Selector 루프를 사용한다.

```powershell
backend\.venv\Scripts\python.exe -m uvicorn ai_workshop.main:app --loop ai_workshop.shared.asyncio_policy:create_selector_event_loop --reload --host 127.0.0.1 --port $env:API_PORT
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
- 관리자 시스템 런타임: `http://127.0.0.1:5173/admin/system/runtime`

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

### 개인 개발용 Codex 연결

이 흐름은 소유자·개발 환경 전용이다. 설치된 CLI와 서버의
`AI_WORKSHOP_CODEX_RUNNER_REFS` 사전 설정이 필요하며, CLI 인증 파일을 앱에 복사하거나
관리자 화면에 비밀번호·API 키·실행 파일 경로를 입력하지 않는다.
Codex는 로컬에서 실행해도 질문·포함된 대화·승인 근거를 OpenAI로 보내고 계정 사용량을 쓴다.
운영 HTTP API 모델의 준비 상태·모델 식별 검증 기준은 이 예외로 완화하지 않는다.

1. 정상 소유자 로그인 후 `/admin/rag/models`에서 LLM 모델 식별자를 등록한다.
   요청 모델명은 관리 데이터이며 업무 코드에 고정하지 않는다.
2. **서버 Codex 설정 불러오기**로 사전 검사된 실행기를 확인하고 배포·생성 프로파일을 저장한다.
   제어·답변·문맥 프롬프트는 읽기 전용이다. 온도는 CLI에 전달하지 않으며,
   출력 수락 한도는 제공자 과금 상한을 보장하지 않는다.
3. 현재 설치·지식 공간의 외부 전송 정책을 확인하고 `/admin/rag/configurations`에서
   호환되는 색인·검색·생성 조합과 대상 공간, 정확한 고지 동의를 저장한다.
   사전 검사를 통과한 Codex 초안은 연결 검사 전에도 저장할 수 있지만 사용 준비 완료는 아니다.
4. 저장된 정확한 구성 카드에서 동의 후 **합성 입력으로 연결 검사**를 실행한다.
   상태 조회는 모델을 호출하지 않는다. 구성 목록을 다시 불러와 서버의 준비 상태를 확인한다.
   연결 성공은 빈 근거의 형식·통신 검사이며 검색 평가나 실제 답변 품질의 통과가 아니다.
5. 사용할 공개·합성 자료만 관리자 모델 화면에서 정확한 문서 버전·SHA-256을 확인해 승인한다.
   비공개 사용자 문서는 자동 승인하지 않는다. 승인 복구 변경(ADR-0024)을 적용한 환경에서는
   같은 문서 버전을 다시 승인할 수 있고 취소 이력은 보존된다. 변경 전 환경은 여전히 재승인 불가다.
6. 실제 색인·근거 기반 평가를 통과한 정확한 구성만 기존 도메인에 연결한다.
   `/workshop/rag/search`에서 도메인을 선택하고 질문과 포함된 이력의 분류·전송에 매번 동의한다.
   요청 모델과 실제 관측 모델은 별도이며, 관측되지 않았다면 `미확인`으로 유지한다.

검증 자료도 평가 스냅샷·승인 이력에 남는다. 현재 완전 삭제 UI가 없으므로 임시 업로드 후
완전 삭제를 약속하지 말고 보관 범위를 먼저 승인받는다. 실제 검증 현황과 남은 게이트는
[연결 진행 기록](../worklogs/2026-09-09-codex-rag-activation.md)을 따른다.

### 문서 전송 승인 복구 적용

승인 복구 변경은 코드 검증과 실제 적용을 구분한다. 현재 이관 목표는
`0032_evidence_approval_requests`까지이며 `0031_evidence_reapproval`을 거쳐 기존
`0030_technology_permissions` 데이터를 보존한다. 2026-09-12 로컬 적용·실제 백업 복원 및
독립 보존 검증을 완료했다. [적용 기록](../worklogs/2026-09-12-rag-domain-resume.md)을 참고한다.
요청 API 적용과 일반 사용자 요청함 UI의 구현 완료는 별개다.
승인/모델 실행 writer를 모두 중지하고 정확한 DB·스키마 head·백업을 확인한 다음에만
이관과 신규 binding v3 서버를 함께 적용한다. 적용 중 구버전 서버를 다시 띄우지 않는다.
이관은 기존 승인/취소 시각을 유지하고 미기록 철회 주체를 임의로 채우지 않는다.
기존 v2 대기 호출은 무효화되며 필요하면 새로운 실행 동의를 받아 발급한다.
데이터가 있는 환경의 downgrade는 차단된다. 장애 시 테이블을 비우거나 이전 승인을
덮어쓰지 말고 검토된 백업 복구/순방향 수정 절차를 선택한다.
최종 실제 적용 head와 요청함 후속 migration은 `WORKBOARD.md`의 검증 상태를 확인한다.

### 파일 관리 독립 열람 검증

구현·연결 상태는 `WORKBOARD.md`의 파일 관리 작업을 먼저 확인한다. 아래는 단계별 구현의
검증 절차이며, 화면 연결 완료 또는 RAG 검색 준비 완료를 의미하지 않는다.

1. 로그인 후 `/workshop/workspaces`에서 접근 가능한 회사/개인 공간을 확인한다.
2. 공간의 `/documents`에서 실제 공간명·현재 폴더 경로와 직접 자식 문서 목록을 확인한다.
3. 기존 공개 합성 TXT/Markdown 문서를 클릭해 활성 READY 버전의 원문을 연다.
   이 열람에는 RAG projection·색인·외부 AI 전송 승인이 필요하지 않다.
4. 버전 선택·닫기·새로고침과 URL 복원을 확인한다. 최신 업로드 버전과 활성 버전을 구분한다.
5. PDF는 서버에서 로컬 페이지 이미지로 처리한다. Office/HTML은 최초 독립 미리보기 대상이
   아니며 명시적으로 원본을 다운로드한다. 기존 RAG 근거 뷰어의 지원 범위와 혼동하지 않는다.

폴더 생성·업로드·다중 페이지 PDF·권한 거절·무결성 실패는 격리된 합성 테스트로 검증한다.
사용자 공간에 임시 문서나 폴더를 만들거나 승인 상태를 바꾸지 않는다. 실제 브라우저 검증은
이미 보관 중인 합성 문서 읽기만 수행하며, 별도 형식의 실제 UI 검증 여부를 구분해 기록한다.

### 원본 업로드 추적 활성화 전제

원본 추적 코드는 업로드 bytes를 object store에 쓰기 전에 독립 예약을 확정한다.
설정 또는 marker가 준비되지 않으면 `original_upload_unavailable`(503)로 거절하며 기존 미추적
업로드로 전환하지 않는다. 기존 원본 읽기와 파일함 탐색은 이 업로드 준비 상태와 별개다.

1. 승인된 적용 대상의 백업·복구를 확인한 뒤 migration `0045_original_upload_ownership`까지 적용한다.
   코드만 바꾸고 기존 schema로 API를 재시작하지 않는다. 이번 구현 검증은 격리 합성 DB에서만 했다.
2. 실제 `AI_WORKSHOP_OBJECT_STORE_ROOT`와 기존 원본의 접근 경로를 유지한다. 새 경로로 옮기거나
   과거 원본·임시 파일을 이름으로 추정해 자동 등록하지 않는다.
3. `AI_WORKSHOP_ORIGINAL_STORE_ID`와 `AI_WORKSHOP_ORIGINAL_STORE_BINDING_ID`를 함께 설정한다.
   전자는 소문자로 시작하는 80자 이하 machine identifier, 후자는 운영에서 새로 발급한 UUID다.
4. 실제 root의 `.ai-workshop-original-store.json`에는 `schema_version`(정수 1), `store_id`,
   `binding_id`의 세 필드만 둔다. 설정값과 정확히 일치해야 한다. 애플리케이션은 marker를 자동 생성하지 않는다.
   RAG 산출물용 `.ai-workshop-store.json`과 다른 marker이며 서로 대체하지 않는다.
5. 현재 추적 쓰기·자동 실패 정리는 Windows 파일 핸들 기반 구현만 지원한다. 그 외 운영체제의
   `publish`/`discard`는 안전한 원자성 구현 전까지 거절한다. 읽기 관찰(`observe`)은 유지한다.
   Linux 배포의 업로드 지원이 완료된 것으로 취급하지 않는다.
6. 적용 후 승인된 합성 업로드로 예약→게시→원본/검증 job/관계 원자 확정과 원본 읽기를 검증한다.
   과거 미등록 원본은 별도 dry-run/backfill 전까지 inventory에서 incomplete다.

업로드 정리 시작은 `discarding`으로 먼저 확정한다. 삭제 이후 DB 응답 상실이나 callback 실패가 나면
이 상태와 locator를 남겨 재첨부를 차단한다. 시각 경과나 job 종료만으로 원장을 지우거나 재시도하지 않는다.
원본 없는 실패 업로드는 workspace 기준 미확정 목록에서 찾는다. 공개 응답에는 경로·해시를 내보내지 않는다.
HTTP multipart 수신은 아래의 선행 예약 전제를 함께 적용한다. 일반 작업 기록은 별도 후속 경계다.
파서/OCR/뷰어 임시물은 아래의 별도 저장소 설정을 사용한다.
이 구현은 실제 영구 삭제 API/UI를 활성화하지 않는다.

### 일반 Jobs 메타데이터 추적 적용

신규 Job은 실제 문서/버전과 RESTRICT로 연결된 소유권 및 현재 provenance revision을 가진다.
상태·단계·시도·오류 갱신과 재전송 처리도 같은 transaction에서 revision을 변경한다.
migration `0048_job_metadata_ownership`은 기존 Job의 revision을 NULL로 두며 자동 backfill하지 않는다.
실사용 적용 전 기존 writer 중지·백업·복구와 schema/code 호환 확인 절차를 따른다.
신규 추적 Job은 부모 user/workspace/version의 CASCADE 삭제로도 사라지지 않는다.

Jobs의 성공·실패·재시도 상태는 파일/큐 writer 종료 증거가 아니다. 읽기 inventory의
`writer_unconfirmed`는 유지하며 Job/source 소유권 pin이나 provenance를 수동 제거하지 않는다.
실제 삭제, legacy 정리와 실행 종료 확인은 별도 후속 계약이다.

### 기존 자료와 분리된 RAG 테스트 환경

합성 자료로 업로드→검색을 검증할 때는 [RAG sandbox 절차](rag-sandbox.md)를 따른다.
별도 PostgreSQL/Redis/Elasticsearch와 Windows API/worker를 사용하며 기존 `.env`, DB와 자료를
수정하지 않는다. 코드 테스트용 UUID DB와 사용자 확인용 지속 sandbox DB도 분리한다.
이 환경의 성공은 기존 개발 DB에 migration이 적용됐다는 의미가 아니다.

### HTTP 업로드 선행 예약 활성화 전제

두 문서 업로드 API는 인증과 intake 예약 commit 이후에만 본문을 읽는다.
File/Form 자동 spool을 사용하지 않으며 파일 1개(최대 50MiB)와 신규 문서의 선택 folder_id만 받는다.
file/folder_id의 전송 순서는 모두 허용한다. 중복·알 수 없는 필드, 잘린 종료 경계와
추가 epilogue는 `upload_multipart_invalid`(422), 실제 수신 한도 초과는 `upload_too_large`(413)다.

1. 승인된 적용 절차에서 백업·복구 확인 후 `0047_http_upload_intake`까지 migration을 적용한다.
   이 구현 작업은 격리 합성 DB만 검증했으며 실사용 DB는 변경하지 않았다.
2. 위 원본 저장소와 아래 임시 저장소의 root·ID·binding·marker를 모두 준비한다.
   HTTP intake는 같은 전용 임시 저장소의 별도 UUID 작업공간을 사용한다.
   임시 설정 누락은 `http_intake_unavailable`(503)이며 미추적 저장소로 전환하지 않는다.
3. 같은 코드 버전의 API·worker를 적용한 뒤 합성 TXT의 신규 업로드와 새 버전을 확인한다.
   응답·조건부 job 전달을 확인하고 intake의 attached/cleaned 및 현재 출처 revision을 대조한다.

commit 응답 유실이나 파일 종료 확인 실패는 원장과 파일을 보존한다. 정리만 실패한 경우
이미 확정된 업로드의 성공 응답을 실패로 바꾸지 않는다. 원장 상태 수동 변경·시간 경과만으로
정리 완료를 선언하지 않는다. 과거 spool은 자동 회수하지 않으며 inventory의
`legacy_untracked`는 유지한다. 읽기 inventory 어댑터는 실제 영구 삭제를 활성화하지 않는다.

계약: [HTTP intake 설계](../superpowers/specs/2026-09-20-http-upload-intake-design.md).

### 문서 전용 임시 작업공간 활성화 전제

파싱과 PDF 원본 미리보기는 임시 파일 생성 전에 실제 source와 선택 job을 원장에 예약한다.
원본 object store와 다른 전용 root를 준비하며 앱이 기존 OS temp나 marker를 자동 인수하지 않는다.
설정 누락은 `temporary_storage_unavailable`(503), 파일 어댑터 문제는 안전한 작업 오류로 표시한다.
기존 text/Markdown 원문 읽기·다운로드에는 임시 저장소 설정이 필요하지 않다.

1. 승인된 적용 절차에서 백업·복구 확인 후 migration `0046_document_temporary`까지 적용한다.
   파일명은 `0046_document_temporary_workspaces.py`다. 검증에는 격리 합성 DB만 사용했다.
2. `AI_WORKSHOP_TEMPORARY_STORE_ROOT`, `AI_WORKSHOP_TEMPORARY_STORE_ID`,
   `AI_WORKSHOP_TEMPORARY_STORE_BINDING_ID`를 함께 지정한다. root는 승인된 전용 경로,
   ID는 소문자로 시작하는 80자 이하 machine identifier, binding은 새 UUID다.
3. root의 `.ai-workshop-temporary-store.json`에는 `schema_version`(정수 1), `store_id`,
   `binding_id`의 세 필드만 두고 설정과 정확히 맞춘다. 원본/RAG marker와 호환되지 않는다.
   애플리케이션은 root/marker를 자동 생성하지 않는다. 현재 mutation·관측 어댑터는 Windows 전용이다.
4. 같은 코드 버전의 API와 worker를 적용한 뒤 승인된 합성 문서로 parsing/PDF preview를 확인한다.
   정상 작업은 `open/1 → closed/2 → cleaning/3 → cleaned/4`와 현재 provenance revision이 함께 바뀐다.
   `cleaned`는 해당 UUID의 확인된 파일 부재이며 문서 전체 삭제 완료를 뜻하지 않는다.

OCR의 불투명 런타임은 반환/실패만으로 백그라운드 writer 종료를 증명하지 못하므로 **성공해도
open과 임시 파일을 보존한다**. PDF worker도 reap 실패·spawn 결과 불명은 open을 유지한다.
자동 재시작 복구나 시간 경과 정리는 없다. 미등록 하위 파일/경로 교체·정리 실패는 보존하고
`cleaning` 등 미완료 상태로 남는다. 원장 상태를 수동 변경해 정리 완료로 만들지 않는다.

미검증 runtime 외부 쓰기, 과거 OS temp/HTTP spool과 일반 Jobs 출처가 남아 있어 inventory는
보수적으로 incomplete를 반환한다. 런타임 종료 증명과 잔존 복구는 후속이며 실제 purge는 비활성이다.
기존 purge inventory 저장 경로의 document→version 잠금은 새 예약의 version→document와 반대다.
현재 제품 호출은 없으며 활성화 전에 잠금 순서 통합과 경쟁 검증을 완료해야 한다.
실사용 적용·백필·과거 임시 파일 제거는 코드 구현과 별도 작업이다.

## 4. RAG ingestion, 검색과 평가

### 추적 RAG 색인 활성화 전제

새 build는 migration `0042_rag_index_resources`와 아래 두 설정이 필요하다. 실사용 적용은
기존 writer를 중지·확인하고 migration 및 같은 버전의 API·worker·beat를 함께 배포하는
별도 작업이다. 코드 검증만으로 실사용 적용이 완료된 것은 아니다.

- `AI_WORKSHOP_RAG_INDEX_STORE_ID`: 소문자로 시작하는 소문자·숫자·밑줄 80자 이하의
  안정적인 논리 식별자(예: `rag_indexes`).
- `AI_WORKSHOP_RAG_INDEX_CLUSTER_UUID`: 승인된 ES endpoint의 정보 응답에서 확인한 실제
  `cluster_uuid`. UUID 표준 문자열을 새로 발급하는 설정이 아니다. 두 설정은 함께 지정한다.

새 build는 DB에 source·profile·정확한 concrete name·binding을 먼저 등록한다. ES UUID를
확인하면 bulk 전에 저장하고, prepare 완료와 시도 종료를 같은 DB 트랜잭션으로 확정한다.
cluster/UUID/입력 불일치 시 자동 인수·대체 저장소 전환을 하지 않는다. 기존 미추적 build는
legacy로 유지하며 현재 이름·환경 설정만으로 자동 등록하거나 삭제 준비 완료로 판단하지 않는다.

`rag_index_attempt_busy`는 다른 open prepare가 있다는 뜻이다. timeout·취소·통신 단절·DB
최종화 실패의 `rag_index_writer_unconfirmed`는 기존 시도를 열린 상태로 보존한다. lease 만료나
정상 count만으로 닫거나 새 writer에게 넘기지 않는다. 서버 종료가 확정된 부분 실패만 시도를
닫고 재시도할 수 있다. 원시 ES 오류·본문·접속 정보는 일반 오류에 포함하지 않는다.

현재 inventory는 읽기 대조만 제공한다. 별칭 원장과 문서 차단은 아래 절차를 따르며,
다른 참여자·구 writer·legacy 해소와 실제 삭제 실행기 통합 전에는 영구 삭제 API/UI를 활성화하지 않는다.
정확한 계약은 [색인 출처 설계](../superpowers/specs/2026-09-20-rag-index-provenance-design.md)를 따른다.

### 공유 별칭 요청과 문서 쓰기 차단

`0043_rag_alias_operations`와 `0044_rag_index_write_fences`는 별칭 요청과 문서별 차단을 저장한다.
activation과 parity 모두 위 store/cluster 설정을 요구하며, 기존 미추적 build의 별칭도 원장을 거친다.
구 API/worker/beat를 중지하고 진행 중 요청을 drain한 뒤 같은 버전으로 함께 적용해야 한다.
서로 다른 writer 버전이 섞인 실행은 종료 확인의 전제를 만족하지 않는다.

별칭 요청은 source/profile 잠금을 유지한 채 별도 DB 연결에서 먼저 예약한다. 미확인 요청이 있으면
현재 별칭이 일치해도 재전송하지 않는다. 정확한 승인 응답과 target 관찰을 받은 요청만 종료한다.
`rag_index_writer_unconfirmed`는 timeout·취소·불완전 응답·종료 기록 실패를 포함한다. 원장을 직접
닫거나 삭제하고 재시도하는 복구 절차는 제공하지 않는다. 정상 count·현재 별칭·시간 경과로 종료를 추정하지 않는다.

내부 `block_index_writes`는 exact workspace/document/generation에 영속 차단을 설정한다. 반복은 멱등이며
차단 해제 API는 없다. 차단한 문서는 새 ingestion·게시·prepare·READY 진입에서 거부되고 parity의 target에서
제외된다. 다른 문서는 유지한다. 이 호출 자체가 진행 중 요청을 종료하거나 물리 색인을 삭제하지 않는다.
`inspect_index_writers`는 해당 문서의 전체 버전/build와 prepare·alias 원장을 확인한다. legacy나 미확인 요청이
있으면 false다. true는 현재 지원하는 RAG 색인/별칭 writer 범위이며, 파일/OCR/외부 관리자·구 프로세스 또는
전체 삭제 완료 증명이 아니다. UI/API에서 호출하는 전체 purge 조립은 후속이다.

자세한 불변식과 잠금 순서는 [별칭·쓰기 차단 설계](../superpowers/specs/2026-09-20-rag-alias-write-fence-design.md)를 따른다.

### 추적 RAG 산출물 저장소 활성화 전제

추적 대상은 새 ingestion이 게시하는 parsed, chunks, embeddings JSON 묶음뿐이다. 기존
projection/job 파일, 원본 Asset, OCR 입력 이미지, Elasticsearch build와 다른 임시 파일은
이 저장소의 소유 자산으로 간주하지 않는다. 기존 미추적 projection을 파일명이나 현재 환경
설정만으로 자동 등록하거나 backfill하지 않으며, 인벤토리에서도 legacy 미해결 상태로 남긴다.

활성화는 다음 전제를 모두 충족한 별도 승인 작업이어야 한다.

1. 구 API와 worker의 신규 ingestion 진입을 막고 진행 중 writer를 drain한 뒤, API·worker·beat와
   직접 SQL/파일 writer가 모두 중지됐는지 확인한다. 종료가 입증되지 않은 open attempt나 남은
   등록 temp key가 있으면 timeout만으로 완료 처리하지 않고 활성화·정리를 중단한다.
2. DB migration과 새 API·worker 버전을 함께 준비한다. 추적 테이블만 먼저 사용하거나 구 writer를
   다시 시작하지 않는다.
3. 현재 구현은 별도의 RAG root 설정을 제공하지 않는다. 추적 adapter도 기존 원본 object store와
   같은 `AI_WORKSHOP_OBJECT_STORE_ROOT`를 사용하므로, 먼저 그 실제 구성 경로와 기존 원본
   object가 계속 접근 가능한지 확인한다. 빈 전용 경로로 임의 변경하거나 기존 object를 이동·추정
   backfill하지 않는다. 별도 물리 저장소가 필요하면 이 활성화 절차가 아니라 구성·이관 설계를 먼저
   승인받는다.
4. 안정적인 논리 이름(예: `rag_ingestion_artifacts`)은
   `AI_WORKSHOP_RAG_ARTIFACT_STORE_ID`에 설정한다. 이 값은 소문자로 시작하는 소문자·숫자·밑줄
   80자 이하의 정확한 machine identifier다. 운영 절차에서 새로 발급한 UUID는 이 이름과 다른
   값이며 `AI_WORKSHOP_RAG_ARTIFACT_STORE_BINDING_ID`에 설정한다.
5. 애플리케이션 시작 전에 실제 `AI_WORKSHOP_OBJECT_STORE_ROOT`에
   `.ai-workshop-store.json`을 아래의 정확한 스키마로 별도 provisioning한다. marker의
   `store_id`는 STORE_ID와, `binding_id`는 STORE_BINDING_ID와 각각 정확히 같아야 한다.

```json
{
  "schema_version": 1,
  "store_id": "rag_ingestion_artifacts",
  "binding_id": "00000000-0000-4000-8000-000000000000"
}
```

위 UUID는 형식 예시일 뿐 재사용할 운영 값이 아니다. 애플리케이션과 migration은 marker를 자동
생성·수정하지 않는다. marker 부재·불일치·손상, 다른 실제 경로나 reparse 경로, 미확인 writer가
하나라도 있으면 새 추적 ingestion과 완전한 삭제 인벤토리를 준비 완료로 간주하지 않는다.

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

### 비공개 Learning 스키마와 검증

Learning 1단계는 `0024_learning_records`에서 사용자별 현재 기록과 불변 revision 테이블을
추가한다. 구현·격리 DB 검증과 실행 중인 개발 DB 반영은 별도 단계다. 현재 반영 여부는
`WORKBOARD.md`를 확인하며, 화면 파일이 존재한다는 이유로 migration 완료를 추정하지 않는다.

Windows에서는 저장소 루트에서 기존 `.env`를 사용해 현재 버전을 먼저 확인한다.

```powershell
backend/.venv/Scripts/python.exe -c "import asyncio; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); from alembic.config import main; main(argv=['-c','backend/alembic.ini','current'])"
```

개발 DB 반영이 승인되고 현재 버전이 `0023_rag_domains`인지 확인된 경우에만 같은 루트에서
명시적으로 `0024_learning_records`까지 upgrade한다. 임의 downgrade는 학습 기록을 제거하므로
복구 수단으로 실행하지 않는다. 적용 뒤 current와 기존 서비스 응답을 다시 확인한다.

```powershell
backend/.venv/Scripts/python.exe -c "import asyncio; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); from alembic.config import main; main(argv=['-c','backend/alembic.ini','upgrade','0024_learning_records'])"
```

단위·계약 검사는 외부 모델 없이 실행한다. DB 검사는 `learning_support.py`가 생성하고 정확한
이름을 검증한 `ai_workshop_learning_<UUID>` 전용 DB만 사용한다. 개발 DB를 truncate/reset하지 않는다.

```powershell
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/platform/learning backend/tests/contract/test_learning_api.py -q
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/integration/test_learning_persistence.py backend/tests/integration/test_migration_0024_learning_records.py backend/tests/integration/test_learning_lifecycle.py -q -m integration
pnpm --dir frontend test --run src/features/learning 'src/app/(workspace)/workshop/learning' src/features/navigation src/shared/routing/routes.test.ts --pool=threads --maxWorkers=1 --reporter=verbose
```

DB lifecycle은 실제 API·서비스·SQL 저장과 RAG 참조 권한을 검증한다. 프론트 lifecycle은
실제 컴포넌트와 HTTP mock을 연결한 검사이며 실제 브라우저 E2E가 아니다. migration 적용 후
`/workshop/learning`에서 메모 저장→재조회→실험 전환→이력→보관→복원을 별도로 확인한다.

학습 기록은 로그인 사용자별 비공개 데이터다. 보관·복원과 revision 조회만 제공하고 영구 삭제,
공개 게시, 모델 호출·훈련을 실행하지 않는다. API 응답은 접근 불가 참조를 편집용 draft에서 제외하되
저장 이력은 보존한다. 이 draft를 다시 저장하면 해당 연결이 빠지므로 UI의 확인 안내를 따라야 한다.

## 6. 테스트와 품질 검사

### Publishing 기반 계약 검사

공개 기록 관리의 첫 구현은 package·승인·철회 순서를 검증하는 순수 Python 계약이다.
관리자 UI·게시 API·공개 저장소는 아직 연결하지 않았다. `backend`에서 다음을 실행한다.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/platform/publishing -q
.venv/Scripts/python.exe -m ruff check src/ai_workshop/platform/publishing tests/unit/platform/publishing
.venv/Scripts/python.exe -m mypy src/ai_workshop/platform/publishing
```

이 검사는 DB·모델·실제 인증 키가 필요 없다. 전체 unit/contract 검사는 기존 인증 Settings를
초기화하는 테스트를 포함한다. 환경 파일을 읽지 않는 독립 테스트 터미널에서는
`$env:AI_WORKSHOP_SECRET_KEY = ('offline-test-' * 4)`처럼 합성 테스트 키만 지정한다.
이 값을 앱 서버나 운영 설정에 사용하지 않는다. 검증 범위와 결과는
[Publishing 작업 기록](../worklogs/2026-09-08-publishing-contracts.md)에 남긴다.

빠른 로컬 검사는 아래처럼 단위 테스트 경로를 명시한다. `integration` marker는 서비스 연결
허가나 DB 격리를 보장하지 않는다. 전체 `pytest`를 실사용 `.env`로 실행하지 않는다.
일부 기존 통합 테스트가 앱 DB에 fixture를 commit하는 문제가 확인됐으며,
격리 보완 범위와 증거는 [RAG 테스트 격리 기록](../worklogs/2026-09-09-rag-test-isolation.md)을 따른다.
전체 integration 격리 검증이 끝나기 전에는 검토된 파일·전용 자원 경계만 명시해 실행한다.

```powershell
cd backend
uv lock --check
uv run pytest tests/unit -q
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

백엔드 이미지를 변경했으면 build check와 실제 image footprint 회귀 검사를 함께 실행한다.
Core는 512 MiB, embedding API는 2 GiB, OCR worker는 4 GiB 이하를 요구한다. 세 운영 target은
내장 uv cache, 개발 도구와 테스트 소스가 없어야 하며 embedding target에는 CPU-only torch만,
OCR target에는 CPU-only torch와 고정 Paddle package만 있어야 한다.

```powershell
docker buildx build --check -f backend/Dockerfile backend
docker compose -f infrastructure\compose\compose.yaml build object-store-init api worker
.\scripts\verify-backend-image-footprint.ps1 -Image ai-workshop-backend:local -MaximumImageBytes 536870912 -ExpectedEmbeddingRuntime absent
.\scripts\verify-backend-image-footprint.ps1 -Image ai-workshop-backend-embedding-cpu:local -MaximumImageBytes 2147483648 -ExpectedEmbeddingRuntime cpu
.\scripts\verify-backend-image-footprint.ps1 -Image ai-workshop-backend-ocr-cpu:local -MaximumImageBytes 4294967296 -ExpectedEmbeddingRuntime cpu -ExpectedOcrRuntime cpu
docker compose -f infrastructure\compose\compose.yaml build e2e ocr-linux-cpu-smoke
.\scripts\verify-backend-image-footprint.ps1 -Image ai-workshop-backend-test:local -MaximumImageBytes 2362232012 -ExpectedEmbeddingRuntime cpu -ExpectedDevelopmentRuntime present -ExpectedTestSources present
.\scripts\verify-backend-image-footprint.ps1 -Image ai-workshop-backend-ocr-test:local -MaximumImageBytes 3758096384 -ExpectedEmbeddingRuntime cpu -ExpectedOcrRuntime cpu -ExpectedDevelopmentRuntime present -ExpectedTestSources present
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

### Windows 스캔 PDF OCR

Migration `0021_pdf_ocr_profile`은 `pp-structure-v3-pdf-docx` v1을, `0022_mixed_pdf_ocr_profile`은
혼합 페이지를 지원하는 같은 이름의 v2를 draft·비기본으로 등록한다.
관리자 RAG 구성에서 이 문서 처리 프로파일을 선택해 새 저장 구성 버전을 만든다.
기존 구성은 자동 변경되지 않는다. 프로파일 변경은 새 Projection·색인이 필요하다.
Windows 호스트 API·worker를 최신 코드로 실행하고 기존 10개 모델 무결성을 확인한다.
별도 Linux 서버는 필요 없다.

관리자 상세 화면은 선택한 `pymupdf-ocr` 버전, 144 DPI, 페이지당 16,000,000 pixels,
최대 200 pages와 PP-StructureV3 구성을 표시한다. 변경은 새 프로파일 버전으로 한다.
v1은 텍스트 없는 페이지만 OCR한다. v2는 본문 직접 추출과 이미지 영역 OCR을 함께 수행하며
동일 위치의 중복 OCR은 `pdf_ocr_native_duplicate` 경고로 남기고 근거에서 제외한다.
글자 없는 장식 이미지는 정상 처리하되 런타임 실패는 전파한다. 낮은 confidence는 근거에서
제외하고 하이라이트는 OCR 요소 bbox를 사용한다. 기존 v1 구성은 자동 변경되지 않는다.

실제 모델 smoke는 backend 디렉터리에서 실행한다. 검증된 로컬 모델만 사용한다.

```powershell
$env:AI_WORKSHOP_PDF_OCR_ACTUAL_SMOKE='1'
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True'
.\.venv\Scripts\python.exe -m pytest tests/integration/labs/rag/ocr/test_scanned_pdf_smoke.py -q
```

`pdf_processing_limit_exceeded`는 입력 분할 또는 제한 프로파일 재평가가 필요하다.
`pdf_ocr_empty`는 추출 결과가 없다는 뜻이다. `ocr_model_artifact_missing`,
`ocr_runtime_unavailable`, `ocr_output_invalid`는 모델 파일·런타임·출력 계약을 확인한다.
실패 시 다른 모델로 전환하지 않으며 임시 PNG는 성공·실패 모두 정리한다.

혼합 페이지의 실제 업로드·색인·검색 API 검증은 저장소 루트에서 별도로 실행한다.
기존 PostgreSQL·Elasticsearch 인스턴스에 고유 임시 DB와 색인을 만들고 종료 시 정리한다.
모델은 기존 로컬 캐시를 읽는다. 사용자 DB·저장 구성은 변경하지 않는다.

```powershell
$env:AI_WORKSHOP_MIXED_PDF_ACTUAL_SMOKE='1'
backend\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml backend/tests/e2e/test_rag_mixed_pdf_actual.py -q --tb=short
```

기본 모드는 실제 OCR·E5·Elasticsearch와 API를 사용하고 worker workflow를 직접 실행한다.
Redis/Celery 전달도 검증하려면 위 호스트 실행 절차의 `.env` 로드 후
`AI_WORKSHOP_MIXED_PDF_ACTUAL_QUEUE=1`을 추가한다. 테스트가 고유 queue·Redis keyprefix와
별도 host worker를 만들고 종료한다. 기존 개발 worker·beat는 중지하지 않는다.
Windows에서는 `--basetemp`를 해당 작업의 짧은 전용 경로로 지정한다. 생성 파일은 검증 후
정확한 경로별로 정리하며 사용자 객체 저장소를 basetemp로 지정하지 않는다.
두 모드 모두 브라우저 상호작용과 외부 LLM 생성은 검증 범위가 아니다. 실제 큐 모드도
ingestion command 생성은 서비스에서 수행하므로 관리자 구성 UI 전체 검증을 대체하지 않는다.
모델·DB·색인 오류가 있으면 실패하며 다른 모델로 대체하지 않는다.

### 도메인 대화 등록과 확인

도메인 선택형 대화의 설계·구현 상태와 검증 범위는
[작업 기록](../worklogs/2026-09-07-domain-first-rag-conversation.md)을 확인한다.

1. migration `0023_rag_domains` 이상을 적용하고 API를 현재 코드로 실행한다. 도메인 예시는
   자동 생성되지 않으며 기존 문서도 자동 분류되지 않는다.
2. owner로 `/admin/rag/domains`에서 도메인 표시명·고유 slug·설명을 등록한다. 저장 RAG 구성의
   정확한 버전과 해당 구성에 연결된 공간을 선택해 서비스 연결 버전을 만든다.
3. 평가를 통과하고 생성형 답변·색인·런타임이 준비된 연결을 명시적으로 활성화한다. 준비
   오류가 나면 기존 `/admin/rag/configurations`와 모델 관리에서 원인을 확인한다. DB 상태를
   직접 바꾸거나 미준비 모델을 다른 모델로 대체하지 않는다.
4. 로그인 사용자로 `/workshop/rag/search`에서 도메인을 선택한다. 실제 허용 공간은
   도메인·구성·현재 사용자 권한의 교집합이다. 도메인에 연결해도 문서 권한이 새로 생기지 않는다.
5. 대화 안에서 공간·폴더를 조정한다. 공간을 모두 해제하면 전송할 수 없고, 폴더를 선택하지
   않으면 선택 공간 전체를 검색한다. 범위 변경 후에는 이전 대화를 새 LLM 문맥에 넣지 않는다.
6. 답변의 인용에서 원문과 하이라이트를 확인한다. 연결 버전 변경·비활성화·권한 회수 오류가
   표시되면 도메인 목록으로 돌아가 현재 연결로 새 대화를 시작한다. 새로고침 시 대화는 초기화된다.

외부 모델 전송은 기존 저장 구성의 승인 정책을 계속 적용한다. 화면의 전송 안내 확인은
관리자의 저장 승인·데이터 분류 검사를 대체하지 않는다. 실제 API 호출 검증은 외부 전송과
비용 승인을 별도로 받은 뒤 수행한다. 이번 단계에는 공개 검색·인라인 첨부·피드백 저장이 없다.

Windows 프론트 테스트의 순차 jsdom 준비와 출력 지연이 길면 다음 명령으로 진행 상황을
확인한다. 실행 중이라는 이유만으로 실패 판정하지 말고 종료 코드와 요약을 확인한다.

```powershell
cd frontend
node node_modules/vitest/vitest.mjs run --pool=threads --maxWorkers=1 --reporter=verbose
```

### 일반 실행 오류

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
