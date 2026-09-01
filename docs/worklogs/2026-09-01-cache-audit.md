# 캐시·worktree·Docker 정리 승인 보고

- 상태: 승인 범위 적용, Docker 이미지 재발 방지와 VHDX 물리 용량 회수 완료
- 조사일: 2026-09-01
- 최종 검증일: 2026-09-02
- 기준 정책: `CACHE_POLICY.md`
- 측정 기준: junction과 symlink target을 따라가지 않은 논리 파일 크기, Docker의 image unique size

## 1. 제거 후보

### 파일시스템

| 절대경로 | 논리 크기 | 근거 |
|---|---:|---|
| `C:\projects\ai-workshop\node_modules` | 151.94 MiB | 루트 package·workspace·lockfile을 제거했고 `frontend/node_modules/.pnpm` 독립 설치와 프론트 검증이 통과한 레거시 의존성이다. |
| `C:\projects\ai-workshop\.pnpm-store` | 0.01 MiB | 로컬 package store가 아니라 `frontend`와 완료 복사본으로 이어지는 junction 메타데이터만 남은 레거시 경로다. |
| `C:\projects\ai-workshop\.worktrees\rag-ai-search-first-slice` | 1,971.22 MiB | 기능 HEAD `47cba3a`가 로컬·원격 기능 브랜치에 존재하고 `main`의 조상이며 추적 파일이 깨끗하다. 선별 검증 기록은 공식 worklog로 인계했다. |
| `C:\projects\ai-workshop\.worktrees\workshop-foundation` | 347.50 MiB | Git에 등록되지 않은 옛 작업 복사본이며 비교 조사에서 고유한 영구 소스가 확인되지 않았다. |
| `C:\projects\ai-workshop\.mypy_cache` | 15.19 MiB | 재생성 가능한 정적 분석 캐시다. |
| `C:\projects\ai-workshop\.ruff_cache` | 0 MiB | 재생성 가능한 정적 분석 캐시다. |
| `C:\projects\ai-workshop\frontend\dist` | 0.34 MiB | 독립 프론트 빌드로 재생성 가능한 산출물이다. |
| `C:\projects\ai-workshop\.local-data\pytest-tmp` | 0 MiB | 파일이 없는 pytest 임시 디렉터리다. `.local-data` 자체는 보존한다. |

다음 테스트 임시 디렉터리도 모두 재생성 가능하며 합계 0.16 MiB 미만이다.

- `C:\projects\ai-workshop\.t7fix1-token-green`
- `C:\projects\ai-workshop\.t7fix1-token-red`
- `C:\projects\ai-workshop\.t7fix1-unit-all`
- `C:\projects\ai-workshop\.t7fix2-unit-all`
- `C:\projects\ai-workshop\.tmp-review-t9-fix1`
- `C:\projects\ai-workshop\.tmp-review-t9-fix1-final`
- `C:\projects\ai-workshop\.tmp-t10-base`
- `C:\projects\ai-workshop\.tmp-t10-green-host1`
- `C:\projects\ai-workshop\pytest-task5`
- `C:\projects\ai-workshop\pytest-task6-all`
- `C:\projects\ai-workshop\pytest-task6-assets`
- `C:\projects\ai-workshop\pytest-task6-final`
- `C:\projects\ai-workshop\pytest-task6-upload`

`.superpowers`에서는 아래 중간 실행 상태와 재생성 가능한 review diff만 후보로 분리한다. 두 HTML 목업은 보존한다.

- `C:\projects\ai-workshop\.superpowers\brainstorm\.last-port`
- `C:\projects\ai-workshop\.superpowers\brainstorm\.last-token`
- `C:\projects\ai-workshop\.superpowers\brainstorm\1609-1788023204\state`
- `C:\projects\ai-workshop\.superpowers\sdd\2026-08-30-rag-ai-search-first-vertical-slice\review-5737b90..441a76a.diff`

파일시스템 후보의 논리 합계는 약 2.43 GiB다. pnpm hard link와 filesystem 특성 때문에 실제 호스트 여유 공간 증가는 이보다 작을 수 있다.

### Docker 컨테이너와 이미지

