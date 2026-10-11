# AI Workshop Kubernetes 학습·실습 후속 계획

- 등록일: 2026-10-08
- 상태: 사용자 요청으로 학습 범위 등록. 상세 배포 설계·클러스터 선정·설치·실습은 미착수
- 목적: AI Workshop의 실제 구성과 실행 흐름을 이용해 컨테이너 배포·통신·복구·확장·운영을 배우고 실험 기록으로 남긴다.
- 소유 영역: 프로젝트 공통 인프라·배포 학습. 새 AI Labs 영역이나 RAG 업무 규칙으로 분리하지 않는다.

이 문서는 후속 범위와 성공 기준을 정리한 인계 문서다. 실행 가능한 배포 manifest·명령·
이관 계약은 현재 환경 조사와 상세 설계에서 확정한다. 이번 등록은 Kubernetes 운영 적용 완료를 뜻하지 않는다.

## 순서와 학습 방식

현재 RAG 기능 마감을 우선하고 기존 Agents SDK → 벡터 저장소 비교 → 로컬 LLM 파인튜닝의
미착수 후속 순서는 유지한다. Kubernetes는 별도의 공통 인프라 후속 작업으로 그 뒤에 등록한다.
개념 정리와 현재 구조의 대응 설명은 먼저 준비할 수 있다. 사용자가 우선순위를 바꾸면
WORKBOARD와 각 계획의 착수 순서를 함께 갱신한다. SDK·벡터 DB·파인튜닝이 Kubernetes의
기술적 선행 조건인 것은 아니다. 품질 개선은 계속할 수 있으며 그 종료를 실습 착수 조건으로 삼지 않는다.

현재 구조에서 어떤 책임이 컨테이너·프로세스에 있고 어떤 책임을 Kubernetes가 담당하는지
설명한 뒤, 같은 앱 동작을 유지한 제한된 배포 실습과 측정으로 확인한다.
Kubernetes 사용을 위해 모듈형 모놀리스를 임의로 마이크로서비스로 분리하지 않는다.

| 학습 단계 | 현재 프로젝트와 연결 | 확인할 결과 |
| --- | --- | --- |
| 1. 구조와 기본 배포 | Next.js·FastAPI·worker와 Docker Compose를 Pod·Deployment·Service에 대응 | 제어 계층과 요청 경로 설명, 실제 적용 후보 구성요소의 배포·접속 확인 |
| 2. 설정·통신·권한 | 현재 typed settings·인증·API 통신을 ConfigMap·Secret·서비스 DNS·RBAC와 연결 | 비밀 미포함 설정, 실제 권한 거부·허용, 기존 로그인·문서 권한 보존 |
| 3. 상태 검사와 복구 | API health/ready와 종료·drain을 readiness/liveness/startup 및 종료 처리에 연결 | 준비 전 트래픽 제외, 준비 후 접속, 제한된 장애·재시작의 상태/시간/로그 기록 |
| 4. 확장·업데이트 | 웹/API replica와 background queue를 분리하고 rolling update·rollback을 비교 | 요청·대화·작업 중복 및 자료 손실 여부, 버전·오류율·복구 시간 측정 |
| 5. 영속 저장소 | PostgreSQL·Elasticsearch·파일·모델 캐시와 PVC·PV·StatefulSet의 책임 비교 | 원본·인덱스·벡터·파일의 저장 위치/수명 설명, 실제 이관은 별도 보존/복구 검증 후 결정 |
| 6. 관찰·비교·학습 기록 | 기존 실행 모니터링과 Pod 상태·event·로그·자원 지표의 진단 책임 연결 | Compose 대비 배포·복구·CPU/메모리/디스크·관리 비용 비교와 실패 기록 |

실습은 학습 항목마다 한 가지 동작을 바꾸고 전후를 비교한다. 확장과 장애 실습은 멱등성·
권한·작업 접수 경계가 확인된 구성요소부터 한다. Celery worker는 실제 task 소비자이며
Kubernetes Job과 동일한 개념으로 치환하지 않는다. beat의 중복 스케줄링과 미종료 작업을
먼저 검토하고 replica를 늘리지 않는다. HPA는 필요한 metrics 제공과 부하 실습 조건이 정해진 뒤 다룬다.

## 실제 착수 전에 결정할 사항

1. 기존 Docker·Windows·공식 Python·프론트/백엔드·네트워크·가용 CPU/메모리/디스크를 조사한다.
   kind·minikube·기존 Docker Desktop의 Kubernetes 지원 여부를 비교하고 로컬 클러스터 방법 하나를
   선택한다. 현재 설치·활성화 여부나 제품/버전은 조사 없이 가정하지 않는다.
2. 현재 container image·build·health/ready 의미·환경 주입·종료 계약을 확인한다.
   Codex 네이티브 Windows 실행, DPAPI private store, 원본 경로·모델 캐시와 기타 OS 의존 기능이
   Linux Pod에서 그대로 동작한다고 가정하지 않는다. 실제 지원 구성과 책임 경계를 상세 설계에 남긴다.
