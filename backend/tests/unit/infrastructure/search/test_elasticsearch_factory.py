from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch


async def test_factory_configures_the_settings_elasticsearch_url() -> None:
    settings = Settings(
        secret_key="x" * 32,
        elasticsearch_url="http://127.0.0.1:9200",
    )

    client = create_elasticsearch(settings)
    try:
        configured_url = str(client._transport.node_pool.get().base_url).rstrip("/")
        assert configured_url == settings.elasticsearch_url
    finally:
        await client.close()