- `ai-workshop-object-store-init-1`은 정상 종료된 일회성 컨테이너이며 크기는 0 B다. 현재 worktree 경로 라벨과 아래 `95949023bee4` 이미지를 참조하므로 main Compose 관리 기준 이전 뒤 제거 후보로 둔다.
- 아래 36개 미태그 이미지는 모두 `com.docker.compose.project`가 `ai-workshop` 또는 격리 smoke project이고, `/app`, `workshop` 사용자와 AI Workshop API 실행 설정을 가진 반복 빌드 산출물이다.
- 현재 `ai-workshop-backend:local`은 제외했다. 후보 이미지의 Docker unique size 합계는 약 133.98 GB다.

```text
sha256:0d4653ab0d4213712e385738cf24d377ef34fbf2a3f89c76b487b10cb5148c33
sha256:31606787fbc34ebe1c828ffd9b191da375f33f177cacf053b9a2fbe64f73e60a
sha256:cd3e291c7453fd66bcf0eed1c0e238efd0262b58570b2e1ab671b21998bfaab6
sha256:24d88860a28cd1463822ee9483763678d988edb297dececee6d0578135793ffb
sha256:43de0fdfb6fcb101e55a5fa126d224970dd8a4f6ad8eaca76a53371d04ba5c13
sha256:286fc04a8e2e683df000a21db6da23b66f05e55cb3e5d685b0570e24d84eba90
sha256:fa44b234a2dbf224e8251899b3e9e9614f79e833f862b07f9b40f3c0712bb2ff
sha256:742b3b1413fdf76e437b40df8fa915d1a9577fe184377717c733e4afcb97ea13
sha256:a0fb4d9d681271e8c6e372cbac19c988dfcda90da837f9fa7208c15c39ff3ba3
sha256:64601fbd1e8a040497e28683169b08e21d61f2386408bbcda9d26ea1d1265bfa
sha256:0f2d0ae2a2388a3033c6b5b54a86158d54c3bbf932c006af2e9701e4e55448d0
sha256:ee1e554c7a54c61909bd8758fe29f3a2985f5fc036f327683897a9e3f58e6b11
sha256:589694601caf183237b642d44bf2f2f5d251cd759a6e1eb33c66442b9eb5682f
sha256:83d159fa46bf6d83aefef70a4cebe36bf69d6fdace3dd3761f85ccce0dafbcaa
sha256:092f7da255e4316c79e882c255e25c9c5dbec6f371b974a3f7064944792ca8f5
sha256:c654fdc1fbffa8871745149f462054cea5afa7638366ae2472b4b2a99898ccf1
sha256:d03e829843f9fb22d3db1fef2379fae24d6c6e2f9f61d78f0309001a875a7f05
sha256:3669f370e54a994667670b7d49e1419daba49b557b2b092e498f706ed6b83d4f
sha256:eab13f1f8b7b20202582d508710a1c34653de328835024f426db621bcbce5191
sha256:c1b810f4d695d96c6d1478f07338ce0d47df1d93b73809e963e65c23ea13a456
sha256:1e8b48787d61f57b1e92c23d966757977966e7fd73c136b851dff0de0305c1a2
sha256:3f7f906b6ed0d47c89e119957f106293a2e0b4946d7c07e74240d0fc4ff9563b
sha256:ffac4375fb8ff4d0a9022d0374a3475f87f637c002f918885e25e214a5c030ba
sha256:fd168e32afdaa7435ebe1491869536db43e001322473145338380e5a94fd79dc
sha256:95949023bee4b99a2d64ede5b22055978932679ec67e611e323aa8994f772dba
sha256:e9d10d511ab3a7fee24c25501b6663615b1400827c75552b1fd89c4fac85b527
sha256:e32f48ce65cc21c5795d1efcfeb0bbc61789cd2c99d6e1e462d468e14785bf8f
sha256:c50b4f9482ba6711bca94e38314761d77f3330c7c997d392133752de421da5f7
sha256:d2ac16af296bb620f54017011f119c768d5d351707a314d16a918e6b737d904c
sha256:4a9cb93de1d8b11b89ce8c3b0da46ea12adba4643cbd1e9f1b7976c03b03e3a5
sha256:c2a9d838762557e70a79c398f36d933ae5df2d9017fe7cbbcea0ba073fffd31e
sha256:8e816762cf3953d2dfa028ec608f68e4f2c3ef110d23e730cea87dcc8fc6ed04
sha256:420a45870bb2c492ed7b820f2f66c02254109f79d0962f7fc5100613292ca2c3
sha256:b2ef531a7c1fa6a166420e6f026969933e82718408e09b5ad9243e2c32feaf4c
sha256:b32871c9bd823ecf6bd6a8294ba6c2cf1875f8b04c9819cb8edd985e66971ec2
sha256:7970d2a0809cd00c580d2ca9bd6daaf3f4d33a9eeaf5a40cdf3ffdd67f2c5ae4
```

