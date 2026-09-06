# Linux OCR 런타임·관리자 Docker 구성도 설계

- 상태: 승인됨
- 기준일: 2026-09-06
- 범위: PP-StructureV3 Linux CPU 런타임, CPU/GPU 호환성 경계, owner 전용 Docker 구성도
- 관련 설계: `docs/superpowers/specs/2026-09-06-rag-document-processing-ocr-profile-design.md`
- 관련 결정: `docs/decisions/0013-separate-ocr-runtime-and-safe-topology.md`

## 1. 배경과 목표

현재 단일 backend image를 FastAPI API, Celery worker와 beat가 함께 사용한다. core dependency에는
OCR extra가 포함되지 않으므로 Docker worker에서 PP-StructureV3를 실제 실행할 수 없다. 반대로
OCR dependency를 모든 backend process에 설치하면 API와 beat까지 불필요하게 커지고 취약점·빌드
캐시·배포 비용이 증가한다.

이 설계는 다음을 목표로 한다.

- core, CPU embedding API, CPU embedding+OCR worker와 test image를 같은 Dockerfile의 명시적
  target으로 분리한다.
- 공식 CPU package 범위에 맞춰 API, OCR worker와 test target을 `linux/amd64`로 고정한다.
- Windows에서 검증한 정확한 10개 모델 매니페스트를 Linux CPU에서도 네트워크 없이 검증한다.
- 같은 모델 artifact를 쓰는 Linux GPU 경계를 정의하되, GPU engine과 실제 하드웨어를 검증하지
  않은 상태를 성공으로 표시하지 않는다.
- owner가 `/admin/system/runtime`에서 Docker Compose의 전체 논리 구성을 안전하게 확인한다.
- 실행용 Compose와 화면용 안전 매니페스트가 달라지면 자동 테스트가 실패한다.
- Docker socket, 비밀값, 내부 endpoint와 host 절대 경로를 애플리케이션에 노출하지 않는다.

## 2. 채택 방식과 대안

### 채택: multi-target image + 안전 토폴로지 계약

하나의 `backend/Dockerfile`에서 공통 application layer를 공유하고 최종 target을 분리한다.

- `runtime-core`: embedding·OCR·개발 도구가 없는 beat, migration, model registry
- `runtime-embedding-cpu`: CPU-only torch와 sentence-transformers를 포함하는 API
- `runtime-ocr-cpu`: CPU embedding과 고정 CPU OCR dependency를 포함하는 Celery worker
- `runtime-test`, `runtime-ocr-test`: profile 전용 개발 도구와 테스트 소스

Docker Compose는 실제 배포 선언의 정본이다. 관리자 API는 Compose 원문을 읽지 않고 backend
package에 포함된 버전형 안전 토폴로지 매니페스트를 읽는다. 계약 테스트가 두 선언의 서비스,
image target, 의존 관계와 논리 저장소를 비교해 drift를 차단한다.

이 방식은 Compose secret과 환경변수를 API가 해석하는 위험을 없애면서 관리자 설명을
데이터 기반으로 유지한다.

### 비채택: 모든 process에 OCR 설치

구성은 단순하지만 API·beat에 필요 없는 Paddle runtime과 OCR package가 포함된다. image 용량,
빌드 시간과 공격 표면이 늘어나므로 채택하지 않는다.

### 비채택: Docker Engine socket으로 실시간 조회

실행 중 container 상태를 정확히 볼 수 있지만 애플리케이션에 host 제어 권한을 부여한다.
구성 확인 목적에 비해 권한이 과도하므로 채택하지 않는다.

### 비채택: frontend에서 Compose YAML 직접 읽기

Next.js 배포 경로와 저장소 구조에 결합되고 owner 권한·응답 allowlist를 backend에서 일관되게
적용할 수 없다. 또한 raw 환경 설정 노출 위험이 있어 채택하지 않는다.

## 3. 런타임 이미지 경계

```text
backend/Dockerfile
└─ application-base (production dependencies only)
   ├─ runtime-core
   └─ embedding-base (explicit PyTorch CPU index)
      ├─ runtime-embedding-cpu
      ├─ runtime-test
      └─ ocr-base
         ├─ runtime-ocr-cpu
         └─ runtime-ocr-test
```