3. 기존 DB·자료를 어느 주소·권한으로 접근할지, 중복 API/worker·포트·소비자가 생기는지 확인한다.
   첫 적용 대상을 작게 정하고 전환/되돌림 및 측정 절차를 준비한다. 상세 계약 변경은 구현 전에 ADR로 남긴다.
4. 상태 저장 서비스와 원본 파일은 초기 실습에서 자동 이관하지 않는다. 기존 외부 서비스에 연결하는
   경우에도 Pod에서의 실제 도달·TLS·인증·권한·대화 복원을 검증해야 한다.
5. Namespace·클러스터·image·컨테이너·volume·cache·manifest마다 소유자·용도·정확한 위치·
   자원 예산·보존/인계·정리 조건을 기록한다. 생성·실행·중단 대상이 정해진 실습 절차를 검토한 뒤 적용한다.

## 데이터와 실행 경계

- 본래 계정·DB·문서·파일·권한·활성 프로파일·대화·큐를 보존한다. 사용자 검증용 별도 DB·
  계정·복제 애플리케이션 환경을 임의 생성하지 않는다. 로컬 클러스터 자체는 명시적으로 관리하는 학습 자원이다.
- Kubernetes namespace만으로 기존 앱 계정·문서 권한이나 비공개/공개 저장 경계를 대체하지 않는다.
- Secret의 base64 표현을 암호화로 간주하지 않는다. 실제 credential·kubeconfig·인증서 private key·
  원문은 Git/공개 manifest/로그에 넣지 않고 권한·저장·전달 계약을 확정한다.
- Pod replica·컨테이너 재생성·롤백이 기존 미종료 요청의 종료 proof·receipt·gate 해제나
  secured access floor 복구의 대체가 되지 않는다. ISSUE-00013과 기존 RAG 기능 완료 조건은 유지한다.
- 새 namespace에서의 성공을 본래 사용자 로그인·대화·업로드·검색·생성 성공으로 보고하지 않는다.
  실제 배포 구성에서 같은 자료·권한·세션·모니터링 흐름을 확인해야 한다.
- 기존 로컬 실행과 Kubernetes 실행을 구분해 기록하며, 이관·본래 반영·검증이 끝나기 전에
  보존 대상 환경이나 산출물을 삭제하지 않는다. 정리는 [캐시 정책](../../../CACHE_POLICY.md)을 따른다.

## 학습 기록과 흐름도

학습 기록은 공통 인프라 상위 분류 아래 Kubernetes 하위 주제로 정리하는 방향으로 준비한다.
현재 DB 카테고리·메뉴를 생성한 것은 아니며 Learning의 기존 기술 주제/연결 계약을 먼저 확인한다.
별도 메뉴를 계속 추가하기보다 기존 학습 기록·실험 및 `/workshop/flows`의 기술별 분류를 활용한다.

흐름도는 전체 보기에서 요청 → Service → API/worker → 저장소 흐름을 보여주고,
기술 상세에서 controller·Pod·readiness·재시작·rolling update·volume 연결을 설명한다.
실제 도입 전 콘텐츠는 계획/개념으로 표시하고 현재 Kubernetes가 실행 중이라고 표현하지 않는다.

각 실습에는 목적·가설·소스/설정/데이터 스냅샷·클러스터/도구 버전·변경 대상·전후 지표·
실패 단계·원인·원복 결과·남은 제한·산출물 위치를 남긴다. 모델의 비공개 내부 추론을 기록하지 않는다.

## 완료 기준

- 현재 앱에 대응되는 배포·통신·설정·복구·확장·저장 개념을 구현 근거와 함께 설명할 수 있다.
- 실제 선택한 로컬 클러스터에서 승인된 구성요소를 배포하고 본래 사용자 흐름 및 자료 보존을 검증했다.
- 제한된 장애·재시작·업데이트/롤백·확장 실습의 전후 결과와 실패 원인을 측정해 기록했다.
- Compose와 비교해 장단점과 운영 채택 여부를 판단했다. 실습 완료가 운영 전환을 자동 승인하지 않는다.
- 학습 기록·흐름도·관련 문서 연결 및 산출물 인계·정리 조건을 충족했다.

## 참고 정본

- [Kubernetes 기초 학습](https://kubernetes.io/docs/tutorials/kubernetes-basics/)
- [로컬 학습 환경](https://kubernetes.io/docs/setup/learning-environment/)
- [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [상태 검사](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [Secret](https://kubernetes.io/docs/concepts/configuration/secret/)
- [PersistentVolume](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- [프로젝트 시스템 설계](../../architecture/system-design.md)
- [본래 로컬 실행 정본](../../runbooks/local-development.md)
- [SDK 도입](2026-10-04-rag-agents-sdk-adoption.md), [저장소·파인튜닝 비교](2026-10-04-rag-vector-store-and-local-llm-experiments.md)

공식 문서 확인일은 2026-10-08이며 도구/API 버전·기능 지원과 실제 장치 조건은 착수 때 다시 확인한다.
