# 휴지통 순수 계약 구현 기록

- 계획: [1단계 구현 계획](../superpowers/plans/2026-09-13-asset-trash-contracts.md)
- 설계: [휴지통·복원·영구 삭제](../superpowers/specs/2026-09-13-asset-trash-purge-design.md)
- 상태: 1단계 순수 계약 구현·검증 완료. 사용자 삭제 기능 완료 기록이 아니다.

## 역할과 범위

오케스트레이터는 요구·테스트 설계 및 통합, Python 구현 담당은 순수 함수와 단위 테스트,
독립 검토 담당은 명세·보안·프라이버시, 별도 최종 검증 담당은 계약 간 연결을 확인한다.
개별 Task의 구현과 승인 책임은 분리한다. main에서 작업하며 기존 UI 변경은 보존한다.

## 실행 경계

- 기존 backend 가상환경만 사용하고 `-B`, `-p no:cacheprovider`로 단위 테스트한다.
- 상태 전이, 명시적 보관 기한, 현재 capability 행위 판정, 정리 영수증 완료 판정만 구현한다.
- DB·API·UI·worker·실사용 문서·원본·파생물·캐시는 변경하지 않는다.
- 실제 부재 확인, 개인 소유권/회원 활성 SQL 검사, 자동 삭제, 백업 정리는 후속 단계다.
- 신규 의존성·테스트 서버·DB를 만들거나 외부 모델을 호출하지 않는다.

## 검증

| 범위 | 결과 | 검토 / 커밋 |
|---|---|---|
| 변경 전 Assets 기존5개 테스트 파일 | 69 passed, 기존 Starlette/httpx deprecation warning1건 | 메인 기준선 |
| Task1 상태 전이 | 행동 RED11실패 → GREEN69통과, mypy·Ruff 통과; 메인69재검증 | 독립 명세·품질 승인, bb25db2 |
| Task2 보관 정책 | 행동 RED13실패 → GREEN17통과, mypy·Ruff 통과; 메인17재검증 | 독립 명세·품질 승인, 33a7486 |
| Task3 권한 정책 | 보완 행동 RED5실패 → GREEN37통과, mypy·Ruff 통과; 메인37재검증 | 독립 보안·명세·품질 재검토 승인, 001df2a |
| Task4 삭제 완료 증거 | 행동 RED24실패 → GREEN24통과, mypy·Ruff 통과 | 독립 프라이버시·명세·품질 승인, 1715dda |

기존 Starlette/httpx 경고는 이번 코드 이전에도 재현됐다. 관련 의존성 변경은 별도 작업이며
성공 결과에서 경고를 숨기지 않는다. 전체 변경 독립 최종 검토도 승인됐다(코드 지적 없음).

Task3의 최초 RED는 함수 부재 오류라 행동 검증 요건을 충족하지 못했다. 독립 리뷰에서 차단한 뒤,
선언은 유지하고 본문을 미구현 상태로 되돌려 실제 권한 assertion5개 실패를 확인하고 최소 구현했다.
이후37개 통과와 정적 검사·재검토를 확인했다. 최초 실행을 유효한 TDD로 소급 표기하지 않는다.

## 메인 최종 실행

작업 디렉터리는 backend, 기존 가상환경을 사용했다. 기존 Assets 회귀에 필요한 secret은
테스트 프로세스에만 합성 값으로 지정했고 실제 환경 파일이나 자격 값을 읽지 않았다.

```text
.venv/Scripts/python.exe -B -m pytest tests/unit/platform/assets -q -p no:cacheprovider
199 passed, 1 warning in 9.42s (exit 0)

.venv/Scripts/python.exe -B -m mypy src/ai_workshop/platform/assets/lifecycle.py src/ai_workshop/platform/assets/trash_policy.py src/ai_workshop/platform/assets/purge_contracts.py
Success: no issues found in 3 source files (exit 0)

.venv/Scripts/python.exe -B -m ruff check --no-cache src/ai_workshop/platform/assets/lifecycle.py src/ai_workshop/platform/assets/trash_policy.py src/ai_workshop/platform/assets/purge_contracts.py tests/unit/platform/assets/test_asset_lifecycle.py tests/unit/platform/assets/test_trash_policy.py tests/unit/platform/assets/test_purge_contracts.py
All checks passed! (exit 0)
```

테스트199건은 기존69건과 신규130건이다. 테스트 소스는 회귀 검증 자산이며 실제 화면으로
나중에 옮기는 임시 화면 파일이 아니다. 사용자 원본을 테스트로 올리거나 삭제하지 않았다.

## 독립 최종 확인과 인계

- 구현4명: trash_lifecycle_impl, trash_retention_impl, trash_capabilities_impl, trash_purge_impl.
- 각 Task 명세·품질 및 보안/프라이버시 검토: trash_contract_task_review. 동일 변경 구현에 참여하지 않았다.
- 전체 변경 리뷰·오프라인 계약 조합: trash_contract_final_review. 기존 구현·Task 검토와 분리했다.
- 범위: 5d036c6..1715dda의 백엔드3개 모듈과 단위 테스트3개 파일만. DB/API/프론트 변경 없음.
- 독립 조합 명령: backend에서 프로세스 PYTHONPATH=src로 지정하고 합성 Python 입력을
  기존 `.venv/Scripts/python.exe -B -`에 전달했다. 결과 exit0.
- 관찰: 권한 철회 및 delete-only 복원 거부, UTC 확정 기한 유지, pending 복원 거부,
  writer/참조/누락·미검증/전용 잔존에 따른 완료 차단, 재시도와 공유 보존을 포함한 완료 후 PURGED 전이.
- 이는 순수 함수 호환성 검증이다. 실제 command의 증거 강제·SQL 권한/잠금/동시성·API·worker·
  실제 파일/색인 삭제·백업/외부 사본 정리·E2E를 검증한 것으로 확대하지 않는다.
- 다음 단계는 영속 모델·현재 SQL 권한·provenance와 migration/backfill dry-run의 상세 계획이다.
- 기존 root/이동창 UI 변경과 references는 보존했다. 원격 push는 실행하지 않았다.
- 임시 인계 기록은 저장소 루트가 아닌 해당 작업 전용 local-data 경로에만 두었다.
  정확 대상 정리에는 CACHE_POLICY의 조사·승인이 필요하며 이번에 광범위 캐시 삭제를 수행하지 않았다.
