# Conda 환경의 backend 내부 이전

- 승인: 외부 `C:/projects/ai-workshop-scipy-test`를 `C:/projects/ai-workshop/backend/.conda`로 오프라인 이전. 기존 시작 스크립트에서 자동 활성화.
- 범위: 런타임 배치·경로 검증·런처·관련 테스트와 운영 안내. DB/ES/Docker·모델·추가 RAG 요청·권한 설정 변경 없음.
- 상태: 준비 중. 사용자 터미널의 백엔드 및 같은 환경 worker 정상 종료 확인 대기. 실행 상태 조회 제한을 우회하지 않음.
- 기존 변경 보존: `.local-data/project-agent-work/conda-in-backend-20261015/before/`와 git status/diff 스냅샷. 새 브랜치·worktree·커밋 없음.
- 오프라인 자료: Conda 아카이브 27개(72,109,256 bytes), pip wheel 37개(291,893,629 bytes)를 캐시에서 복사하고 기존 승인 해시와 일치 확인. 52개 pip 실행 파일의 이전 경로를 재생성할 패키지 소유권 확인.
- 원본 환경과 기존 RAG 요청·readiness 증거는 불변 보존. 이전 검증 전 정리하지 않음.
- 역할: 메인 구현(런타임 운영·Python 경로·테스트 설계), 별도 독립 리뷰/검증. UI·DB·RAG 동작·모델 실행 역할 제외: 해당 기능 변경 없음.
- 판단: 승인된 기존 작업 디렉터리에서 진행하며 별도 worktree/커밋을 만들지 않는다. 계획의 일반 worktree 절차보다 사용자의 변경 보존 지시를 우선한다.

## 실행 준비 검증

- 원본 파일 66,490개·2,108,394,072 bytes의 SHA-256 기록 완료. 기존 RAG 증거 32개 파일 별도 해시 기록 완료.
- `.gitignore`에 `backend/.conda/` 추가 후 `git check-ignore`로 제외 확인.
- 런처의 기본값을 사용자 Miniconda base와 저장소 `backend/.conda`로 설정. 명시적인 기존 인수, 자동 활성화, 선택된 Python 동일성 검사, 오류 코드 전달과 프로세스 환경 복원 유지.
- 새 no-argument 동작 테스트가 변경 전 실패한 것을 확인하고 변경 후 런처·런타임 선택 단위 테스트 28개 통과(26.37초). 외부 프로세스 대신 PowerShell 함수로 Conda/Python을 대체한 테스트이므로 실제 새 환경 기동 성공으로 해석하지 않음. pytest 자동 플러그인 비활성화에 따른 asyncio_mode 설정 경고 1개.
- 변경한 테스트 파일 Ruff·strict Mypy 통과. 실제 환경 복제/재설치·import·OpenAPI·health·원본 정리는 아직 미실행.
- 런타임 descriptor·3개 SHA pin·운영 안내의 현재 실행 경로는 새 환경 검증 후 전환 예정.
- 기존 RAG manifest는 수정하지 않음. 런처 소스는 이번 작업에서 바뀌므로 과거 readiness의 소스 해시를 새 런처의 검증 증거로 재사용하지 않음. 요청 예산 1/1 유지, 추가 추론 없음.

## 독립 준비 리뷰

- 독립 리뷰가 27개 Conda·37개 pip 자료를 다시 해시 대조했고 불일치 0개. 준비 코드 결함 없음.
- `modelscope`와 `modelscope-hub`가 `modelscope.exe`·`ms.exe`를 공동 소유하는 위험 확인. 현재 두 실행 파일은 `modelscope.cli.cli:run_cmd`를 호출함을 실행 없이 ZIP 진입점으로 확인.
- 52개 실행 파일의 `__main__.py`를 기록. 이전 시 나머지 36개 후 `modelscope` 1개를 설치하고 진입점 동일성을 검증하도록 로컬 요구사항 파일을 분리. 실제 재설치는 아직 수행하지 않음.
- 현재 차단은 백엔드·동일 환경 worker 정상 종료 확인 대기. 기존 프로세스 관측 제한 때문에 강제 종료나 CIM/소켓 우회 조회를 하지 않음.

