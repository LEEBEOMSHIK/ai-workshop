# 학습 목록 기술 주제 표시

## 범위와 기준

- 사용자 요청: 카드의 카테고리를 더 잘 구분하고 목록 표시 개수를 설명한다.
- 낮은 위험의 프론트엔드 표시 변경. 구현 담당과 독립 리뷰 담당을 분리한다. API·학습 데이터·모델·저장·정렬 변경은 없다.
- 기술 주제를 제목 아래 작은 중립 배지로 옮기고 라벨을 붙인다. 복수 분류와 미등록 키를 보존하며 빈 주제는 기록 종류로 대체한다.
- 공통 배지와 디자인 토큰을 재사용한다. 디자인 시스템에도 실제 분류 컴포넌트 예시를 둔다.

## 목록 표시 기준

- 프론트엔드는 한 열에 한 카드씩 표시한다.
- 목록 요청은 별도 `limit`을 보내지 않으며 서버 `LearningLimits.page_default`를 따른다. 본래 환경 설정을 읽은 값은 20이다.
- 현재 화면은 실제 실행 3건과 미실행 계획 1건, 총 4건이며 다음 페이지가 비활성이다.
- 한 화면에 동시에 보이는 수는 카드 본문 길이와 창 높이에 따라 달라진다.

## 검증

- 프론트엔드 관련 19건 통과. 복수 분류·미등록 키·빈 주제 대체·비조작성 신규 검증 포함.
- TypeScript 및 대상 ESLint 통과. 독립 코드 검토 차단 0건, 독립 테스트 10건 통과.
- 본래 Chrome에서 네 카드의 제목 아래 분류, 최신순 유지, 라이트/다크 표시 확인. 375px 및 320px 가로 넘침 없음. 임시 화면 크기와 기존 다크 모드를 복원했다.
- ISSUE-00051에 진행 이력을 저장하고 실제 화면에서 재조회했다.
- 전체 프로덕션 빌드는 수행하지 않았다. 페이지 크기를 변경하거나 실제 학습을 실행하지 않았다.

## 변경 파일

- `frontend/src/features/learning/LearningSequence.tsx`: 재사용 가능한 `LearningRecordClassification`, 제목 아래 배치.
- `frontend/src/features/learning/LearningSequence.module.css`: 토큰 기반 분류 배지·줄바꿈·수정일 배치.
- `frontend/src/features/learning/LearningLineage.test.tsx`: 분류 보존과 대체 표현 검증.
- `frontend/src/app/(workspace)/workshop/design-system/page.tsx`: 실제 분류 컴포넌트 예시.
- `docs/guidelines/ui-style-guide.md`, 이 기록 및 `WORKBOARD.md`: 적용 기준·검증 결과.