모든 target은 같은 Python 3.13 application source와 lock을 사용한다. embedding은
`embedding-cpu`, OCR은 `ocr-cpu` extra로 분리한다. torch는 explicit PyTorch CPU index에
고정하고 CUDA·NVIDIA·Triton package를 운영 image에서 금지한다. 기존 모호한 `ocr` extra를
병행 유지하지 않는다.

Dockerfile의 마지막 stage는 `runtime-core`로 두어 target을 생략한 기존 build가 무거운 OCR
image로 바뀌지 않게 한다. Compose의 각 build에는 target을 명시해 암묵적 stage 선택에
의존하지 않는다.

core image에는 sentence-transformers, torch, Paddle와 개발 도구가 없어야 한다. Embedding
CPU image는 `torch==2.13.0+cpu`를 사용하고 NVIDIA package와 Triton이 없어야 하며, OCR CPU
image에는 세 Paddle package의 정확한 버전과 CPU engine이 존재해야 한다. 운영 image에는
`/app/tests`를 복사하지 않는다. 이 경계를 image contract test로 검증한다.

## 4. Compose 서비스와 저장소 구성

기본 Compose 구성은 다음처럼 표시하고 실행한다.

```text
api [runtime-embedding-cpu]
├─ postgres
├─ redis
├─ elasticsearch
├─ object-data volume
└─ model-cache volume

worker [runtime-ocr-cpu]
├─ postgres
├─ redis
├─ elasticsearch
├─ object-data volume
└─ model-cache volume

beat [runtime-core]
├─ postgres
├─ redis
└─ elasticsearch
```

관리자 구성도는 다음 종류를 구분한다.

- 상시 process: `api`, `worker`, `beat`
- 기반 service: `postgres`, `redis`, `elasticsearch`
- 초기화 job: `object-store-init`
- on-demand tool: `migrate`, `model-tools`, `e2e`, Linux OCR smoke
- 논리 저장소: `object-data`, `model-cache`, `postgres-data`, `redis-data`,
  `elasticsearch-data`

`object-data`는 현재 별도 object-store container가 아니라 backend local object-store adapter가
사용하는 named volume이라고 명시한다. 로컬 Next.js frontend는 Docker Compose 기본 구성에
포함되지 않으므로 구성도 밖의 `호스트 실행` 경계로 표시한다.

service마다 안정적인 논리 ID, 표시명, 종류, image target, process 역할, dependency ID,
storage ID, OCR capability, 기본/도구 profile 여부와 healthcheck 구성 여부를 제공한다.

Windows CPU, Linux CPU와 Linux GPU의 검증 상태는 Compose service node와 분리된
`runtime compatibility lane`으로 제공한다. 따라서 Linux GPU가 실제 Compose service인 것처럼
표현되지 않으며, 현재 CPU worker의 검증 상태와 GPU 미검증 상태를 동시에 정확히 표시할 수 있다.

## 5. Linux CPU 실제 smoke

Linux CPU smoke는 `runtime-ocr-test` image를 사용한 명시적 Compose profile로 실행한다.
일반 `docker compose up`에는 포함하지 않고 exact service를 지정하거나 `ocr-smoke` profile을
선택했을 때만 실행한다.

smoke 입력은 공개·합성 fixture로 제한한다. Windows의 한국어 font에 의존하지 않는 영문·숫자
텍스트와 표를 생성하고 다음을 실제 PP-StructureV3 결과에서 확인한다.

- 고정 10개 model directory가 매니페스트의 revision과 SHA-256에 일치한다.
- pipeline이 외부 다운로드 없이 초기화된다.
- text와 table cell이 기대 문자열로 인식된다.
- 정규화 bbox가 원본 image 범위 안에 있다.
- 실행 snapshot의 OS는 Linux, device는 CPU, package version은 고정값이다.

model cache는 worker와 공유하는 named volume을, model profile은 bind mount를 각각 read-only로
제공한다. container는 `network_mode: none`, non-root user와 read-only model mount로 실행하고 결과·pytest 임시물은
container의 임시 쓰기 영역만 사용한다. 모델이 누락되거나 해시가 다르면 다운로드로 복구하지
않고 smoke를 실패시킨다. Windows bind mount가 POSIX mode를 잘못 보존할 수 있으므로 승인된
초기화 단계는 `model-tools`를 통해 내용·해시를 검증한 뒤 named volume에 표준 권한으로 설치한다.

