# 테스트 산출물·Docker 정리 감사

- 기준일: 2026-09-06
- 완료일: 2026-09-07
- 프로젝트: `C:\projects\ai-workshop`
- 상태: 승인 범위 정리와 VHDX 오프라인 압축 완료
- 정책: `CACHE_POLICY.md` schema v1, destructive approval required

## 제거 후보

아래 73개 디렉터리는 pytest `--basetemp`로 생성된 완료 작업의 임시 산출물이다. 전부 정규화된
프로젝트 내부 경로이고 reparse point가 아니며, 참조 중인 프로세스·컨테이너가 없다. 26개는
현재 계정으로 접근 가능하고 확인된 파일 합계는 16,706 bytes다. 47개는 Windows ACL 때문에
현재 계정과 read-only Docker bind mount에서 내부 크기 확인이 거부되어 관리자 권한 재검증이
필요하다.

### 저장소 루트 35개

- `C:\projects\ai-workshop\.pt-cli-ocr-green`
- `C:\projects\ai-workshop\.pt-cli-ocr-red`
- `C:\projects\ai-workshop\.pt-core`
- `C:\projects\ai-workshop\.pt-core2`
- `C:\projects\ai-workshop\.pt-e2e-ocr`
- `C:\projects\ai-workshop\.pt-fix`
- `C:\projects\ai-workshop\.pt-ocr-focused-final`
- `C:\projects\ai-workshop\.ptn-ocr`
- `C:\projects\ai-workshop\.ptn-ocr-final`
- `C:\projects\ai-workshop\.ptu-ocr`
- `C:\projects\ai-workshop\.ptu-ocr-final`
- `C:\projects\ai-workshop\.pytest-task11-openapi-red`
- `C:\projects\ai-workshop\.pytest-task2-round4-baseline`
- `C:\projects\ai-workshop\.pytest-task2-round4-final`
- `C:\projects\ai-workshop\.pytest-task2-round4-green-cli`
- `C:\projects\ai-workshop\.pytest-task2-round4-green-config`
- `C:\projects\ai-workshop\.pytest-task2-round4-green-config-invalid`
- `C:\projects\ai-workshop\.pytest-task2-round4-green-failure-version`
- `C:\projects\ai-workshop\.pytest-task2-round4-green-hooks`
- `C:\projects\ai-workshop\.pytest-task2-round4-green-initialize`
- `C:\projects\ai-workshop\.pytest-task2-round4-green-mcp`
- `C:\projects\ai-workshop\.pytest-task2-round4-green-probe`
- `C:\projects\ai-workshop\.pytest-task2-round4-green-requirements-params`
- `C:\projects\ai-workshop\.pytest-task2-round4-green-skills`
- `C:\projects\ai-workshop\.pytest-task2-round4-red-apps`
- `C:\projects\ai-workshop\.pytest-task2-round4-red-cli`
- `C:\projects\ai-workshop\.pytest-task2-round4-red-config`
- `C:\projects\ai-workshop\.pytest-task2-round4-red-failure-version`
- `C:\projects\ai-workshop\.pytest-task2-round4-red-hooks`
- `C:\projects\ai-workshop\.pytest-task2-round4-red-initialize`
- `C:\projects\ai-workshop\.pytest-task2-round4-red-mcp`
- `C:\projects\ai-workshop\.pytest-task2-round4-red-requirements-params`
- `C:\projects\ai-workshop\.pytest-task2-round4-red-skills`
- `C:\projects\ai-workshop\.pytest-task8-search-full2`
- `C:\projects\ai-workshop\.pytest-tmp`

### backend 19개

- `C:\projects\ai-workshop\backend\.pytest-nextjs-final-contract`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-characterization-green`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-combined-green`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-focused-green`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-focused-skips`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-green-new`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-mutation-red-partial`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-mutation-red-posix-remove`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-mutation-red-report`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-mutation-red-report-2`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-mutation-red-windows-remove`
- `C:\projects\ai-workshop\backend\.pytest-task3-cont-pre-fix-2`
- `C:\projects\ai-workshop\backend\.pytest-tmp`
- `C:\projects\ai-workshop\backend\.pytest-verify-ocr-focused`
- `C:\projects\ai-workshop\backend\.pytest-verify-ocr-focused-key`
- `C:\projects\ai-workshop\backend\.pytest-verify-ocr-focused-secret`
- `C:\projects\ai-workshop\backend\.pytest-verify-ocr-root`
- `C:\projects\ai-workshop\backend\.pytest-verify-ocr-root-all`
- `C:\projects\ai-workshop\backend\.pytest-verify-ocr-unit`

