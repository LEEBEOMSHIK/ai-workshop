# Linux OCR native 실행 환경 사전 점검

- 기준일: 2026-09-07
- 상태: 사전 점검 완료, 실제 추론은 x86_64 실행 환경 대기
- 기존 계약: [런타임 검증 기록](2026-09-06-linux-ocr-runtime-admin-topology.md),
  [로컬 실행 정본](../runbooks/local-development.md)

## 확인 결과

| 대상 | 관측 결과 |
| --- | --- |
| 물리 CPU | Snapdragon X2 Plus, Win32_Processor Architecture=12 (ARM64) |
| Docker 서버 | Linux, aarch64, 10 CPU, 메모리 12,245,540,864 bytes |
| OCR 운영 이미지 | ai-workshop-backend-ocr-cpu:local, amd64 |
| Docker 컨텍스트 | default, desktop-linux; 모두 로컬 named pipe |
| WSL 배포판 | docker-desktop 한 개, WSL 2 |

PowerShell 프로세스의 RuntimeInformation.OSArchitecture는 X64를 보고했지만 물리 CPU와
Docker 서버 아키텍처는 ARM64다. 클라이언트 프로세스의 아키텍처만으로 native 실행을
판정하지 않는다. 등록된 컨텍스트에는 원격 x86_64 엔진이 없다.

## 실행 판정과 수용 기준

기존 ARM64 엔진의 AMD64 에뮬레이션 실행은 40분간 전체 pipeline 결과가 반환되지 않았다.
동일 환경에서 다시 실행해도 native x86_64 검증을 충족할 수 없어 이번에는 이미지 빌드,
컨테이너 생성, 모델 추론을 실행하지 않았다. Linux CPU는 미검증 상태를 유지한다.

실행 환경이 제공되면 정본 runbook의 모델 프로비저닝과 `ocr-linux-cpu-smoke`를 사용한다.
실행 전 Docker 서버 자체가 x86_64/amd64인지 확인하고 이미지 ID, Git revision, manifest
SHA-256과 패키지 버전을 기록한다. 모델 10개의 크기·해시 검증, 비루트 실행, 네트워크 차단과
모델·프로파일 read-only mount를 유지한다. 전체 Compose smoke의 `5 passed, 0 skipped`와
추론 결과, 처리 시간·최대 메모리는 완료 후 기록한다.

현재 테스트 `backend/tests/integration/labs/rag/ocr/test_paddle_structure_smoke.py`는
패키지 버전, 별도 프로세스 import, 실제 텍스트·표·좌표 추출을 검증한다. Linux fixture는
`POLICY`, `EQUITY`, `7%`인 영문 합성 이미지이므로 통과하더라도 Linux 한국어 인식 품질을
검증한 것으로 확대 해석하지 않는다. 한국어 수용 검증에는 별도의 재현 가능한 한국어 fixture가
필요하다. 성능 합격 임계값은 현재 정의돼 있지 않아 실행 시간을 측정값으로 보고한다.

## 작업 범위와 인계

- 필수 역할 선택: ai-engineer, infrastructure-docker-engineer.
- 독립 검증: integration-e2e-verifier가 Docker 서버의 linux/aarch64를 직접 재확인하고
  native 검증 차단 판정과 fixture 한계를 검토했다. bbox는 범위 검사이며 위치 정밀도를
  검증하지 않는다. DOCX→검색→뷰어 흐름도 이 smoke의 검증 범위 밖이다.
- 독립 검증에서 발견한 Windows runbook의 실제 추론 활성화 변수 누락과 skip 설명을 수정했다.
  Windows 명령은 integration marker로 실제 검증 3개를 선택하므로 `3 passed, 0 skipped`,
  전체 Linux Compose smoke는 `5 passed, 0 skipped`가 기대 결과다. 이번에 실행한 결과는 아니다.
- UI, DB, 권한, 모델 profile과 운영 기본값은 변경하지 않았다.
- 다음 입력: 사용 가능한 Intel/AMD 기반 Linux Docker 환경 또는 x86_64 PC.
- 현재 환경에서 native Linux 검증을 완료했다고 표시하거나 다른 환경을 임의로 생성하지 않는다.