Windows 한국어 smoke와 Linux CPU smoke는 서로 다른 보완 증거다. Linux 합성 fixture 통과가
Windows 한국어 품질 검증을 대체하지 않는다.

## 6. Linux GPU 호환성 경계

PP-StructureV3의 model artifact, pipeline 의미 설정, 전처리와 출력 schema는 CPU/GPU가
공유한다. 그러나 실행 engine은 공유하지 않는다.

- CPU: `paddlepaddle==3.2.2`
- GPU: `paddlepaddle-gpu`와 선택한 CUDA wheel channel

두 engine을 한 Python 환경에 함께 설치하지 않는다. GPU image는 NVIDIA driver, CUDA wheel
channel, architecture와 실제 GPU가 확정된 별도 승인 작업에서 `runtime-ocr-gpu` target으로
추가한다. 현재 작업에서는 CPU image에 GPU device만 연결하거나 GPU 성공을 가정하는 Compose
service를 만들지 않는다.

관리자 화면은 GPU를 `별도 런타임 필요 · 미구현/미검증`으로 표시한다. 향후 GPU 작업의 완료
게이트는 다음과 같다.

- exact `paddlepaddle-gpu` version과 CUDA channel을 lock한다.
- Docker Compose GPU device reservation과 host driver 전제조건을 검증한다.
- 같은 10개 model artifact로 text·table·bbox 실제 추론을 통과한다.
- CPU와 GPU의 품질 차이, 처리 시간과 peak memory를 별도 evaluation snapshot으로 남긴다.
- 검증 전에는 GPU를 기본 worker나 운영 승인 상태로 승격하지 않는다.

## 7. 안전 토폴로지 매니페스트

화면용 계약은 다음 package resource에 둔다.

`backend/src/ai_workshop/platform/runtime_topology/runtime-topology-v1.yaml`

이 파일은 다음 allowlist 필드만 포함한다.

- `schema_version`, `topology_version`, `environment_kind`
- node의 `id`, `display_name`, `kind`, `runtime_target`, `process_role`
- `dependencies`, `storages`, `capabilities`, `activation`
- `healthcheck_declared`
- storage의 `id`, `display_name`, `purpose`, `persistence`
- compatibility lane의 `id`, `display_name`, `device`, `runtime_target`,
  `verification_state`, `verification_note`

다음 데이터는 매니페스트와 API 응답에 포함하지 않는다.

- environment variable 이름과 값
- password, token, secret reference
- database DSN, 내부 hostname, endpoint와 host port
- host 절대 경로와 volume의 Docker 내부 물리 경로
- raw Compose YAML, container ID와 Docker socket 정보

Compose와 매니페스트는 서로 다른 목적의 선언이므로 drift test가 필수다. 테스트는 Compose를
안전한 typed 구조로 parsing한 뒤 기본/도구 service ID, build target, `depends_on`, named volume
참조와 profile 분류가 매니페스트의 node와 일치하는지 확인한다. compatibility lane은 Compose
service로 취급하지 않고 허용된 device·runtime target·검증 상태 조합을 별도로 검증한다.
환경변수 값과 secret은 비교하거나 snapshot하지 않는다.

## 8. Backend API

새 모듈은 `Platform`에 둔다.

```text
backend/src/ai_workshop/platform/runtime_topology/
├─ api.py
├─ domain.py
├─ schemas.py
├─ service.py
└─ runtime-topology-v1.yaml
```

`GET /api/v1/admin/system/runtime-topology`는 `require_owner`를 적용한다. database write나 새
영속 table은 만들지 않는다. service는 package resource를 load하고 schema를 fail closed로
검증한 뒤 typed response로 반환한다.

응답 상태는 다음을 구분한다.