### `.local-data` 19개

- `C:\projects\ai-workshop\.local-data\pytest-artifact-verify-green`
- `C:\projects\ai-workshop\.local-data\pytest-artifact-verify-green2`
- `C:\projects\ai-workshop\.local-data\pytest-codex-gate-fail-final`
- `C:\projects\ai-workshop\.local-data\pytest-codex-gate-fail-full`
- `C:\projects\ai-workshop\.local-data\pytest-codex-gate-fail-full-root`
- `C:\projects\ai-workshop\.local-data\pytest-compose-contract-green2`
- `C:\projects\ai-workshop\.local-data\pytest-compose-smoke-green`
- `C:\projects\ai-workshop\.local-data\pytest-ocr-fixture-green`
- `C:\projects\ai-workshop\.local-data\pytest-ocr-full-20260906`
- `C:\projects\ai-workshop\.local-data\pytest-ocr-paths-green`
- `C:\projects\ai-workshop\.local-data\pytest-ocr-portability-red`
- `C:\projects\ai-workshop\.local-data\pytest-runtime-api-green`
- `C:\projects\ai-workshop\.local-data\pytest-runtime-api-red`
- `C:\projects\ai-workshop\.local-data\pytest-runtime-topology-green`
- `C:\projects\ai-workshop\.local-data\pytest-runtime-topology-green2`
- `C:\projects\ai-workshop\.local-data\pytest-task4-review-openapi`
- `C:\projects\ai-workshop\.local-data\pytest-unit-current`
- `C:\projects\ai-workshop\.local-data\pytest-unit-final-review-20260903-0218`
- `C:\projects\ai-workshop\.local-data\pytest-unit-final-review-20260903-0222`

### 교체되거나 완료된 Docker image 20개

아래 이미지는 모두 현재 컨테이너 참조가 없다. 현재 test image 두 개는 완료된 검증 전용이며
필요할 때 Compose로 재빌드할 수 있다. 나머지는 untagged이고, 앞의 19개는
`com.docker.compose.project=ai-workshop` 라벨로 소유권을 확인했다. 마지막 이미지는 라벨이
없지만 `/app` 작업 디렉터리와 `ai_workshop.main:app` 실행 명령으로 이 저장소의 구형 API
image임을 확인했다.

- `sha256:b9eb5adafb7a9a546b2296fb451a28d693f736f8ff6818d9af6e2d2fffab4555`
  (`1,731,529,786` bytes, 완료된 현재 E2E test, 재빌드 가능)
- `sha256:7098ba38e90ecdcd19996029e8e2cf282e6f2b4988acc1c5b694f9be029445f0`
  (`3,098,925,345` bytes, 완료된 현재 OCR test, 재빌드 가능)
- `sha256:f97666866288c839fba36bc4375bc3ee1dc28e15942abe40be7ec39a1ea53598`
  (`3,098,923,889` bytes, 교체된 OCR test)
- `sha256:420529a1c9980784a8162fc4394f489a785df3fe0dbdae2f35f65203152ce7fc`
  (`1,731,528,330` bytes, 교체된 E2E test)
- `sha256:a1e55939eece0c581f591a00f879f1c6e452feae6200203f610384270cfd64b6`
  (`3,005,623,143` bytes, 교체된 OCR worker)
- `sha256:d4275d2eb838a5e2da8200cee4bb8e259e1943b4158020306fd732f504abe8ad`
  (`1,638,227,584` bytes, 교체된 embedding API)
- `sha256:496d01e603d87faf28bada8d92df635c0e39ea8d4b1836e2b7f3368b40c74cd7`
  (`398,102,709` bytes, 교체된 core)
