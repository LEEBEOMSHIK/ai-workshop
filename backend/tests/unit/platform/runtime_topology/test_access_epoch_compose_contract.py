"""Offline contracts for controller assets; never interpolate the host environment."""

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[5]
BOOTSTRAP = ROOT / "infrastructure/compose/compose.access-epoch-bootstrap.yaml"
FINAL_COMPOSE = ROOT / "infrastructure/compose/compose.access-epoch-secured.yaml"
SECURED = ROOT / "infrastructure/elasticsearch/elasticsearch-secured.yml"
CONFIG_ROOT = "/usr/share/elasticsearch/config"
IMAGE = "docker.elastic.co/elasticsearch/elasticsearch:9.5.2@"
REQUIRED = re.compile(r"\$\{([A-Z_][A-Z_0-9]*):\?[^{}]+\}")


def load_asset(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"required controller asset missing: {path.name}"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def assert_required(value: str, name: str) -> None:
    match = REQUIRED.fullmatch(value)
    assert match is not None and match.group(1) == name


def assert_bootstrap_contract(document: dict[str, Any]) -> None:
    # Closed keys also reject merge/include hooks, extra routes, commands and secrets.
    assert set(document) == {"name", "services", "volumes"}
    assert document["name"] == "ai-workshop"
    assert set(document["services"]) == {"elasticsearch"}
    service = document["services"]["elasticsearch"]
    assert set(service) == {
        "image",
        "pull_policy",
        "network_mode",
        "restart",
        "environment",
        "volumes",
        "healthcheck",
    }
    assert service["image"].startswith(IMAGE)
    assert_required(service["image"][len(IMAGE) :], "AI_WORKSHOP_ES_ORIGINAL_MANIFEST_DIGEST")
    assert service["pull_policy"] == "never"
    assert service["network_mode"] == "none"
    assert service["restart"] == "no"
    environment = service["environment"]
    assert set(environment) == {"ES_JAVA_OPTS", "AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME"}
    assert environment["ES_JAVA_OPTS"] == "-Xms1g -Xmx1g"
    assert_required(
        environment["AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME"],
        "AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME",
    )
    # Authenticated readiness belongs to the controller's private-input helper.
    assert service["healthcheck"] == {"disable": True}
    assert set(document["volumes"]) == {"elasticsearch-data"}
    volume = document["volumes"]["elasticsearch-data"]
    assert set(volume) == {"external", "name"}
    assert volume["external"] is True
    assert_required(volume["name"], "AI_WORKSHOP_ES_ORIGINAL_VOLUME")
    mounts = service["volumes"]
    tls_files = {
        f"access-epoch-tls/{layer}/{filename}": f"{layer}/{filename}"
        for layer in ("http", "transport")
        for filename in ("node.key", "node.crt", "ca.crt")
    }
    assert len(mounts) == 8
    by_target = {mount["target"]: mount for mount in mounts}
    assert set(by_target) == {
        "/usr/share/elasticsearch/data",
        f"{CONFIG_ROOT}/elasticsearch.yml",
        *(f"{CONFIG_ROOT}/{target}" for target in tls_files),
    }
    assert by_target["/usr/share/elasticsearch/data"] == {
        "type": "volume",
        "source": "elasticsearch-data",
        "target": "/usr/share/elasticsearch/data",
        "volume": {"nocopy": True},
    }
    for target in ("elasticsearch.yml", *tls_files):
        mount = by_target[f"{CONFIG_ROOT}/{target}"]
        assert set(mount) == {"type", "source", "target", "read_only", "bind"}
        assert mount["type"] == "bind"
        assert mount["read_only"] is True
        assert mount["bind"] == {"create_host_path": False}
    config = by_target[f"{CONFIG_ROOT}/elasticsearch.yml"]["source"]
    assert config == "../elasticsearch/elasticsearch-secured.yml"
    assert (BOOTSTRAP.parent / config).resolve() == SECURED.resolve()
    for target, relative_source in tls_files.items():
        source = by_target[f"{CONFIG_ROOT}/{target}"]["source"]
        suffix = f"/{relative_source}"
        assert source.endswith(suffix)
        assert_required(source.removesuffix(suffix), "AI_WORKSHOP_ES_TLS_DIRECTORY")


def assert_secured_contract(config: dict[str, Any]) -> None:
    expected: dict[str, Any] = {
        "cluster.name": "${AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME}",
        "discovery.type": "single-node",
        "network.host": "0.0.0.0",
        "http.port": 9200,
        "transport.port": 9300,
        "xpack.security.enabled": True,
        "xpack.security.autoconfiguration.enabled": False,
        "xpack.security.enrollment.enabled": False,
        "xpack.security.authc.anonymous.roles": [],
        "xpack.security.authc.realms.file.file1.order": 0,
        "xpack.security.authc.realms.file.file1.enabled": True,
        "xpack.security.authc.realms.native.native1.order": 1,
        "xpack.security.authc.realms.native.native1.enabled": True,
        "remote_cluster_server.enabled": False,
        "node.roles": [
            "master",
            "data",
            "data_content",
            "data_hot",
            "data_warm",
            "data_cold",
            "data_frozen",
            "ingest",
            "ml",
            "transform",
        ],
    }
    for layer in ("http", "transport"):
        prefix = f"xpack.security.{layer}.ssl"
        expected.update(
            {
                f"{prefix}.enabled": True,
                f"{prefix}.verification_mode": "full",
                f"{prefix}.client_authentication": "required" if layer == "transport" else "none",
                f"{prefix}.key": f"access-epoch-tls/{layer}/node.key",
                f"{prefix}.certificate": f"access-epoch-tls/{layer}/node.crt",
                f"{prefix}.certificate_authorities": [f"access-epoch-tls/{layer}/ca.crt"],
            }
        )
    # Exact allowlist excludes passwords, extra listeners, overrides and auto-bootstrap settings.
    assert config == expected


def test_bootstrap_is_isolated_and_reuses_required_original_resources() -> None:
    assert_bootstrap_contract(load_asset(BOOTSTRAP))


def test_final_security_config_has_only_reviewed_settings_and_separate_tls_roots() -> None:
    assert_secured_contract(load_asset(SECURED))


@pytest.mark.parametrize(
    "name",
    [
        "AI_WORKSHOP_ES_ORIGINAL_MANIFEST_DIGEST",
        "AI_WORKSHOP_ES_ORIGINAL_VOLUME",
        "AI_WORKSHOP_ES_TLS_DIRECTORY",
        "AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME",
    ],
)
def test_all_external_references_reject_empty_or_unset_values_without_defaults(name: str) -> None:
    text = BOOTSTRAP.read_text(encoding="utf-8")
    expressions = re.findall(r"\$\{[^}]+\}", text)
    matches = [expression for expression in expressions if expression.startswith(f"${{{name}:")]
    assert len(matches) == (6 if name == "AI_WORKSHOP_ES_TLS_DIRECTORY" else 1)
    assert_required(matches[0], name)
    assert {REQUIRED.fullmatch(expression).group(1) for expression in expressions} == {
        "AI_WORKSHOP_ES_ORIGINAL_MANIFEST_DIGEST",
        "AI_WORKSHOP_ES_ORIGINAL_VOLUME",
        "AI_WORKSHOP_ES_TLS_DIRECTORY",
        "AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME",
    }


@pytest.mark.parametrize(
    ("location", "key", "unsafe"),
    [
        ("root", "networks", {"default": {}}),
        ("root", "include", ["compose.yaml"]),
        ("services", "api", {"image": "example/app"}),
        ("service", "network_mode", "host"),
        ("service", "ports", ["9200:9200", "9300:9300"]),
        ("service", "networks", ["default"]),
        ("service", "command", ["elasticsearch-reset-password", "--auto"]),
        ("service", "entrypoint", ["sh", "-c"]),
        ("service", "env_file", [".env"]),
        ("service", "environment", {"ELASTIC_PASSWORD": "synthetic-only"}),
        ("service", "environment", {"xpack.security.enabled": "false"}),
        ("service", "image", "docker.elastic.co/elasticsearch/elasticsearch:9.5.2"),
        (
            "service",
            "image",
            IMAGE + "${AI_WORKSHOP_ES_ORIGINAL_IMAGE_DIGEST:?ambiguous image identifier}",
        ),
        (
            "service",
            "image",
            IMAGE + "${AI_WORKSHOP_ES_ORIGINAL_IMAGE_ID:?local config image identifier}",
        ),
        ("service", "pull_policy", "always"),
        ("service", "healthcheck", {"test": ["CMD", "curl", "http://localhost:9200"]}),
        ("volume", "external", False),
        ("volume", "name", "${AI_WORKSHOP_ES_ORIGINAL_VOLUME:-new-data}"),
        ("volume", "driver", "local"),
        ("data", "volume", {"nocopy": False}),
        ("tls", "read_only", False),
        ("tls", "bind", {"create_host_path": True}),
        ("tls", "source", "${AI_WORKSHOP_ES_TLS_DIRECTORY:-./certs}"),
        ("tls", "target", f"{CONFIG_ROOT}/access-epoch-tls"),
        ("tls", "source", "${AI_WORKSHOP_ES_TLS_DIRECTORY:?required}"),
        ("tls", "source", "${AI_WORKSHOP_ES_TLS_DIRECTORY:?required}/http/ca.key"),
        ("tls", "source", "${AI_WORKSHOP_ES_TLS_DIRECTORY:?required}/controller/private.key"),
    ],
)
def test_bootstrap_contract_detects_unsafe_asset_mutations(
    location: str,
    key: str,
    unsafe: Any,
) -> None:
    original = load_asset(BOOTSTRAP)
    assert_bootstrap_contract(original)
    altered = deepcopy(original)
    service = altered["services"]["elasticsearch"]
    locations = {
        "root": altered,
        "services": altered["services"],
        "service": service,
        "volume": altered["volumes"]["elasticsearch-data"],
        "data": service["volumes"][0],
        "tls": service["volumes"][2],
    }
    locations[location][key] = unsafe
    with pytest.raises(AssertionError):
        assert_bootstrap_contract(altered)


@pytest.mark.parametrize(
    ("key", "unsafe"),
    [
        ("xpack.security.enabled", False),
        ("xpack.security.autoconfiguration.enabled", True),
        ("xpack.security.http.ssl.enabled", False),
        ("xpack.security.transport.ssl.enabled", False),
        ("xpack.security.transport.ssl.verification_mode", "certificate"),
        ("xpack.security.transport.ssl.client_authentication", "optional"),
        ("xpack.security.authc.anonymous.roles", ["superuser"]),
        ("xpack.security.authc.realms.file.file1.enabled", False),
        ("xpack.security.http.ssl.key_passphrase", "synthetic-only"),
        ("xpack.security.transport.ssl.certificate_authorities", ["access-epoch-tls/http/ca.crt"]),
        ("remote_cluster_server.enabled", True),
        ("node.roles", ["master", "data", "remote_cluster_client"]),
        ("transport.profiles.extra.port", 9400),
        ("cluster.initial_master_nodes", ["replacement"]),
    ],
)
def test_security_contract_detects_auth_tls_route_and_secret_regressions(
    key: str,
    unsafe: Any,
) -> None:
    config = load_asset(SECURED)
    assert_secured_contract(config)
    config[key] = unsafe
    with pytest.raises(AssertionError):
        assert_secured_contract(config)


def assert_final_compose_contract(document: dict[str, Any]) -> None:
    assert document["networks"] == {"default": {"external": True, "name": "ai-workshop_default"}}
    service = document["services"]["elasticsearch"]
    assert service["ports"] == ["127.0.0.1:9200:9200"]
    assert set(service["networks"]) == {"default"}
    attachment = service["networks"]["default"]
    assert set(attachment) == {"ipv4_address"}
    assert_required(attachment["ipv4_address"], "AI_WORKSHOP_ES_ORIGINAL_IPV4")
    # Both standalone documents share the exact protected image/storage/TLS contract.
    as_bootstrap = deepcopy(document)
    del as_bootstrap["networks"]
    adapted = as_bootstrap["services"]["elasticsearch"]
    del adapted["ports"]
    del adapted["networks"]
    assert "network_mode" not in adapted
    adapted["network_mode"] = "none"
    assert_bootstrap_contract(as_bootstrap)


def test_final_compose_reuses_original_network_and_required_verified_ip_with_loopback_only():
    assert_final_compose_contract(load_asset(FINAL_COMPOSE))


@pytest.mark.parametrize(
    ("location", "key", "unsafe"),
    [
        ("network", "external", False),
        ("network", "name", "new-network"),
        ("network", "driver", "bridge"),
        ("service", "ports", ["9200:9200"]),
        ("service", "ports", ["127.0.0.1:9200:9200", "127.0.0.1:9300:9300"]),
        ("service", "network_mode", "host"),
        ("service", "networks", {"default": {}, "other": {}}),
        ("attachment", "ipv4_address", "${AI_WORKSHOP_ES_ORIGINAL_IPV4:-172.20.0.2}"),
        ("attachment", "ipv4_address", "172.20.0.2"),
        ("root", "include", ["compose.yaml"]),
    ],
)
def test_final_compose_rejects_new_networks_ingress_defaults_and_merge_hooks(location, key, unsafe):
    document = load_asset(FINAL_COMPOSE)
    assert_final_compose_contract(document)
    service = document["services"]["elasticsearch"]
    locations = {
        "root": document,
        "service": service,
        "network": document["networks"]["default"],
        "attachment": service["networks"]["default"],
    }
    locations[location][key] = unsafe
    with pytest.raises(AssertionError):
        assert_final_compose_contract(document)