## 2. 보존 대상

- 현재 저장소와 `.git`, `.idea`를 보존한다.
- 독립 설치와 58개 테스트·타입 검사·린트·빌드를 통과한 `C:\projects\ai-workshop\frontend\node_modules`를 보존한다.
- `.local-data` 루트와 향후 `objects`, `models` 영속 데이터 영역을 보존한다.
- `.superpowers\brainstorm\1609-1788023204\content`의 RAG 구성 스튜디오 HTML 목업 두 개를 보존한다.
- 실행 중인 AI Workshop PostgreSQL, Redis, Elasticsearch는 각 한 개이며 모두 healthy 상태다.
- 현재 기준 이미지 `ai-workshop-backend:local` (`sha256:ff7e74a63b7a069eab3b5f8ce2632e641ea3c514b12d03f34e9551bced84fb06`)와 PostgreSQL·Redis·Elasticsearch 기반 이미지를 보존한다.
- 모든 AI Workshop named volume과 업로드·DB·검색·모델 데이터를 보존한다.

## 3. 차단 대상

- Docker volume 52개, 6.12 GB는 정리 대상이 아니다. 이 중 5.915 GB가 회수 가능으로 표시돼도 DB·검색·모델·업로드 데이터 가능성 때문에 삭제하지 않는다.
- `ai-workshop-smoke-task14-green-0831_model-cache` 5.301 GB를 포함한 smoke volume도 이 정책에서는 삭제하지 않는다.
- 실행 중 Compose 컨테이너 세 개는 아직 구성 경로가 완료 RAG worktree를 가리킨다. main 경로에서 동일 project를 재적용하고 health와 volume 연결을 검증하기 전에는 worktree를 제거하지 않는다.
- AI Workshop 소유권이 없는 미태그 이미지와 다른 프로젝트 컨테이너·이미지는 제거하지 않는다.

## 4. 공유 리소스

- BuildKit cache는 총 192.5 GB지만 회수 가능 표시는 79.49 MB이며 대부분 shared다. 프로젝트 단독 소유권을 증명할 수 없으므로 보고만 하고 정리하지 않는다.
- `tpmp-db-local-55432` PostgreSQL과 `csa_backend`, `dev-bumci`, `proposal_automation`, `test_preparation_master_project` 소유 Docker 리소스는 다른 프로젝트 자산이므로 변경하지 않는다.

## 승인 후 적용 순서

1. main 경로의 Compose 정의로 AI Workshop PostgreSQL·Redis·Elasticsearch 관리 기준을 이전하고 health, container label과 기존 volume 연결을 확인한다.
2. 정상 종료된 `ai-workshop-object-store-init-1`을 제거한다.
3. 등록된 RAG worktree를 Git worktree 절차로 제거하고, 미등록 foundation 복사본과 레거시 junction·루트 의존성을 정확한 절대경로로 제거한다.
4. 나열된 정적 분석·테스트·빌드·도구 산출물만 제거한다.
5. 나열된 36개 Docker image ID만 제거한다. 전역 prune은 사용하지 않는다.
6. Git 상태, worktree 목록, 프론트 고정 설치·테스트·타입 검사·린트·빌드·API 계약과 Docker health를 다시 검증한다.

## 2026-09-01 적용 결과

