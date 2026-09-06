# Linux OCR 런타임·관리자 시스템 구성도 구현 기록

- 기준일: 2026-09-06
- 구현 상태: 완료
- Linux CPU actual smoke: native x86_64 재검증 필요

## 구현 결과

- backend image를 `runtime-core`와 `runtime-ocr-cpu` target으로 분리했다.
- API·beat·도구는 core, OCR worker와 smoke만 CPU OCR target을 사용한다.
- PaddlePaddle 공식 지원 경계에 맞춰 OCR build와 실행을 `linux/amd64`로 고정했다.
- `paddlepaddle==3.2.2`, `paddleocr==3.7.0`, `paddlex[ocr]==3.7.2`와
  `libgl1`, `libglib2.0-0`, `libgomp1`을 OCR image에만 설치한다.
- 10개 고정 모델을 크기·SHA-256으로 검증해 `model-cache` named volume에 준비하는
  `ai-workshop provision-rag-ocr-models` 명령을 추가했다.
- smoke는 비루트 사용자, `network_mode: none`, read-only model/profile mount로 실행한다.
- 안전 토폴로지 manifest와 Compose의 service, image target, dependency, storage, profile
  drift를 자동 테스트한다.
- owner 전용 `/api/v1/admin/system/runtime-topology`와 `/admin/system/runtime`를 추가했다.
  API는 allowlist metadata만 반환하고 Docker socket, raw Compose, secret, endpoint, host path를
  읽거나 노출하지 않는다.

## TDD와 발견한 문제

1. manifest parser, Compose drift, owner API, admin route/UI, portable OCR fixture, artifact 권한과
   CLI 계약을 실패 테스트로 먼저 확인했다.
2. Windows bind cache에 원본 권한 metadata가 복제되어 파일 mode가 `000`이 된 문제를
   발견했다. 프로비저너를 내용 복사 후 디렉터리 `0755`, 파일 `0644`로 정규화하도록 바꿨고
   회귀 테스트 6개가 통과했다.
3. 기존 손상 host cache는 현재 Windows 계정에 소유권 복구 권한이 없어 삭제·우회하지 않고
   보존했다. 접근 가능한 승인 staging을 검증해 기존 Docker `model-cache` 볼륨에 설치했다.
4. ARM64 image에서는 PP-DocLayout 모델 초기화 중 Paddle native `SIGSEGV`가 재현됐다. 공식
   설치 가이드는 CPU 아키텍처를 x86_64로 제한하므로 OCR build와 실행을 AMD64로 고정했다.
5. AMD64 import에서 누락된 `libgomp.so.1`을 발견해 `libgomp1`을 OCR target에 추가했다.
6. 접근 불가능한 artifact에서 운영체제 예외와 실제 경로가 그대로 노출될 수 있는 경계를
   발견했다. 이를 경로 비노출 도메인 오류로 변환하고 회귀 테스트를 추가했다.

## 검증 증거

- 집중 backend: `28 passed, 3 skipped`
- 전체 backend unit: `674 passed`
- 전체 backend API·contract: `22 passed`
- Ruff: 전체 backend 통과
- mypy: `177 source files` 통과
- frontend 집중: `7 passed`
- frontend 전체: `45 files, 204 tests` 통과
- TypeScript, ESLint, OpenAPI 생성 일치, Next.js production build 통과
- Compose config와 Dockerfile build check 통과
- core image: ARM64, `5,976,864,274` bytes, OCR package 없음, uv cache `0`, 비루트 계약 통과
- OCR image: AMD64, `7,098,486,735` bytes, CPU OCR package/import, uv cache `0`, 비루트 계약 통과
- 모델 10개 전체가 manifest 크기·SHA-256 검증을 통과해 named volume에 설치됨

## 실제 Linux 추론 판정

ARM64 Docker 엔진에서 AMD64 image를 QEMU로 실행해 네트워크 `0B`, CPU 약 100%, 메모리
약 2.9GiB 상태로 40분간 실제 전체 pipeline을 실행했으나 결과가 반환되지 않아 중단했다.
충돌이나 OOM은 없었지만 완료 결과가 없으므로 Linux CPU를 검증됨으로 승격하지 않는다.
다음 게이트는 native Linux x86_64에서 같은 image ID 또는 재현 가능한 동일 build로 text,
table, normalized bbox와 처리 시간을 확인하는 것이다. Linux GPU는 별도 engine·CUDA·NVIDIA
hardware 평가 전까지 미구현·미검증이다.

## Docker/cache 조사

정리 전용 승인이 없는 구현 작업이므로 image, volume과 BuildKit cache를 삭제하지 않았다.

- Images: `36.11GB`, reclaimable `18.19GB`
- Local Volumes: `7.091GB`, reclaimable `5.915GB`
- Build Cache: `35.55GB`, reclaimable `5.634GB`
- 보존 volume: `ai-workshop_model-cache`

교차 아키텍처 build가 새 cache를 만들었으므로 회수가 필요하면 `CACHE_POLICY.md`에 따라
AI Workshop 정확 대상과 의존성을 다시 조사하고 사용자 승인 후 별도 작업으로 진행한다.

이번 검증에서 새로 만든 pytest 임시 디렉터리 세 개는 정확 경로, 링크 부재와 미사용 상태를
확인하고 사용자 승인 후 삭제했다. 논리 회수량은 `258,171` bytes이며 모델·볼륨·이미지는
삭제하지 않고 사후 존재를 재확인했다.
