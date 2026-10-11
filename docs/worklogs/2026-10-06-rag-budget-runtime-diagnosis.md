# 본래 RAG 입력 예산·DLL 런타임 원인 확인

- 기준일: 2026-10-06 KST
- 관련 문제: ISSUE-00005 근거 선택, ISSUE-00029 Windows DLL 재발 방지
- 이전 [본래 Chrome·HTTP 세션 검증](2026-10-06-rag-numeric-proof-browser.md)의 동결 DB v1과 파일은 변경하지 않는다.
- 본래 계정·DB0063·자료·활성v4·후보·별칭을 유지했다. 새 대화·문서·모델 요청·75회 반복·서버 재시작·환경 생성·패키지 변경·Git 작업·정리는 하지 않았다.

## 근거가 제외된 정확한 경계

독립 verifier는 기존 마지막 turn `c0d0d329-1509-4fb2-8832-cb9d7e185f7a`의 진단을 실제 원본 청크·근거 단위와 읽기 전용 SQL로 대조했다. 원문 본문을 가져오거나 별도 기록으로 복사하지 않고 ID·개수·문자 길이·페이지·출처 상태만 집계했다.

| 그룹 | 관련성 | 실제 근거 단위 | 원문 문자 합 | 위치 | 제외 원인 |
| --- | --- | ---: | ---: | --- | --- |
| 첫 그룹 | 통과 |33|712|PDF2쪽|단위33 > 상한32 |
| 두 번째 그룹 | 통과 |36|683|PDF1쪽32단위+2쪽4단위|단위36 > 상한32 |
| 세 번째 그룹 | 미달 |38|598|PDF2·3쪽|관련성 임계값 미달, 예산 선택 검사 전 |

실제 활성 v4의 예산은 그룹8·단위32·문자12000이다. 적격 두 묶음은 각각 단독으로 단위 상한을 넘으므로 누적 경쟁 이전에 제외된다. 문자 상한이나 그룹 수는 이 요청의 제외 원인이 아니다. 정상 `insufficient_evidence`는 검색 실패가 아니라 선택0에 따른 생성 생략이다.

전체107단위의 chunk/projection/element ID·문자 offset·PDF page/bbox·evidence_eligible는 확인됐다. 표 cell의 row/column 위치는 모두 null이다. 첫 집계에서 JSON null에 대한 SQL `IS NOT NULL`을 표 셀 정보 존재로 오해한 결과를 바로잡았고, JSON null/object를 구분한 읽기 전용 재조회로 present0을 확인했다. 표 헤더·행 관계가 복구됐다는 증거는 아니다.

불변 v4 후보·v5·v6은 동일 `resolve_evidence_budget` 인터페이스로 그룹8·단위128·문자12000을 해석한다. 기존 합성 `test_pdf_context_budget.py`도33단위/712문자의 전체 보존·32제외/128수용을 검증한다. 현재 코드가 한도를 잘못 계산한 결함으로 판단하지 않는다. 예산이 큰 후보가 존재해도 정답 품질·인용·승격 조건을 대신하지 않으므로 활성 연결을 바꾸지 않았다.

## DLL 차단 원인

프로젝트 DLL `scipy/optimize/_lsap.cp313-win_amd64.pyd`의 과거3077 이벤트는 `VerifiedAndReputableDesktop`와 GUID `0283ac0f-fff1-49ae-ada1-8a933130cad6`를 기록한다. Microsoft가 명시한 Windows Smart App Control 기본 정책과 일치한다. [Microsoft 정책 문서](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/inbox-appcontrol-policies)

21:37:49/21:39:11 KST의3077은 요청 서명 수준2·검증 수준1·status0xc0e90002를 기록했고 관련3033 및 동일 ActivityID의3089 네 건에서 서명 수0을 확인했다. 현재 파일 Authenticode는 NotSigned이며 DLL flat SHA256는 차단 당시와 동일하다. SciPy1.18.1 설치 RECORD의 해시·크기도 일치한다. 과거 차단은 강제 정책에 의한 서명 없는 DLL 로드 거절로 좁혀졌으며 파일 교체·훼손 근거는 없다. [Microsoft 이벤트 해석](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/appcontrol-debugging-and-troubleshooting)