- PostgreSQL·Redis·Elasticsearch를 기존 named volume에 연결한 채 main Compose 경로로 재생성했다. 세 컨테이너 모두 healthy이며 config file과 working directory 라벨이 main 경로를 가리킨다.
- 정상 종료된 `ai-workshop-object-store-init-1`과 승인된 미태그 이미지 36개를 제거했다.
- Docker image 논리 사용량은 198.4 GB에서 24.64 GB로 173.76 GB 감소했다. 현재 `ai-workshop-backend:local`과 다른 프로젝트 이미지는 보존됐다.
- 이미지 제거 뒤 BuildKit 회수 가능 표시는 173.9 GB로 바뀌었지만 shared cache이므로 정책에 따라 제거하지 않았다.
- Docker volume은 하나도 제거하지 않았다. 총 52개와 6.12 GB가 그대로 보존됐다.
- 루트 `node_modules`, `.pnpm-store`, 정적 분석 캐시, 접근 가능한 테스트 임시물과 선별된 `.superpowers` 중간 상태를 제거했다.
- `frontend/node_modules` 독립 구조에서 frozen lockfile, 58개 테스트, 타입 검사, 린트, 빌드와 Docker 기반 OpenAPI 계약 검사를 통과했다. 검증 뒤 `frontend/dist`는 다시 제거했다.
- Git worktree 등록에는 main만 남았다.
- Windows host 여유 공간은 조사 시점 대비 약 43.6 MiB 증가했다. pnpm hard link와 Docker Desktop VM 저장소 특성 때문에 Docker 논리 감소량이 host 여유 공간에 즉시 동일하게 반영되지는 않는다.

Docker가 `root:root`, mode `111`로 만든 하위 디렉터리는 일반 권한에서 ACL 조회·소유권 회수·삭제가 거절됐다. 첫 관리자 실행에서는 Windows PowerShell 5.1이 긴 `torch` 라이선스 경로를 순회하지 못해 일부만 제거됐다. 동일 승인 경계를 유지한 채 PowerShell 7 관리자 프로세스에서 소유권과 ACL을 회수하고 긴 경로 형식으로 다음 여섯 경로만 제거했다.

- `C:\projects\ai-workshop\.worktrees\rag-ai-search-first-slice`
- `C:\projects\ai-workshop\.worktrees\workshop-foundation`
- `C:\projects\ai-workshop\.tmp-review-t9-fix1`
- `C:\projects\ai-workshop\.tmp-review-t9-fix1-final`
- `C:\projects\ai-workshop\.tmp-t10-base`
- `C:\projects\ai-workshop\.tmp-t10-green-host1`

최종 검증에서 위 여섯 경로는 모두 부재했다. `frontend/node_modules/.pnpm`, `.local-data`, 선별 HTML 목업, Docker volume과 shared BuildKit cache는 그대로 보존됐으며, 검증 시점의 C 드라이브 여유 공간은 39.42 GB였다. 관리자용 일회성 삭제 스크립트도 저장소에서 제거했다.

## 2026-09-01 BuildKit 용량 미회수 후속 조사

이미지 참조 제거만으로는 실제 Docker 저장소 용량이 회수되지 않았다. 후속 측정에서 Docker image는 24.64 GB였지만 BuildKit cache는 192.5 GB, 그중 회수 가능 표시는 173.9 GB였다. `C:\Users\bumci\AppData\Local\Docker\wsl\disk\docker_data.vhdx`는 논리 크기와 실제 할당 크기가 모두 219.079 GB이고 sparse file이 아니었다.

직접 원인은 `backend/Dockerfile`의 두 레이어다. 첫 `uv sync`는 최종 5.3 GB 가상환경 외에 `/root/.cache/uv` 5.0 GB를 같은 이미지 레이어에 남겨 10.7 GB가 됐다. 이후 `chown -R workshop:workshop /app /data`는 `/app` 전체를 copy-up해 빌드마다 약 5.5 GB 레이어를 다시 만들었다. 현재 이미지의 해당 레이어는 공유 상태이므로 보존하지만, 같은 AI Workshop 고유 명령을 가진 private·reclaimable 레코드 31개는 프로젝트 전용 후보로 식별됐다.

### 제거 후보

다음 정확한 BuildKit ID 31개의 논리 합계는 143.849 GB다.

