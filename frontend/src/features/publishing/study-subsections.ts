// Display compatibility for labels in the existing plain-text published records.
// This is not a content validation whitelist: all other text remains unchanged.
export const legacyStudySubsectionLabels: ReadonlySet<string> = new Set([
  "초기 문제", "분리한 판단", "후속 설계", "남겨 둔 실패 경계", "문제",
  "관찰 사실", "선택과 이유", "변경 사항", "배운 점", "선택과 개선",
  "발견한 결함", "PDF 확장", "확인된 원인", "보완", "인계 개선",
  "검토 중 확인한 원인", "개선", "설계 판단", "관찰과 원인", "요구",
  "설계 선택", "문맥과 근거", "실패 처리", "이력과 권한", "발견한 문제",
  "추가로 발견한 문제", "설계 문제", "정책 경계", "오류와 관찰", "관찰한 문제",
  "효율과 실패 처리", "문제와 관찰", "검증 판단", "관리 화면", "개선 과정",
  "게임형 공간 확장", "발견한 결함과 보완", "개선과 판단", "확인된 사실과 가설",
  "복구", "재발 방지와 실제 큐",
]);
