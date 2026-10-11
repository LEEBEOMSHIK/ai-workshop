# RAG 실패 모니터링의 근거 개수 표시 수정 — 2026-10-05

본래 수정 런타임 평가 중 인용 검증 실패의 실행 상세가 `생성에 전달된 전체 근거 (0)`로
표시됐다. 독립 READ ONLY/rollback과 실제 `ExecutionReadService.detail`에서 선택 단계
완료·선택77개·관측 선택 ID77개를 확인했지만 저장된 실패 결과와 읽기 API의 원문 배열은
0개였다. 현재 원문 권한 거절은 관측되지 않았다. 성공 경로는 원문 payload를 저장하고
실패 경로는 관측 ID만 남기는 기존 계약인데, 배열 길이를 실제 전달 개수로 명명한
프론트 표시가 원인이다. 문제는 정상 관리 API로 ISSUE-00025에 등록했다.

`ExecutionDetailPage.tsx`의 목록을 `기록된 생성 근거 원문 (N)`으로 정정하고 선택 개수를
기존 선택 관측에서 별도로 표시했다. 양수 선택과 빈 원문 목록에만 기록 없음 안내를
표시한다. 선택 수 미기록을0으로 만들거나 실제 선택0을 누락으로 표시하지 않는다.
입력 예산에서도 `선택된 근거 단위`로 정정했다. 실제 공급자 전송 완료를 단정하지 않는다.
기존 기본 접힘·8처리 단계·인용과 원문 버튼·권한·레이아웃·API·실패 저장 계약·평가
런타임을 유지했다. 구현 담당의 수정 범위는 해당 컴포넌트와 `ExecutionMonitoring.test.tsx`
두 파일이며 루트가 독립 검토·검증·통합을 맡았다.

검증은 다음 범위에서 완료했다.

- 변경 전 신규4회귀 실패·기존4통과(11.79초), 변경 후8통과(6.40초).
- 루트 독립 동일 회귀8통과(9.09초), 전체 TypeScript와 변경 두 파일 ESLint exit0.
- 공백 검사 exit0. 기존 LF/CRLF 변환 안내만 발생했다.
- 본래 로그인된 Chrome의 실제 실행 `de9dbde7-574e-4dba-b28f-63431e681e4d`에서 기본
  접힘 `기록된 생성 근거 원문 (0)` 확인. 펼친 뒤 선택77개·표시 가능한 원문 기록 없음
  안내를 실제 AX와 스크린샷으로 확인했다. 새 질문·모델 호출·서버 재시작 없이 검증했다.
- 정상 관리 API의 ISSUE-00025 verifiedr2는 이 표시 수정 범위로 기록했다.

재현 명령은 기존 `frontend` 디렉터리에서 실행한다. 초기 pnpm launcher가 Vitest를
인식하지 않아 설치 없이 기존 Node entrypoint를 사용했다.

```powershell
node node_modules/vitest/vitest.mjs run src/features/rag/executions/ExecutionMonitoring.test.tsx --pool=threads --maxWorkers=1 --reporter=dot
node node_modules/typescript/bin/tsc --noEmit --pretty false
node node_modules/eslint/bin/eslint.js src/features/rag/executions/ExecutionDetailPage.tsx src/features/rag/executions/ExecutionMonitoring.test.tsx --max-warnings 0
```

실패 원문 payload 추가 저장이나 거절 초안 복원은 구현하지 않았다. 실제 숫자 검증
실패의 상세 원인을 확정하지 않으며 전체75건 평가·후보 수용·본래 도메인 적용·신규
대화 생성과 멀티턴·별칭 종료 proof를 완료했다고 보고하지 않는다. 기존 계정·자료·활성
연결·이전 불변 보고서·평가 결과·차단 gate는 보존했다. staging/commit/push는 없다.