```text
0tvwklu18skiss70pw1u2zw19
17e9a5jf8ih4cj8pk36rq5bdh
1rrout5wxz2peuq1hy80d8ni6
4k331tfvro7g7e0a0igqzwan1
5i0gobsx2b29tfvcn1t86pcge
bb6fhsm5f5xzrb51qvtnemkld
cqx3tgp632mmay58wtueu0b6b
d5pqc87ys1h0rzs4hg36k5bxo
dymrcop1acponr5b1movfsxnz
f021xp154pir1jtzrz9km0cm3
hhfjz77912qtlkswh5zdkiwfg
hyilwukigf2039id0in57s5zz
l26yc26109tis1gy51ojspfzk
lluq0c420ysd809xwv0eh9x2q
ox1qc285lh5alai40hkkqvzyw
poooo2jb1lo11p1sfm5004muj
qiazsdj600vv0ju1fjy1nk37b
r54owwdp4xwfmxx9lj4hzwdy3
rb9bmdpws5u39zi1jw7fahsrb
rec9grd7g50bp10wltl9gve96
rrwyzceejt3by4ytipwtzzqr6
rz1okp8tbgdlw179aje8ptl3u
stzocwbsp0k4s2a8oup8a0orx
t7ij29ja741oxk0wqiwyy7jzv
tg1qqvz5t47pn2tvwf3fhdljm
uogeam94r5tejhzjpprt0pqjs
v5bfwcq0dkrs944j7ebvb5l65
wa7evwhf4xaxa7dvwgoehg7zq
x96zs1t81lwqrdnbddyj4s78u
yuh2r9bbzbt7vi8puol6bdwsr
z83fg5qsbaxynovlgtah5f5z0
```

### 보존·차단 경계

- 현재 이미지와 공유되는 `h28gnjvptb3c5adlm80i74a4r` 5.497 GB 레코드는 보존한다.
- 실행 중 컨테이너, 이미지, Docker volume 52개와 AI Workshop 고유성이 입증되지 않은 나머지 BuildKit 레코드는 변경하지 않는다.
- `CACHE_POLICY.md`에 private·reclaimable·프로젝트 고유 BuildKit ID의 후보 조건을 먼저 반영하고, 위 ID 목록에 대한 파괴 작업 승인을 받은 뒤에만 제거한다.
- BuildKit 논리 삭제 뒤 VHDX 실제 할당량과 호스트 여유 공간을 다시 측정한다. 자동 회수가 일어나지 않을 경우 Docker와 WSL을 정상 종료한 VHDX 압축은 별도 승인 대상으로 다룬다.

### 재발 방지 적용

새 Dockerfile은 `uv` 다운로드 캐시를 BuildKit cache mount로 분리하고 `/app` 전체 chown을 제거했다. 실제 후보 이미지 검증에서 image size는 16.664 GB에서 5.960 GB로 감소했고 내장 uv cache는 5.218 GB에서 0 B가 됐다. 비권한 runtime import와 `/data/objects`의 `10001:10001` 소유권도 유지됐다. 검증된 image `sha256:ff7e74a63b7a069eab3b5f8ce2632e641ea3c514b12d03f34e9551bced84fb06`을 `ai-workshop-backend:local`로 승격했다.

후보 image를 빌드하는 동안 BuildKit 자동 GC가 위 31개 승인 ID를 먼저 제거했다. 삭제 명령은 사전 검증에서 선택 ID가 0개인 것을 확인하고 실행되지 않았다. Build cache는 192.5 GB에서 41.15 GB로 줄었지만 VHDX 실제 할당량은 227.568 GB로 증가했고 Windows host 여유 공간은 30.877 GB로 감소했다.

구형 미태그 image `sha256:d6a1de7e3c390e74adc8f0f2983d5da9f569fb7fcae8957d139760b20619ef6e` 16.664 GB는 컨테이너 참조가 없다. 이 image를 제거한 뒤 private 상태로 바뀌는 구형 전용 BuildKit chain은 다음 9개 ID, 논리 합계 16.468 GB다.

```text
gbcue4z865u4ftzwjtt4ns1s6
h28gnjvptb3c5adlm80i74a4r
ckmv7tu9kbbf0unjznnxk3nm9
so9utccs1lsabbmmpl77ex5q1
kvzds856r9j23ecn092e5ncm8
tgs6zi6knoy8ygogtk2l0oid8
tm85fl7429z9egnrocphk8aes
uxp32catlcehrlmdub4k89i5d
hx6boq7i795gm0ps5bcvepno0
```