- `sha256:1e87477ab3f92a9840a7137e756b7fbd3449d10ae6de836c331a6ed40c630b87`
  (`7,098,486,735` bytes, 구형 OCR test)
- `sha256:2016bf8820f3d1bb19ae174394a488dc9526936ef5ef155083e91d3a3a59b783`
  (`5,976,864,274` bytes, 구형 core)
- `sha256:840bc95f14395d35410c69ae4b087312f5f51b9bc44299ac5b76a4abe0415b04`
  (`7,098,482,944` bytes, 구형 OCR test)
- `sha256:ae5580a91f81bf246316743698248a4f6a332c511aa3ab5ac02ab4bd809a1c67`
  (`7,098,172,539` bytes, 구형 OCR test)
- `sha256:7e632c33ba4bf25780a91d598f79228164e129ac0d2fcda43a752be9914059e5`
  (`7,191,662,318` bytes, 구형 OCR test)
- `sha256:30d906bacb175e2b84c64ecb719bdbd91fa0cb1d341d63598592a9b147ab4f16`
  (`7,191,661,397` bytes, 구형 OCR test)
- `sha256:9d9aa0e7c267255170ae5ebc8b954b3e48a7e9ee16496c33d2914cfb1d8f78cf`
  (`5,976,858,651` bytes, 구형 core)
- `sha256:79660b9a36bcce3aa0cdd99a9e21875a2dbd71716bf12881438c2a02d24856dc`
  (`7,191,653,277` bytes, 구형 OCR test)
- `sha256:4985fa1c77baf45dfed93aab1057af21143fb3213b94c2b50004bc46f315fead`
  (`7,191,648,022` bytes, 구형 OCR worker)
- `sha256:4fbb7322265e3ea6ff13992b5106561a061a50b2f7dc5482f3b557ce35557f54`
  (`7,187,201,515` bytes, 구형 OCR worker)
- `sha256:a847b19449d2c72d6d66738a28325d0417e8fcec6b63a5a0f7cb3cd79133f702`
  (`6,979,971,741` bytes, 구형 OCR worker)
- `sha256:afc6a42d66c75f40da66a3bc20c5bd164ff5f686a45f03f93e08bda13acd9128`
  (`5,976,845,276` bytes, 구형 API)
- `sha256:ff7e74a63b7a069eab3b5f8ce2632e641ea3c514b12d03f34e9551bced84fb06`
  (`5,959,896,736` bytes, 라벨 이전 구형 API)

### AI Workshop 전용 private BuildKit 두 개

- `93lb850qbb66uqf5rjkxkn2xl`: `5.204GB`, mutable exec cache mount,
  이전 `uv sync --all-groups --no-install-project` 명령, reclaimable·private·non-shared
- `rbas8nyzf5ef8gwvjqpxny5x0`: `427.8MB`, 이전 동일 명령의 regular layer,
  reclaimable·private·non-shared

후속 조사에서 부모 `rbas8nyzf5ef8gwvjqpxny5x0`의 유일한 자식
`g98czd2wowjxe2q591c2z2u0s`를 확인했다. 자식은 AI Workshop Dockerfile의
`COPY alembic` 레코드, `36.86kB`, reclaimable·private·non-shared였고 추가 후손은 없었다.
사용자 승인 후 자식과 부모 순서로 exact ID 삭제했다.

Docker image의 표시 크기 합은 실제 회수량이 아니다. 공유 layer와 BuildKit 참조가 있으므로
논리 제거량, Docker 저장소 감소량과 Windows VHDX 실제 감소량을 정리 후 각각 측정한다.

## 보존 대상

- 현재 core `sha256:03d04f9377d46890048786700113c825c054744eda602c1bb24ab615c332c899`
- 현재 embedding CPU `sha256:12eca76db4f705cdfdd9644d330b278664096242dd098eed0e4d20e0d4dcd104`
- 현재 OCR CPU `sha256:2e284ec3e5ae4e7ac100525de265092e95ab9aecb3a8c75eda09273714d5c38b`
- 실행 중 PostgreSQL·Redis·Elasticsearch와 모든 프로젝트 named volume
- `.local-data/objects`, `.local-data/models`, `ai-workshop_model-cache`
- 사용자 소유 `references/`, `.idea/`, `.git/`

