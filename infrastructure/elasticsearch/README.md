# 로컬 Elasticsearch

Elasticsearch는 자산운용 문서 RAG 검색용으로 다시 만들 수 있는 로컬 projection이다.
PostgreSQL의 문서 메타데이터·권한과 객체 저장소의 원본은 authoritative source로 유지하며,
Elasticsearch 색인만으로 원본을 복구하지 않는다.

Compose에서는 `elasticsearch` 서비스가 단일 노드로 실행되고, 호스트 포트는
`127.0.0.1:${ELASTICSEARCH_PORT:-9200}`에만 바인딩된다. Compose 네트워크의 backend와
worker는 `http://elasticsearch:9200`으로 연결한다. 로컬 개발 Compose에 한해 보안을
비활성화했으므로 이 구성을 외부에 노출하거나 운영 환경에 재사용하지 않는다.

로컬 서비스를 시작하려면 다음을 실행한다.

```powershell
docker compose -f infrastructure/compose/compose.yaml up -d elasticsearch
```
