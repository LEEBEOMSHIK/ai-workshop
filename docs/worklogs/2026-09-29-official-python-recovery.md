# 공식 Python 전환과 로컬 서버 복구 — 2026-09-29

## 장애와 확인

기존 uv Python 실행이 Windows Code Integrity 3077 이벤트로 차단돼 API18000이 시작되지 않았다. 프론트5173의 로그인500은 API 연결 거부의 후속 증상이다. 같은 정책이 09-23부터 활성화돼 있었으며 기존 실행 파일의 수정 시각은08월말이다. 이전 정상 실행과 현재 차단의 판단 변화 원인은 미확인이다.

## 사용자 승인과 처리

공식 Python 설치 후 기존 Python 삭제를 승인받았다. Python Software Foundation의 공식3.13.15 x64 설치 파일을 사용했다. 게시 SHA-256과 Authenticode Valid를 확인했다. Python3.11과 기존 PATH는 변경하지 않았다.

- 공식 설치 경로: `%LOCALAPPDATA%/Programs/Python/Python313`.
- 기존 `backend/.venv`에서 `venv --upgrade --without-pip`로 설정과 실행기를 전환했다. site-packages150개와 backend/src editable 경로를 유지했다.
- `.env`, DB, 계정, 원본, 색인, 모델 자산은 변경하지 않았다. 보안 정책도 변경하지 않았다.
- 실행기·설정 복구본과 설치 검증 자료는 `.local-data/python-migration-20260929`에 있다.

## 검증

공식base_prefix·3.13.15·64bit, 실행기서명Valid, FastAPI/Uvicorn/Psycopg/애플리케이션 import를 확인했다. SciPy special, Torch, Sentence Transformers import도 통과했다. 기존 .env로 Selector loop의 API를 숨김 실행했다. API 직접health, 프론트경유health, 로그인페이지 모두200이다.

독립 리뷰는 venv제자리전환과 기존editable경로 보존을 확인했다. API 런처PID20384/실제PythonPID11792, 프론트리스너PID22660이다. PID는 이 시점 기록이며 재실행 때 달라진다.

## 기존 Python 정리 보류와 남은 검증

기존 uv runtime은65,531,889바이트이며, 해당runtime junction을 Blender MCP계열 uv cache환경16개가 참조한다. 백엔드 외 공유 도구이므로 임의삭제·캐시전체삭제하지 않았다. Blender MCP도 전환할지 사용자에게 범위확인을 요청했다. 기존Python 삭제는 아직 수행하지 않았다.

브라우저에서 기존 로그인페이지 표시를 확인했다. 기존계정 재로그인이 필요해 관리자 비교화면·DB문제이력 갱신은 대기다. worker/beat는 이번서버복구범위에서 시작하지 않았다. RAG실제생성·OCR기능을 검증한것으로 보고하지 않는다.

공식출처: https://www.python.org/downloads/release/python-31315/

## 후속 승인: Blender MCP 전환 및 이전 런타임 제거

사용자가 공유 Blender MCP환경도 공식Python으로 전환한 뒤 이전Python을 삭제하도록 승인했다. 확인된 uv cache archive환경16개만 `venv --upgrade --without-pip`로 전환했고 도구 패키지는 보존했다. 각 도구console entrypoint의 모듈import와 공식base_prefix를 확인했다. Blender실제연결/장면조작은 수행하지 않았다.

독립검토: 대상16개와 검증artifact의ID일치, 공식base16/16, Python/Pythonw서명32개Valid, uv cache/tools/backend의활성cfg중기존uv base참조0개. 제거직전기존runtime사용프로세스0개, 실제디렉터리와junction목적지를확인했다.

`uv python uninstall cpython-3.13.15-windows-x86_64-none`가성공했고 Roaming/uv/python아래기존3.13.15디렉터리와3.13junction이모두없어졌다. 제거된runtime논리파일크기는65,531,889바이트다. 호스트디스크실제회수량은별도측정하지않았다. 다른Python3.11과Blender패키지캐시는보존했다.

자동승인검토가임시복구자료삭제를거절했다. 사용자승인은기존runtime삭제이며복구백업·설치파일삭제는범위밖이고롤백가능성을줄인다는이유다. `.local-data/python-migration-20260929`의`previous-launcher`28,987,556바이트,`blender-launchers`7,654,493바이트,`python-3.13.15-amd64.exe`29,452,944바이트는변경없이보존했고별도확인을요청했다. 검증JSON/설치로그는보존한다.

삭제 후 재검증: backend 및 SciPy/Torch/Sentence Transformers import 통과. uv Python 탐색은 공식 Python313을 반환했다. API 직접·프론트 경유 health와 로그인 페이지는 모두200이며, 대표 Blender 환경의 도구 진입점 import도 통과했다.

## 복구 자료 정리 완료

2026-09-29 사용자 추가 승인 후 previous-launcher, blender-launchers, python-3.13.15-amd64.exe만 삭제했다. 삭제 직전 절대 경로 경계, 하위 reparse point 부재, 사용 프로세스 부재와 공식 Python의 base_prefix를 확인했다. 논리 제거량66,094,993바이트, 실행 전후 C드라이브 여유 공간 차이는66,191,360바이트이며 다른 프로세스의 디스크 활동 영향을 포함할 수 있다. 검증JSON과 설치로그는 보존했다. 삭제 후 API 직접health·프론트경유health·로그인페이지 모두200을 확인했다. 복구자료 삭제 대기는 해소됐다.
