from elasticsearch import AsyncElasticsearch

from ai_workshop.config import Settings


def create_elasticsearch(settings: Settings) -> AsyncElasticsearch:
    return AsyncElasticsearch(settings.elasticsearch_url, request_timeout=30)
