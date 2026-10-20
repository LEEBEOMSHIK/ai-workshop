# Gemma 직접 실행을 위한 로컬 생성 provider

## 범위와 현재 상태

사용자의 로컬 Gemma RAG 진행 요청에 따라 Python Transformers/PyTorch 직접 추론 경로를
추가했다. 코드·mock 검증 완료이며 실제 모델 활성화와 RAG 전체 기능 마감은 미완료다.
Codex CLI/Ollama를 필수 런타임으로 추가하지 않았고 기존 provider도 유지했다.
[ADR-0037](../decisions/0037-local-transformers-generation.md),
[계획](../superpowers/plans/2026-10-11-local-transformers-generation.md),
[실행 설정 정본](../runbooks/local-development.md#로컬-transformers-생성-코드-제공-활성화-미실행).

작업 시작 HEAD는 `db7417a`였다. 기존 변경은 WORKBOARD, 취소 복구 미승인 초안,
기능 점검·복구 조사 worklog, references였다. 1,890개 파일 SHA 기준선을 기록하고
담당 파일 쓰기 직전에 재확인했다. 기존 문서 3개와 references 파일 1개의 SHA는 종료에도
동일하다. WORKBOARD의 기존 내용·학습 문서 참조·우선순위는 유지했다.
다른 작업의 staging/commit을 수행하거나 브랜치·worktree를 바꾸지 않았다.

중간 위험 작업으로 분류했다. 메인은 요구 설계·아키텍처·백엔드 통합·테스트 설계·문서를,
계약 담당은 배포/DB/API/정책/표시 호환을, 런타임 담당은 AI/RAG 실행을 맡았다.
독립 담당은 구현 없이 코드·개인정보·경계 검증을 수행했다. UI 재설계와 인프라 운영은 제외했다.

## 구현

- `local_transformers`와 nullable `local_model_ref`를 domain/storage/API/정책에 추가했다.
  로컬 참조는 endpoint/runner/secret/외부 전송/자동 재시도와 혼용할 수 없다.
- `Settings.local_model_refs`는 모델 ID, 40자리 revision, 로컬 snapshot 경로, CPU/float32,
  입력 토큰 한도를 검증한다. 업무 코드에 특정 Gemma ID나 개인 경로를 고정하지 않았다.
- `LocalModelHost`는 앱 수명 동안 한 모델을 재사용하고 한 번에 하나의 추론만 허용한다.
  로드·생성은 별도 스레드에서 실행한다. 취소와 timeout은 중단 신호 뒤 실제 worker 종료를
  기다리며 반복 취소에도 점유를 조기에 해제하지 않는다. 실패한 엔진은 버리고 다음 요청에서
  다시 로드한다. 앱 shutdown도 소유 worker를 기다린다.
- 로더는 HF cache의 모델명/고정 revision 경로를 확인하고 local-files-only,
  remote-code 금지, safetensors, eval/inference_mode를 사용한다. 경로 결합 확인은
  가중치의 암호학적 무결성 검증을 의미하지 않는다.
- schema2의 `status`, claims, evidence UUID를 엄격히 파싱한다. 중복 JSON key·추가 필드·
  잘린 출력·형식 불일치·입력 한도 초과를 거부한다. 기존 인용 검증을 거치며 입력/출력 토큰을
  감사에 전달한다. schema3 계산 증명은 이번 provider 범위 밖이다.
- 요청마다 생기는 resolver와 연결 확인은 동일 앱 host를 사용한다. `health()`는 실제 모델을
  로드하므로 별도 운영 승인 전 호출하지 않았다. 네이티브 연산 강제 종료는 제공하지 않는다.
- 프론트에 provider 표시와 busy/입력 초과 안내를 연결했다. 새 비공개 경로를 API에 노출하지
  않으며 API에는 symbolic reference만 전달한다.

## 실제 검증

아래 명령은 기존 backend venv에서 실행했으며 모델·DB·Elasticsearch 호출 없이 synthetic/mock을
사용했다. 테스트 수는 서로 겹치므로 합산한 고유 테스트 수가 아니다.

| 검증 | 실제 결과 |
| --- | --- |
| `pytest tests/unit/labs/rag/generation tests/unit/labs/rag/conversations tests/unit/labs/rag/search tests/unit/labs/rag/deployments tests/unit/labs/rag/policies tests/unit/test_config.py -q --tb=short` | 1453 PASS / 4 skip / 기존 Starlette 경고1, 111.56초 |
| 로컬 host/adapter 테스트 2파일 | 34 PASS |
| 메인 resolver/등록/API 오류/검색 인용 테스트 4파일 | 14 PASS |
| 배포·정책 단위 전체 | 122 PASS |
| 독립 실행: host/adapter/resolver/pipeline/등록 계약/migration SQL 7파일 | 66 PASS, 11.36초 |
| 프론트 관련 5파일 | 첫 묶음46 PASS/기존 Codex 테스트1 timeout(5초); 해당 SearchPage 파일 그대로 재실행24/24 PASS. timeout 설정 변경 없음 |
| 전체 프론트 TypeScript, 변경 파일 ESLint, OpenAPI 생성·일치 검사 | PASS |
| Ruff 및 scoped strict mypy | 메인7·계약6·런타임2 source 파일 PASS |
| Alembic heads / migration SQL 생성 | 단일 `0065_local_transformers`, offline upgrade/downgrade 검사 PASS; DB 적용 아님 |
| 프로젝트 역할 계약, `git diff --check` | PASS |
| 의존성 TOML 및 기존 잠금 비교 | parse PASS, 기존 외부 package152개의 버전·아티팩트·해시 무변경 |

TDD에서는 모듈 부재, 배포 계약 부재, schema2 status 거부, timeout drain 중 취소 우선순위,
새 오류 코드의 generic 변환을 먼저 재현했다. 메인 pipeline 테스트의 감사 필드명 오류는 fixture를
수정했다. 독립 리뷰가 찾은 `provider_busy`/`provider_input_too_large` allowlist 누락은
2 RED→2 GREEN으로 수정했고 독립 재확인에서 503/422를 유지했다. 현재 독립 리뷰 차단 결함은 없다.
발견·수정 근거는 이 worklog에 보존하며 운영 문제 이력 DB 갱신은 쓰기 승인 부재로 미실행이다.

`uv lock --offline`은 설치된 uv.exe 실행 자체가 접근 거부돼 실행되지 않았다. 새
`generation-cpu` extra는 이미 잠긴 Transformers/PyTorch 아티팩트를 재사용하도록 선언·잠금
메타데이터만 수정했다. uv의 공식 lock 일치 검증은 미완료이며 TOML 검사로 대체 통과를 주장하지
않는다. 설치·업데이트·캐시 제거는 하지 않았다.

## 하드웨어·모델 후보 및 승인 경계

현재 Win32_ComputerSystem/OperatingSystem/Processor/VideoController의 사양 필드 조회는
모두 접근 거부였다. CPU/RAM/GPU/여유 메모리는 미확인이고, 과거 ARM64 기록을 현재 사양으로
확정하지 않았다. 별도 사양 읽기 승인을 요청했으며 기존 Docker context/프로세스 읽기 승인을
재사용하지 않았다. 제한을 우회하지 않았다.

설치 메타데이터에는 torch `2.13.0+cpu`, transformers `5.16.1`, tokenizers `0.23.1`,
safetensors `0.8.0`, sentence-transformers `6.0.0`이 있고 accelerate는 없다. 이는
패키지/native DLL 작동이나 모델 호환성 검증이 아니다. 기존 모델 캐시 최상위에는 E5/OCR 등이
있고 Gemma 이름은 없었다. 다른 경로 전체에 모델이 없다고 단정하지 않는다.

조건부 첫 후보는 [google/gemma-3-1b-it](https://huggingface.co/google/gemma-3-1b-it/tree/main)이다.
공식 파일 목록은 weights 약2GB와 tokenizer 관련 약39MB를 제시하며 Gemma 라이선스 동의가
필요하다. 실제 revision은 아직 미확보다. 공개 API 메타데이터 요청은 네트워크 실패,
웹 도구의 개별 파일 조회는401이어서 로그인·동의·다운로드로 이어가지 않았다.
[Google 공식 모델 카드](https://ai.google.dev/gemma/docs/core/model_card_3)의 1B 컨텍스트 한도는32K다.
최초 실행은 훨씬 작은 입력 한도에서 검증해야 한다. CPU float32 가중치 약4GB, 실행 여유 포함
6–8GB 이상의 여유 RAM은 계획용 추정이며 현재 장비 충족 여부·peak·속도 보증이 아니다.
기존 E5 및 서비스 메모리도 별도로 필요하다. 한국어 답변·엄격한 JSON/인용 품질은 미평가다.

다음 순서:

1. 사양 필드 읽기 승인 후 현재 CPU/아키텍처/RAM/GPU/여유를 확인한다.
2. 정확한 immutable revision·artifact 크기·라이선스와 저장 위치를 확정하고 사용자에게 제시한다.
3. 다운로드/필요한 설치/로딩·합성 추론의 정확한 범위를 별도로 승인받는다. 기존 패키지로
   동작하면 불필요한 설치를 하지 않는다. uv 접근 문제도 해결 후 lock 검증한다.
4. 본래 DB 백업·현재 schema·0064/0065 적용 영향·재시작 범위를 별도 승인받는다.
   0065는 deployment nullable 열과 provider/reference/policy 제약을 바꾸며, 로컬 배포·참조·정책이
   있으면 downgrade를 거부한다. 실제 migration, deployment/profile/저장 구성 등록은 하지 않았다.
5. 승인된 원래 환경에서 synthetic 업로드→READY→검색→답변/인용→저장·복원→취소/다음 질문을
   확인한다. 현재 alias frozen/첨부 대기/과거 cancelled 불완료 문제는 별도 해결 대상이다.

커밋·푸시·DB 쓰기·migration 적용·서비스/보안 설정·자동화/학습 예약 변경·실모델 실행·비용 발생
외부 호출은 0이다. 전체 RAG 완료나 본래 환경 동작 완료로 보고하지 않는다.


## 2026-10-12 기존 DB0064·0065 적용

사용자가 데이터 삭제·재입력 없는 기존 DB 변경을 승인했다. 대상은 기존
`127.0.0.1:15432/ai_workshop_local_clean` 한 곳이며, 원본 migration은 수정하지 않았다.
0064·0065 전체와 독립 안전 검토에서 기존 행 DELETE/UPDATE/TRUNCATE, 실제 키 발급,
자격증명·권한 부여 또는 정책 행 변경이 없음을 확인했다. 0064는 사건 기록·검증 스키마이고
0065는 nullable 열 및 provider/reference/policy CHECK 변경이다.

- 기존0063, 대상 객체 선행 생성 없음, 진행 중 RAG/역할 키 작업·다른 활성 트랜잭션0을 확인했다.
- 백업: `.local-data/backups/schema0065-20261012/before.dump`, 28,631,642bytes.
  SHA-256 `ef9f0f5172c0af05761cde6266c22befee2d7cc7526ae2779d7c0fd423f72661`.
  PostgreSQL17.11에서 exported snapshot을 공유한 pg_dump18.6 custom archive를 생성했다.
  전체122테이블 TOC와 pg_restore 전체 archive 디코딩을 확인했다. 실제 복원 시험은 하지 않았다.
- 정확한0063→0064→0065 Alembic 생성 SQL을 한 트랜잭션으로 적용했다.
  잠금 대기1초, DDL 직전 전체 트랜잭션 타이머5초와 실제 설정값을 확인했다.
  초기 읽기·적용·커밋을 합한 시간은7.202초이며 잠금 보유 시간 측정값은 아니다.
  커밋 전후 기존122테이블의 원래 열·행 수·정렬 행 digest가 모두 일치했다.
- 이슈29·사건230·문서57·문서 버전67·연결101개, 원본/Asset8개,
  구성6·구성 버전10·프로파일18·도메인 연결 버전2개를 포함해 기존 행을 보존했다.
  이슈 연결 고아0·저장 문서 SHA 불일치0·READY원본8개의 파일 크기/SHA 불일치0이었다.
  `.env`·두 migration·원본 저장소·이슈/84일 학습 문서의62파일 해시를 보존했다.
  학습 제품 DB 기록0은 그대로이며 학습 진도를 완료 처리하지 않았다.
- 최종 revision0065, local_model_ref 열 존재/기존 값 모두NULL, 새 키 사건0행,
  검증된 CHECK 제약과 함수3개·활성 트리거2개를 확인했다.
  함수는 SECURITY DEFINER가 아니다. 실제 키 발급·receipt·gate 해제는 수행하지 않았다.

백업과 본문 없는 증거는 같은 로컬 백업 폴더의 `before.json`, `backup.json`,
`sql.json`, `applied.json`, `verified.json`에 보존하며 Git에 추가하지 않는다.
이 백업은 복구 자료이므로 작업 완료만으로 정리하지 않는다. 복구 시 정확한 archive SHA와
목차/디코딩을 다시 확인한 뒤 기존 역할·확장과 원본 저장소를 보존하는 pg_restore 절차를
별도 승인해야 한다. 현재 DB 덮어쓰기·새 DB 생성·실제 복원은 하지 않았다.
0064 사건 기록이 생기거나0065 Transformers 배포/참조/정책이 생기면 downgrade가 거부된다.
이력 삭제·강제 downgrade·stamp로 우회하지 않으며, 우선 앱 호환 복원/forward fix를 검토한다.

서비스·Docker·Elasticsearch 상태, 모델 등록·health 기록·활성 구성·factory 코드·실모델 호출,
설치·커밋·푸시는 변경하지 않았다. 제품 코드가 그대로이므로 전체 단위/타입/린트 테스트는
재실행하지 않았다. 실제 복원 가능성의 실행 검증과 앱 전체 RAG 수용은 미검증이다.

독립 담당도 실제 READ ONLY 연결에서0065·122테이블·62파일·백업 SHA·이슈 연결101개·READY원본8개 보존을 재확인했다. 독립 확인에서도 실제 복원 시험·앱 동작 검증은 제외했다.


### 승인된 백업 휴지통 이동

2026-10-12 사용자가 이번 백업 한 파일의 휴지통 이동을 명시 승인했다.
`before.dump`의 경로·28,631,642bytes·기록된 SHA-256·reparse 부재·배타 읽기 가능성을
재확인한 뒤 Windows IFileOperation으로 이동했다. 영구 삭제 동작은 callback에서 차단했다.
원본 경로 부재, 휴지통 파일 존재 및 동일 SHA를 확인했으며 새 백업은 생성하지 않았다.
다른 백업·DB·원본·학습 기록·마이그레이션 증거는 변경하지 않았다.
이동 영수증은 `.local-data/backups/schema0065-20261012/recycle-receipt.json`이다.
복원이 필요하면 Windows 휴지통에서 원래 위치가 `schema0065-20261012`인 `before.dump`를
선택해 복원한다. 위 백업 검증은 이동 전 사실이며, 현재 원래 경로에 백업이 남아 있다는 뜻은 아니다.
