# ADR 0013: OCR 런타임 image와 안전 관리자 토폴로지를 분리한다

- 상태: 승인됨
- 기준일: 2026-09-06

## 맥락

단일 backend image는 API, Celery worker와 beat에 공통으로 쓰이지만 PP-StructureV3 dependency는
worker에만 필요하다. owner는 Docker 구성을 관리자 화면에서 확인해야 하지만 애플리케이션에
Docker socket이나 raw Compose를 노출해서는 안 된다.

CPU와 GPU는 같은 OCR model artifact를 재사용할 수 있어도 PaddlePaddle engine package와
하드웨어 호환성은 서로 다르다.

## 결정

같은 Dockerfile에서 `runtime-core`, `runtime-embedding-cpu`, `runtime-ocr-cpu`, `runtime-test`,
`runtime-ocr-test` target을 사용한다. beat·migration·model tool은 ML이 없는 core, API는
CPU embedding, worker는 CPU embedding+OCR target을 사용한다. test target만 pytest·mypy·ruff와
테스트 소스를 포함한다. Linux GPU는 별도 `runtime-ocr-gpu` image와 actual
hardware evaluation이 승인될 때까지 구현됐거나 검증됐다고 표시하지 않는다.

`sentence-transformers`와 `torch`는 `embedding-cpu` extra로 분리하고 torch는 uv의 explicit
PyTorch CPU index에 고정한다. Linux 운영 image에는 CUDA, NVIDIA runtime과 Triton을 설치하지
않으며 이미지 검증이 이를 직접 확인한다.

PaddlePaddle 및 공식 CPU-only PyTorch index 경계에 맞춰 API, OCR worker와 test target은
`linux/amd64`로
고정한다. ARM64 wheel의 설치 성공만으로 지원을 간주하지 않으며 실제 모델 초기화와 추론을
통과해야 검증됨으로 표시한다. ML이 없는 core service는 호스트의 native architecture를 유지한다.

Docker Compose를 실행 구성 정본으로 유지하고, backend Platform package에 owner API용 안전
토폴로지 매니페스트를 둔다. 자동 계약 테스트가 service, image target, dependency, named
volume과 profile drift를 차단한다. API는 allowlist metadata만 반환하며 Docker socket, raw
Compose, secret, endpoint와 host path를 사용하거나 노출하지 않는다.

## 결과

- core는 embedding·OCR·개발 dependency를 갖지 않고 API도 CUDA dependency를 갖지 않는다.
- worker는 고정 OCR dependency를 명시적으로 보유한다.
- 운영 image는 테스트 도구와 테스트 소스를 포함하지 않는다.
- owner는 전체 논리 구성을 확인할 수 있지만 live Docker 제어 권한은 얻지 않는다.
- Compose와 화면 계약을 함께 변경해야 하며 drift test 유지 비용이 생긴다.
- GPU는 CPU image 재사용으로 가장하지 않고 별도 승인·평가 작업이 필요하다.