## 차단 대상

- 이번에 조사·승인한 정확한 pytest 디렉터리, Docker image, BuildKit 레코드와 VHDX 압축은
  모두 처리됐다.
- 새로 조사하지 않은 BuildKit 레코드, image와 volume은 삭제하지 않는다. 특히 volume의
  `RECLAIMABLE` 표시는 데이터 불필요성을 증명하지 않으므로 broad prune 대상이 아니다.

## 공유 리소스

- exact 자식·부모 삭제 직후 BuildKit은 `38.04GB`였고 Docker Desktop 재시작 뒤 자체 GC로
  `26.45GB`가 됐다. 남은 레코드는 다른 현재 image 또는 프로젝트와의 공유 여부를 개별
  증명하지 않았으므로 제거하지 않는다.
- 새로 조사·승인되지 않은 BuildKit record는 삭제 대상이 아니다.

## 정리 결과

- UAC 관리자 읽기 전용 감사에서 73개 디렉터리 전체의 프로젝트 경계, 디렉터리 타입,
  내부 reparse point 부재와 실행 프로세스 참조 0개를 확인했다.
- 승인된 pytest 임시 디렉터리 73개를 리터럴 경로로 제거했고 사후 잔여는 0개다.
- 승인된 교체·테스트 Docker image 20개를 exact image ID로 제거했다.
- BuildKit `93lb850qbb66uqf5rjkxkn2xl`은 exact ID filter로 `5.204GB`를 회수했다.
  후속 승인으로 자식 `g98czd2wowjxe2q591c2z2u0s` `36.86kB`와 부모
  `rbas8nyzf5ef8gwvjqpxny5x0` `427.8MB`도 exact ID filter로 제거했다. 두 ID가 BuildKit
  목록에 없음을 재검증했다.
- Docker image 논리 사용량은 `44.22GB`에서 `11.38GB`로 `32.84GB` 감소했고 Build Cache는
  `43.67GB`에서 `38.47GB`로 `5.20GB` 감소했다.
- Windows C: 여유 공간은 `150,479,749,120` bytes에서 `150,483,476,480` bytes로
  `3,727,360` bytes 증가했다. 논리 삭제와 달리 Docker Desktop sparse VHDX가 자동 축소되지
  않았기 때문이다.
- 모든 실행 컨테이너를 정상 종료하고 Docker Desktop을 완전히 중지한 뒤 exact 경로
  `C:\Users\bumci\AppData\Local\Docker\wsl\disk\docker_data.vhdx`의 reparse point 부재와
  독점 접근을 확인했다. DiskPart `compact vdisk`는 exit code 0으로 끝났다.
- 종료 직후 압축 기준 크기 `73,814,507,520` bytes에서 압축 직후
  `73,766,273,024` bytes로 `48,234,496` bytes(약 46MiB) 감소했다. 최초 정리 전
  `73,826,041,856` bytes와 비교하면 `59,768,832` bytes 감소다.
- C: 여유 공간은 최신 압축 직전 `150,096,904,192` bytes, 직후
  `150,141,706,240` bytes, 서비스 재시작 뒤 `150,174,216,192` bytes였다. 호스트 여유 공간은
  다른 프로세스 영향으로 변동하므로 VHDX 자체 감소량을 물리 회수 정본으로 사용한다.
- Docker WSL의 `/dev/sde`는 약 `40.5GiB` 사용 중이고 `fstrim --dry-run`은 `0B`를 반환해
  미전달 TRIM 블록은 없었다. Windows에 `Optimize-VHD` cmdlet이 없어 Full 모드 재배치는
  수행하지 않았다. 논리 삭제량 전부가 즉시 VHDX 파일 축소로 이어진다고 기록하지 않는다.
- 현재 core·embedding CPU·OCR CPU image와 PostgreSQL·Redis·Elasticsearch healthy 상태,
  PostgreSQL·Redis·Elasticsearch·object·model named volume 보존을 확인했다. 다른 프로젝트의
  PostgreSQL도 기존 컨테이너와 volume으로 재시작해 연결 수락을 확인했다.
