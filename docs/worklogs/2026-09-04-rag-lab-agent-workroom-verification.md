# RAG 연구실 담당 에이전트 작업실 검증 기록

- 기준일: 2026-09-04
- 기준 커밋: `ed211a1a87557511df2ba2cd7036b148cbabe87d` 이후 main working tree
- 설계: `docs/superpowers/specs/2026-09-04-rag-lab-agent-workroom-design.md`
- 계획: `docs/superpowers/plans/2026-09-04-rag-lab-agent-workroom.md`

## 범위

- `/`의 전체 보기 링크는 `/labs`, RAG 총괄 캐릭터 CTA는 `/labs/rag`로 분리한다.
- `/labs/rag`에 RAG 총괄과 현재 구현된 여섯 기술 담당자 작업 장면을 제공한다.
- 담당자 선택 시 역할, 현재 작업, 입력·결과와 다음 인계를 접근 가능한 대화상자로 설명한다.
- 작업자 콘텐츠는 별도 JSON registry와 엄격한 parser에서 읽는다.
- 공개 catalog, backend API, DB, 모델 런타임과 인증 경계는 변경하지 않는다.

## TDD 증거

1. 메인 route 테스트는 기존 `AI Labs 살펴보기 → /labs`를 관찰하며 실패한 뒤 catalog CTA를
   사용하도록 수정해 통과했다.
2. 작업자 registry 테스트는 모듈 부재로 실패한 뒤 여섯 작업자, exact-key, slug, 중복,
   필수 문자열과 방어적 복사를 구현해 16개 테스트가 통과했다.
3. 작업자 캐릭터 테스트는 컴포넌트 부재로 실패한 뒤 공통 dialog 추출과 작업자 adapter를
   구현해 기존 총괄 회귀를 포함한 12개 테스트가 통과했다.
4. RAG 상세 테스트는 파이프라인 region과 작업자 trigger 부재로 2건 실패한 뒤 총괄 지휘대와
   여섯 작업대를 구현해 관련 route를 포함한 4개 테스트가 통과했다.
5. 모바일 시각 검사에서 한국어 소개 제목이 글자 단위로 나뉘는 현상을 확인했다. 스타일
   회귀 테스트가 실패하는 것을 확인한 뒤 `word-break: keep-all`을 적용해 4개 테스트가
   통과했다.
6. 독립 검토가 캐릭터와 실제 처리 주체의 혼동, 작업 순서·연결선 검증 누락을 지적했다.
   소개 문구를 기술 담당자로 정제하고 실제 처리는 서비스와 worker가 수행한다는 경계를
   화면에 명시했으며, 실제 DOM 순서와 3열·2열·1열 연결선을 실패 테스트부터 보완했다.

## 자동 검증

| 검사 | 결과 |
| --- | --- |
| RAG 공개 UI 대상 테스트 | 3 files, 24 passed (최종 보완 대상) |
| 전체 frontend 테스트 | 41 files, 168 passed |
| TypeScript | `pnpm typecheck`, exit 0 |
| ESLint | `pnpm lint`, exit 0 |
| Next.js production build | `pnpm build`, 11/11 routes, exit 0 |

전체 테스트는 build와 병렬 실행했을 때 worker 시작 전 90초 이상 출력이 없어 해당 세션을
중단했다. 단독 재실행에서는 worker가 약 2분 뒤 시작됐고 41개 파일·168개 테스트가 모두
통과했다. 환경의 worker 시작 지연으로 확인했으며 이를 숨기기 위한 timeout 또는 소스 변경은
하지 않았다.

## 실제 브라우저 검증

### 연결된 Chrome

- `/`에서 `연구실 전체 보기 → /labs`를 접근성 트리로 확인했다.
- RAG 총괄 말풍선의 `RAG 연구실 들어가기 → /labs/rag`를 선택해 실제 URL 이동을 확인했다.
- `/labs/rag`에 총괄과 여섯 작업자 trigger가 파이프라인 순서로 나타났다.
- 첫 `구조 분석가 루미`와 마지막 `품질 분석가 메트릭`의 서로 다른 현재 작업·입출력·인계
  내용을 확인했다.
- `Escape`로 대화상자가 닫히고 선택한 캐릭터 trigger로 초점이 복원됐다.
- viewport `1189×741`, DPR 2에서 문서 가로 overflow가 없었다.
- 최종 보완 후 여섯 기술 담당자 소개와 실제 처리 주체 경계 문구를 접근성 트리에서 다시
  확인했다.

### 연결된 Chrome의 격리 tablet iframe

- 같은 origin의 임시 검증 문서 안에 `768×1024` iframe viewport를 만들고 완료 후 문서를
  삭제했다. 애플리케이션 소스와 route에는 검증용 분기를 남기지 않았다.
- 작업대 6개는 `325px`씩 2열로 렌더됐고 위치는 `(0,0)`, `(341,0)`, `(0,480)`,
  `(341,480)`, `(0,960)`, `(341,960)`이었다.
- `innerWidth=768`, `clientWidth=scrollWidth=753`, `horizontalOverflow=false`였다.
- 첫 `구조 분석가 루미`, 중간 `색인 기술자 벡터`, 마지막 `품질 분석가 메트릭`을 각각
  선택했고 세 dialog 모두 viewport containment가 `true`, 초기 초점이 `소개 닫기`였다.

### 격리 headless Chrome CDP

- 강제 viewport: `390×844`, device scale factor 1
- `innerWidth=clientWidth=scrollWidth=390`, `horizontalOverflow=false`
- RAG 작업실 경계: `left=12`, `right=378`, `width=366`
- 모바일 dialog 경계: `left=0`, `right=390`, `top=332`, `bottom=844`
- dialog open 시 초기 초점: `소개 닫기`, body overflow: `hidden`
- 한국어 제목 수정 후 `구조 분석가 루미`와 `소개`가 단어 단위로 줄바꿈되는 것을 다시
  캡처해 확인했다.

검증을 위해 만든 `.local-data/browser-verification/rag-lab-agent-workroom`과 해당 profile을
사용한 Chrome 프로세스만 정확한 경로·명령줄 검사 후 제거했다. 사후 경로와 관련 프로세스는
모두 0개다.

## 독립 검토

- 1차 재검토에서 tablet 실제 동작 증거와 행 경계 연결선·장식 텍스트·테스트 수 불일치를
  지적받았다. 768px 실제 검증을 추가하고, 연결선을 빈 pseudo-element의 CSS border로
  바꾸며 행 끝에서는 다음 행을 가리키도록 보완했다.
- 마지막 mobile selector 우선순위까지 수정한 뒤 최종 재검토에서 Critical·Important·Minor
  모두 없음, `Ready: Yes`를 받았다.

## 남은 범위

- LLM Generation과 Reranker는 아직 실제 구현 완료 범위가 아니므로 작업자 캐릭터로 노출하지
  않았다.
- 공개 대화형 검색과 불변 공개 릴리스는 기존 2단계 후속 설계 범위다.
- owner 로그인 후 비공개 검색·관리 실제 데이터 smoke는 이 공개 UI 변경과 별개로
  `WORKBOARD.md`의 다음 작업에 남아 있다.