### 승인 범위 정리 결과

- 구형 미태그 image `sha256:d6a1de7e3c390e74adc8f0f2983d5da9f569fb7fcae8957d139760b20619ef6e`를 제거하고 부재를 재확인했다.
- 승인된 구형 전용 BuildKit chain 9개 중 의존 자식이 없던 다음 7개를 정확한 ID로 제거해 논리 5.778 GB를 회수했다.

```text
h28gnjvptb3c5adlm80i74a4r
ckmv7tu9kbbf0unjznnxk3nm9
so9utccs1lsabbmmpl77ex5q1
kvzds856r9j23ecn092e5ncm8
tgs6zi6knoy8ygogtk2l0oid8
uxp32catlcehrlmdub4k89i5d
hx6boq7i795gm0ps5bcvepno0
```

- 승인된 parent `gbcue4z865u4ftzwjtt4ns1s6` 10.69 GB와 `tm85fl7429z9egnrocphk8aes` 221.4 kB는 승인 목록 밖의 다음 자식 레코드가 참조하고 있어 정확한 재시도에서도 0 B가 제거됐다.

```text
2grrs1kvnhl00wv6a3woxrse4  367.1 kB  [5/11] COPY alembic ./alembic
k3p9ksb7i2e3voptv9mm7tnxn  1.726 MB [6/11] COPY src ./src
```

- 두 자식은 기존 승인 범위 밖이므로 넓은 prune이나 임의 확장 삭제를 하지 않았다. 네 레코드는 모두 `private`, `reclaimable`, `shared=false`지만 추가 제거에는 정확한 네 ID에 대한 새 승인이 필요하다.
- Docker Desktop 재기동 뒤 Build cache는 24.25 GB, 회수 가능 표시는 16.33 GB다. 이 수치는 승인 범위 밖의 다른 캐시를 포함하므로 합계만으로 추가 제거하지 않는다.

### VHDX 물리 용량 회수 결과

- AI Workshop PostgreSQL·Redis·Elasticsearch와 다른 프로젝트의 `tpmp-db-local-55432`를 중단하고, Docker Desktop·WSL 종료와 VHDX exclusive open을 확인했다.
- 정확한 `C:\Users\bumci\AppData\Local\Docker\wsl\disk\docker_data.vhdx`만 DiskPart `compact vdisk`로 압축했다. Docker data reset, volume 삭제와 광범위한 prune은 실행하지 않았다.
- 압축 직전 약 227.536 GB였던 VHDX 실제 크기는 압축 직후 57.250 GB로 감소했다. Windows host 여유 공간은 약 32.624 GB에서 202.907 GB로 늘어 약 170.283 GB가 실제 회수됐다.
- Docker Desktop과 네 컨테이너를 다시 시작한 최종 측정은 VHDX 57,283,706,880 B, host 여유 공간 202,819,457,024 B다.
- AI Workshop 세 컨테이너와 `tpmp-db-local-55432`의 ID 및 기존 named volume mount는 중단 전과 동일하다. PostgreSQL `SELECT 1`, Redis `PONG`, Elasticsearch green, 다른 프로젝트 PostgreSQL `pg_isready`를 확인했다.
- Docker volume은 압축 전후 모두 52개이며 하나도 제거하지 않았다. 관리자용 임시 압축 스크립트·DiskPart 파일·로그도 최종 제거했다.

### 최종 회귀 검증

- 백엔드 image footprint: 5,959,896,736 B, 내장 uv cache 0 B, 비권한 runtime import 성공, `/data/objects` 소유자 `10001:10001`.
- Dockerfile build check는 경고 없이 통과했다.
- 백엔드 단위·API·계약 테스트 424개, Ruff, mypy 130개 source file과 OpenAPI 계약 검사가 통과했다.
- 프론트 frozen install, 테스트 58개, 타입 검사, 린트와 production build가 통과했다. 검증 산출물 `frontend/dist`는 정책에 따라 다시 제거했다.