- `configured`: 매니페스트에 선언되고 drift contract가 검증된 구성
- `responding`: 현재 API process처럼 애플리케이션이 직접 관찰한 상태
- `not_observed`: worker, beat와 기반 service처럼 Docker socket 없이 live 상태를 알 수 없음
- `unverified`: Linux GPU처럼 compatibility gate를 통과하지 않음

정적 healthcheck 선언을 live `healthy`로 표현하지 않는다. 첫 버전에서 API 이외 node의 실제
container 상태를 추측하지 않으며, 필요하면 향후 각 adapter의 안전한 readiness port를 별도
설계한다.

service는 요청에 응답 중인 API node에만 `responding` observation을 덧씌운다. 나머지 node는
`not_observed`를 반환하고, 별도 compatibility lane은 매니페스트의 검증 상태를 그대로 반환한다.

비로그인 요청은 401, owner가 아닌 로그인 사용자는 403이며 두 경우 모두 토폴로지 내용을
반환하지 않는다. 오류 응답에는 package path나 YAML 원문을 넣지 않는다.

## 9. 관리자 화면

canonical route는 `/admin/system/runtime`이다. RAG 모델 구성 화면 안에 넣지 않는다. Docker
runtime은 여러 Labs가 공유할 Platform 운영 정보이기 때문이다.

화면은 다음 순서로 구성한다.

1. `실행 환경 요약`: Compose 환경, topology version, core/OCR image 분리와 현재 검증 경계
2. `서비스 흐름`: API, OCR worker, beat와 PostgreSQL·Redis·Elasticsearch 의존 관계
3. `이미지 구성`: runtime target별 포함 capability와 OCR dependency 여부
4. `데이터 보존`: named volume의 논리 목적과 영속 여부
5. `도구 및 검증`: init/migrate/model-tools/e2e/Linux CPU smoke와 GPU 미검증 상태
6. `보안 경계`: Docker socket 미사용, network-off smoke, secret·endpoint 비노출

화면은 API의 typed metadata를 렌더링하며 service 이름, 모델명 또는 package version을 TSX에
하드코딩하지 않는다. node별 badge로 `구성됨`, `응답 중`, `관찰 안 함`, `미검증`을 구분하고
`관찰 안 함`을 장애처럼 표시하지 않는다.

관리자 navigation에 `시스템 런타임` 링크를 추가한다. 기존 `/admin/rag/configurations`와
`/admin/rag/models`는 RAG profile과 model 관리 책임을 유지한다.

## 10. TDD와 검증 전략

구현은 Red → Green → Refactor 순서를 따른다.

### Docker·dependency contract

먼저 실패하는 테스트로 다음을 고정한다.

- `runtime-core`에는 embedding·Paddle·개발 package와 테스트 소스가 없다.
- API는 CPU-only `runtime-embedding-cpu`, worker는 `runtime-ocr-cpu`, beat는 core를 사용한다.
- 운영 embedding target에는 CUDA·NVIDIA·Triton package가 없다.
- image의 uv cache가 비어 있고 non-root/data ownership 기존 계약이 유지된다.
- 안전 매니페스트와 Compose의 service·target·dependency·volume/profile이 일치한다.

### Backend API contract

- 매니페스트가 typed domain으로 parse되고 알 수 없는 field와 잘못된 참조를 거부한다.
- 비밀·endpoint·절대 경로 필드가 schema에 존재하지 않는다.
- owner는 전체 safe topology를 읽고 비로그인은 401, 일반 사용자는 403을 받는다.
- OpenAPI schema가 frontend 생성 타입과 일치한다.

### Frontend contract

- route loader가 owner 세션으로 API를 호출한다.
- 서비스·image·storage·검증 상태가 API 데이터에서 표시된다.
- GPU 미검증과 object-data의 volume 성격을 오인 없이 안내한다.
- API 오류는 기존 admin error boundary로 안전하게 표시된다.
- navigation과 canonical route 테스트가 통과한다.

### 실제 smoke와 회귀

- Dockerfile/Compose 정적 계약
- core/CPU OCR image build와 package import 부정·긍정 확인
- Linux CPU network-off 실제 OCR smoke
- backend unit/API/contract, Ruff, mypy
- frontend unit, TypeScript, ESLint, OpenAPI, Next production build
- 기존 backend image footprint 검증과 OCR image 별도 용량 기록