## 실제 이전 시도와 현재 차단

- 사용자가 백엔드 정상 종료를 확인한 뒤 실행. 별도 worker 사용 충돌은 발견하지 않았으나 시스템 전체 미사용을 관측한 것은 아님.
- 첫 명령의 forward-slash clone 경로를 Conda가 이름으로 해석해 파일 작업 전 실패. Windows 경로로 수정.
- 다음 시도는 작업용 캐시에 URL 매핑이 없어 OfflineError로 실패. 다운로드 없이 기존 검증 아카이브와 원래 URL 매핑을 제공했고 27개 로컬 캐시 인식을 확인한 뒤 복제 성공(exit 0).
- 새 환경의 기본 런처 `-CheckOnly`에서 executable/sys.prefix/CONDA_PREFIX가 모두 `backend/.conda`임을 확인. 이는 서버 기동·health 성공이 아님.
- Conda가 복사한 untracked 56,743개 파일은 원본과 내용 대조해 누락 0·차이 0.
- 새 메타데이터에 최상위 SHA-256이 누락돼 기존 보호 검사가 실패. 검증된 원본 캐시의 repodata_record를 복원했으나 Conda 26.7 명시 목록 설치는 같은 버전을 다시 연결하지 않음. 같은 표준 UnlinkLinkTransaction에 정확한 27개 unlink/link 목록을 주어 재연결했고 성공(exit 0). 보호 검사 조건을 완화하거나 메타데이터 값을 임의 생성하지 않음.
- 재연결 후 Conda 27개 version/build/SHA/URL, 전체 배포 패키지 153개 버전의 원본 일치, 보호 파일 6,121개 스냅샷 확인. Python SHA는 기존 승인값과 같음.
- Conda의 환경 목록 verify 단계에서 사용자 `.conda/environments.txt` 쓰기 불가 경고 발생. 등록 비활성화 옵션은 실제 등록만 막고 앞선 touch 시도는 막지 않음. 권한·보호 설정은 변경하지 않음.
- pip 36개 선설치 명령은 첫 `py-cpuinfo` 제거 과정에서 sandbox 임시 폴더의 `cpuinfo.exe`에 `[Errno 13] Permission denied`가 발생해 exit 1. 36개 설치 완료 아님. 마지막 `modelscope` 설치는 실행하지 않음. 임시 경로 변경·권한 상승·우회 재시도·정리를 하지 않음. 부분 변경된 새 환경을 보존하며 사용 금지.
- 원본 전체 66,490개 파일의 추가·누락·SHA 변경 0, RAG 증거 32개 SHA 변경 0을 재확인. 다운로드·모델 추론·추가 RAG 요청 없음.
- 불완전한 새 환경이 기본 선택되지 않도록 이 작업에서 만든 런처 기본값과 해당 테스트 변경만 SHA 비교 후 시작 전 바이트로 복구. 기존 변경은 유지. 런타임 descriptor와 3개 pin, 기존 운영 안내는 전환하지 않음.
- 현재 변경은 `.gitignore`, WORKBOARD의 상태 안내, 이 작업 기록뿐이다. 앞서 28개 테스트·Ruff·Mypy 통과는 전환 준비 코드에 대한 결과이며 현재 새 환경의 완성을 뜻하지 않는다. 새 환경의 pip check·native import·OpenAPI·서버 health·옛 환경 정리는 미실행.
- 복구 실행: 저장소 루트에서 `./scripts/run_backend_conda.ps1 -CondaPython 'C:/Users/bumci/miniconda3/python.exe' -Prefix 'C:/projects/ai-workshop-scipy-test'`.


