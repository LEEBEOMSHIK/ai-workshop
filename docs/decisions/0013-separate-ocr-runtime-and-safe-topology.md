# ADR 0013: OCR 런타임 image와 안전 관리자 토폴로지를 분리한다

- 상태: 제안됨
- 기준일: 2026-09-06

## 맥락

단일 backend image는 API, Celery worker와 beat에 공통으로 쓰이지만 PP-StructureV3 dependency는
worker에만 필요하다. owner는 Docker 구성을 관리자 화면에서 확인해야 하지만 애플리케이션에
Docker socket이나 raw Compose를 노출해서는 안 된다.

CPU와 GPU는 같은 OCR model artifact를 재사용할 수 있어도 PaddlePaddle engine package와
하드웨어 호환성은 서로 다르다.

## 결정

같은 Dockerfile의 `runtime-core`와 `runtime-ocr-cpu` target을 사용한다. API와 beat는 core,
OCR worker는 CPU OCR target을 사용한다. Linux GPU는 별도 `runtime-ocr-gpu` image와 actual
hardware evaluation이 승인될 때까지 구현됐거나 검증됐다고 표시하지 않는다.

Docker Compose를 실행 구성 정본으로 유지하고, backend Platform package에 owner API용 안전
토폴로지 매니페스트를 둔다. 자동 계약 테스트가 service, image target, dependency, named
volume과 profile drift를 차단한다. API는 allowlist metadata만 반환하며 Docker socket, raw
Compose, secret, endpoint와 host path를 사용하거나 노출하지 않는다.

## 결과

- API와 beat image가 OCR dependency로 불필요하게 커지지 않는다.
- worker는 고정 OCR dependency를 명시적으로 보유한다.
- owner는 전체 논리 구성을 확인할 수 있지만 live Docker 제어 권한은 얻지 않는다.
- Compose와 화면 계약을 함께 변경해야 하며 drift test 유지 비용이 생긴다.
- GPU는 CPU image 재사용으로 가장하지 않고 별도 승인·평가 작업이 필요하다.