GPU 실제 smoke는 현재 완료 주장 대상이 아니다. 실행 가능한 NVIDIA host와 승인된 GPU engine
image가 없으면 `미검증`이 정상 결과다.

## 11. Docker 캐시와 용량 정책

운영 image는 application layer를 공유하고 uv cache mount를 image layer에 복사하지 않는다.
검증 상한은 실제 측정에 근거해 core 512 MiB, embedding 2 GiB, OCR 4 GiB로 둔다. profile 전용
test image는 운영 배포 대상이 아니며 검증 종료 뒤 정확한 참조 상태를 확인해 정리할 수 있다.

build가 새 image와 cache를 만들더라도 자동 prune하지 않는다. 작업 전후 `docker system df -v`,
project image ID와 BuildKit record를 조사하고 `CACHE_POLICY.md`의 정확 대상·승인·사후 검증
절차를 따른다. named volume과 model cache는 삭제 대상이 아니다.

관리자 화면은 논리적인 영속성·용도만 설명하고 host 실제 디스크 용량이나 다른 프로젝트의
Docker 자산을 조회하지 않는다.

## 12. 수용 기준

1. 기본 Compose의 API는 `runtime-embedding-cpu`, beat는 `runtime-core`, worker는
   `runtime-ocr-cpu`를 사용한다.
2. core image에는 ML engine이 없고 embedding·OCR 운영 image에는 CPU package만 있다.
3. Windows와 Linux CPU가 같은 10개 model revision·SHA-256 매니페스트를 사용한다.
4. Linux CPU actual smoke가 network-off/read-only model 조건에서 text·table·bbox를 통과한다.
5. model 누락·해시 불일치는 자동 다운로드 없이 명시적으로 실패한다.
6. GPU는 같은 model artifact를 재사용하지만 별도 engine/image/evaluation이 필요하다고 표시된다.
7. GPU actual smoke 전에는 관리자 화면과 문서가 GPU를 `미검증`으로 표시한다.
8. owner만 `/api/v1/admin/system/runtime-topology`와 `/admin/system/runtime`에 접근한다.
9. 화면에서 기본 service, 기반 service, tool job과 모든 named volume의 논리 구성을 확인한다.
10. raw Compose, secret, endpoint, host path, container ID와 Docker socket 정보는 노출되지 않는다.
11. 매니페스트와 Compose가 drift하면 자동 테스트가 실패한다.
12. 화면은 live 상태를 추측하지 않고 `responding`과 `not_observed`를 구분한다.
13. 기존 RAG 관리 화면, ingestion, worker schedule과 core image footprint 계약이 회귀하지 않는다.
14. 생성된 Docker cache 정리는 `CACHE_POLICY.md` 승인 절차 없이는 수행하지 않는다.

## 13. 구현 순서

1. 안전 토폴로지 domain/schema와 Compose drift contract
2. Dockerfile core·embedding CPU·OCR CPU·test target과 dependency 경계
3. Compose worker target, Linux CPU smoke profile와 image 검증
4. owner 전용 Platform runtime topology API와 OpenAPI 계약
5. `/admin/system/runtime` 화면과 navigation
6. Linux CPU actual smoke, 전체 회귀, image/cache 용량 기록과 작업 문서

## 14. 제외 범위

- Linux GPU image와 actual GPU inference 성공 주장
- CUDA channel 또는 NVIDIA driver를 임의로 선택하는 작업
- Docker Engine socket mount와 실시간 container 제어
- container 시작·중지·재시작·삭제 UI
- raw environment, secret, endpoint, port와 host path 표시
- Kubernetes, cloud orchestration과 다중 host topology
- 스캔 PDF rasterizer 구현

## 15. 근거 문서

- Docker Compose build `target`: https://docs.docker.com/reference/compose-file/build/
- Docker multi-stage build: https://docs.docker.com/build/building/multi-stage/
- Docker Compose profiles: https://docs.docker.com/compose/how-tos/profiles/
- Docker Compose GPU 지원: https://docs.docker.com/compose/how-tos/gpu-support/
- PaddleOCR PaddlePaddle 설치: https://www.paddleocr.ai/latest/en/version3.x/paddlepaddle_installation.html
