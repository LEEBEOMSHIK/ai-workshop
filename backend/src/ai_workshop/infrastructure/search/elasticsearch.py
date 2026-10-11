import ssl

from elasticsearch import AsyncElasticsearch

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.access_credentials import AccessCredentialError


def create_elasticsearch(settings: Settings) -> AsyncElasticsearch:
    if settings.elasticsearch_access_epoch_id is None:
        return AsyncElasticsearch(settings.elasticsearch_url, request_timeout=30)
    if settings.elasticsearch_api_key is None or settings.elasticsearch_role is None:
        raise AccessCredentialError("elasticsearch_capability_required")
    if settings.elasticsearch_ca_certs is None or not settings.elasticsearch_url.startswith(
        "https://"
    ):
        raise AccessCredentialError("elasticsearch_tls_invalid")
    try:
        # Explicit CA only; force hostname/SAN verification for direct IP routes too.
        context = ssl.create_default_context(cafile=str(settings.elasticsearch_ca_certs))
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return AsyncElasticsearch(
            hosts=settings.elasticsearch_url,
            ssl_context=context,
            api_key=settings.elasticsearch_api_key.get_secret_value(),
            request_timeout=30,
            max_retries=0,
            retry_on_timeout=False,
            retry_on_status=(),
        )
    except (OSError, ValueError):
        raise AccessCredentialError("elasticsearch_tls_invalid") from None