파일은190976bytes이며2026-08-30 생성·수정 시각을 유지했다. Zone.Identifier가 없으므로 다운로드 차단 표시를 제거하는 `Unblock-File`을 적용할 근거가 없다. 공식 Python과 기존 venv launcher는3.13.15·Python Software Foundation의 유효 서명이다. Python만 다시 설치하는 것이 SciPy DLL의 서명을 바꾸지는 않는다.

23:47–23:51 KST 조사에서 현재 import-only 한 프로세스는 Torch2.13.0+cpu(4.599초), Sentence Transformers6.0.0(11.953초)를 통과했다. 마지막 SciPy `_lsap` import는 이미 로드된 모듈 확인이며 별도 cold-import 성공으로 세지 않는다. 모델·DB 호출은 없다. 같은 파일의 이후 허용 이유는 미확정이며 평판·캐시·네트워크 가설을 원인으로 단정하지 않는다. 현재 성공을 영구 복구·서버 재시작 후 검증·실제 모델 실행 성공으로 보고하지 않는다.

읽기 전용 `CiTool.exe -lp -json`은 OS의 E_ACCESSDENIED를 반환했다. 현재 정책 목록·현재 적용 상태는 독립 조회하지 못했으며 자동 승인 검토 거절이 아니다. 관리자 권한 획득이나 대체 경로로 우회하지 않았다. Smart App Control은 개별 앱 예외를 제공하지 않으므로 임의 허용·정책 해제·보안 완화를 수행하지 않았다. [Microsoft FAQ](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions)

ISSUE-00029는 open으로 유지한다. 신뢰 가능한 서명 배포 경로는 별도 호환성·공급망 검증이 필요하며 존재 여부를 확인한 패키지가 아직 없다. import readiness/명확한 단계 오류는 가능한 방어책이지만 공개 readiness 계약·시작 지연·오프라인 보장 검토가 필요한 별개 구현이다. 무조건 재설치·DLL 선행 로드·자동 재시도·모델 대체로 해결됐다고 보고하지 않는다.

## 구체화한 후속 수정

[예산 세부 진단 설계](../superpowers/specs/2026-10-06-rag-budget-diagnostics-design.md)는 기존 전체 묶음 선택과 정책을 유지하며 실제 선택 검사 시점의 수치만 대화·실행 모니터링에 추가하는 작은 변경이다. 입력 그룹 수·단위 수·문자 수, 이미 소비된 누계, 실제 상한과 최대3개의 초과 종류를 typed metadata로 전달한다. 그룹에만 붙이고 원문·질문·답변을 추가 저장하지 않으며 None 필드 생략으로 옛 결과를 보존한다. 미달 후보의 미검사와 충돌 때문에 취소된 선택을 구분한다.

독립 검토는 설계 차단 의견0, strict integer/enum·기존200/top_k 상한·진단 on/off의 동일 선택·추가 임베딩0·옛 데이터 무 backfill을 요구했다. 사용자 구현 범위 질문은 대기 중이다. 제품 코드·새 테스트·서버 반영은 시작하지 않았고 새 단위 테스트 통과나 UI 완료로 보고하지 않는다. 전체 묶음을 작은 구조 묶음으로 재구성하거나 한도를 바꾸는 기능은 이 작은 변경과 구분하여 별도 후보·평가·승인 경계를 따른다.

## 이력과 보존

독립 사전 baseline은 보호55테이블·기존8turn·과거155/82평가·새75평가/64판정 및 복원·환경·동결5보고서를 포함하며 읽기 전용 helper는 exit0이었다. 이번 원인과 미확정 범위는 정상 관리자 API로5/29에 새 사건·정확한 보고서 DB 버전을 추가 연결한다. 최종 보존 감사 메타데이터와 DB ID/버전/SHA는 동결 본문을 수정하지 않고 WORKBOARD와 작업 인계에 남긴다.

DLL 영구 복구·유효 답변·성공한 멀티턴·권한 철회·승격·별칭 종료·Git 인계는 아직 완료되지 않았다. 품질 개선만 남은 상태가 아니다.