## 수동 재설치 확인과 실행 경로 전환

- 사용자 일반 PowerShell 재설치 결과 `manual-20261015-181137-result.json`의 `PIP_REINSTALL_VERIFIED`와 설치 보고서 37개를 확인했다. 독립 리뷰에서 승인된 이름·버전·SHA·로컬 wheel 경로와 불일치 0개. `pip check`는 No broken requirements found이며 백업 메타데이터 경고는 남는다.
- 직접 재검증: Conda 27개, 활성 배포판 153개, 보호 파일 6,121개와 실행 파일 52개의 대상 경로·진입점 일치. `~puinfo` 6파일과 `~y_cpuinfo-9.0.0.dist-info` 9파일은 원본과 SHA가 같은 실패 당시 백업으로 독립 확인했다. 즉시 정리할 필요가 없어 이동·삭제하지 않았다.
- 표준 Conda 활성화 후 NumPy 2.3.5, SciPy 1.18.1, sklearn 1.9.0, Torch 2.13.0+cpu, Sentence Transformers 6.0.0, cpuinfo, SSL import와 SciPy 선형 연산 통과. 모델 생성·다운로드·추가 RAG 요청 없이 OpenAPI 136개 경로 생성 및 기존 TypeScript schema `--check` 통과. 결과는 작업 증거 폴더의 `application-verification.json`과 `relocated-openapi.json`에 보존했다.
- descriptor를 `C:/projects/ai-workshop/backend/.conda`로 전환하고 Python·Node·PowerShell 3개 검증 핀을 함께 변경했다. descriptor SHA는 `1a233b5d84a35b7df0dba52ae1beb77023799f1aa00a18445c2eef0bbbac67c4`; Python 실행 파일 SHA는 기존 승인값 그대로다. 실제 Python·Node·PowerShell 선택 검증도 통과했다.
- 기존 런처에 현재 사용자의 Miniconda base와 저장소 `backend/.conda` 기본값을 추가했다. PowerShell `-File`에서는 param 초기화 중 PSScriptRoot가 비어 있어 최초 점검이 실패했으므로, Prefix 기본값은 스크립트 본문의 try 안에서 계산하도록 수정했다. 최종 실제 `powershell -NoProfile -File ./scripts/run_backend_conda.ps1 -CheckOnly`는 exit 0이며 executable/prefix/CONDA_PREFIX 모두 새 경로다.
- 기본 인수 회귀 테스트 2개가 구현 전 실패했고 구현 후 런처·runtime unit 29개 통과(16.91초, 플러그인 자동 로딩 비활성화에 따른 asyncio_mode 경고 1개). Node 검사는 처음에 모듈 mock 플래그 누락으로 실패했으며, 설치된 Node가 지원하는 `--experimental-test-module-mocks`로 실행하여 15개 통과했다. PowerShell 검증, Ruff, strict Mypy 2파일, 관련 diff 공백 검사도 통과했다.
- 쓰기 전 기존 12파일 기준 해시와 전환 직전 상태를 비교·보관했으며, 변경 파일만 갱신했다. 작업 스냅샷은 `cutover-before/`, `cutover-before-sha256.json`, 최종 파일 해시는 `cutover-final-sha256.json`에 둔다. 최종 보존 검사에서 원본 66,490개 파일의 추가·누락·SHA 변경 0개, RAG 증거 32개의 SHA 변경 0개를 확인했다(`preservation-final.json`). 최종 독립 리뷰에서도 차단 사항은 없었다.
- 백엔드 시작 명령: 저장소 루트에서 `./scripts/run_backend_conda.ps1`. 이 작업에서는 서버 시작·health·Route 서비스 실제 기동·추가 모델 요청을 하지 않았다. 원본 Conda, 구 `.venv`, 실패 백업을 모두 보존한다. 커밋·푸시·마이그레이션·DB/ES/Docker 상태 변경 없음.
