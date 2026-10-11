"""Synthetic in-memory keys only; no original TLS material or filesystem operations."""

import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from ipaddress import IPv4Address
from uuid import UUID

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import ExtendedKeyUsageOID

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
EPOCH = UUID("11111111-2222-4333-8444-555555555555")
IP = "172.20.0.8"


def module():
    name = "ai_workshop.infrastructure.local.tls_bundle"
    assert importlib.util.find_spec(name) is not None, "project TLS bundle adapter missing"
    return importlib.import_module(name)


class Protection:
    def __init__(self):
        self.private = {}

    def protect(self, data):
        token = f"synthetic-protected-{len(self.private)}".encode()
        self.private[token] = data
        return token

    def unprotect(self, data):
        return self.private[data]


def case():
    protection = Protection()
    adapter = module().ProjectTlsBundles(protection)
    bundle = adapter.generate(EPOCH, IP, NOW)
    return adapter, protection, bundle


def test_generates_independent_project_scoped_ca_and_leaf_with_exact_san_and_eku():
    adapter, protection, bundle = case()
    public_keys = []
    for purpose, layer in (("http", bundle.http), ("transport", bundle.transport)):
        ca = x509.load_pem_x509_certificate(layer.ca_certificate_pem)
        leaf = x509.load_pem_x509_certificate(layer.leaf_certificate_pem)
        ca.verify_directly_issued_by(ca)
        leaf.verify_directly_issued_by(ca)
        assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value == (
            x509.BasicConstraints(ca=True, path_length=0)
        )
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert set(san) == {
            x509.DNSName("localhost"),
            x509.DNSName("elasticsearch"),
            x509.IPAddress(IPv4Address("127.0.0.1")),
            x509.IPAddress(IPv4Address(IP)),
        }
        eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        assert set(eku) == (
            {ExtendedKeyUsageOID.SERVER_AUTH}
            if purpose == "http"
            else {
                ExtendedKeyUsageOID.SERVER_AUTH,
                ExtendedKeyUsageOID.CLIENT_AUTH,
            }
        )
        assert leaf.not_valid_before_utc == NOW - timedelta(minutes=5)
        assert leaf.not_valid_after_utc == NOW + timedelta(days=90)
        assert ca.not_valid_after_utc == NOW + timedelta(days=365)
        for cert in (ca, leaf):
            public_keys.append(
                cert.public_key().public_bytes(
                    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
                )
            )
        assert layer.ca_key_protected in protection.private
    assert len(set(public_keys)) == 4
    assert adapter.validate(bundle, EPOCH, IP, NOW).epoch_id == EPOCH


def test_manifest_hashes_only_public_certificates_and_materialization_excludes_ca_keys():
    adapter, protection, bundle = case()
    manifest = adapter.validate(bundle, EPOCH, IP, NOW)
    assert (
        manifest.http_ca_der_sha256
        == x509.load_pem_x509_certificate(bundle.http.ca_certificate_pem)
        .fingerprint(hashes.SHA256())
        .hex()
    )
    assert (
        manifest.http_leaf_der_sha256
        == x509.load_pem_x509_certificate(bundle.http.leaf_certificate_pem)
        .fingerprint(hashes.SHA256())
        .hex()
    )
    assert manifest.http_ca_pem_sha256 == sha256(bundle.http.ca_certificate_pem).hexdigest()
    assert (
        manifest.transport_ca_pem_sha256 == sha256(bundle.transport.ca_certificate_pem).hexdigest()
    )
    assert manifest.http_ca_pem_sha256 != manifest.http_ca_der_sha256
    files = adapter.materialize(bundle, EPOCH, IP, NOW)
    assert {item.relative_path for item in files.files} == {
        f"{purpose}/{name}"
        for purpose in ("http", "transport")
        for name in ("node.key", "node.crt", "ca.crt")
    }
    assert all(item.content not in protection.private.values() for item in files.files)
    for value in (bundle, bundle.http, bundle.transport, files, files.files, manifest):
        assert "PRIVATE KEY" not in repr(value) and "synthetic-protected" not in repr(value)


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "0.0.0.0", "224.0.0.1", "169.254.1.1", "::1", "host", "172.020.0.8"]
)
def test_invalid_original_ip_never_generates_or_protects_keys(ip):
    protection = Protection()
    adapter = module().ProjectTlsBundles(protection)
    with pytest.raises(module().ProjectTlsError, match="project_tls_denied"):
        adapter.generate(EPOCH, ip, NOW)
    assert not protection.private


@pytest.mark.parametrize(
    "when", [NOW.replace(tzinfo=None), NOW - timedelta(days=1), NOW + timedelta(days=91)]
)
def test_validation_rejects_naive_time_not_yet_valid_and_expired(when):
    adapter, _, bundle = case()
    with pytest.raises(module().ProjectTlsError, match="project_tls_denied"):
        adapter.validate(bundle, EPOCH, IP, when)


@pytest.mark.parametrize(
    "alteration", ["epoch", "ip", "purpose", "ca", "leaf_key", "ca_key", "trailing", "oversized"]
)
def test_validation_rejects_wrong_binding_and_malformed_private_material(alteration):
    adapter, _, bundle = case()
    if alteration == "epoch":
        bundle = replace(bundle, epoch_id=UUID(int=2))
    elif alteration == "ip":
        bundle = replace(bundle, original_ipv4="172.20.0.9")
    elif alteration == "purpose":
        bundle = replace(bundle, http=bundle.transport)
    elif alteration == "ca":
        bundle = replace(
            bundle,
            http=replace(bundle.http, ca_certificate_pem=bundle.transport.ca_certificate_pem),
        )
    elif alteration == "leaf_key":
        bundle = replace(
            bundle,
            http=replace(bundle.http, leaf_private_key_pem=bundle.transport.leaf_private_key_pem),
        )
    elif alteration == "ca_key":
        bundle = replace(
            bundle, http=replace(bundle.http, ca_key_protected=bundle.transport.ca_key_protected)
        )
    elif alteration == "trailing":
        bundle = replace(
            bundle,
            http=replace(
                bundle.http, leaf_certificate_pem=bundle.http.leaf_certificate_pem + b"unexpected"
            ),
        )
    else:
        bundle = replace(bundle, http=replace(bundle.http, leaf_private_key_pem=b"x" * 65537))
    with pytest.raises(module().ProjectTlsError, match="project_tls_denied"):
        adapter.validate(bundle, EPOCH, IP, NOW)


def test_wrong_expected_hostname_ip_rejects_materialization_before_returning_files():
    adapter, _, bundle = case()
    with pytest.raises(module().ProjectTlsError, match="project_tls_denied"):
        adapter.materialize(bundle, EPOCH, "172.20.0.9", NOW)


def test_protection_failure_is_sanitized_and_no_plain_ca_bundle_returned():
    class Failing(Protection):
        def protect(self, data):
            raise RuntimeError("synthetic-private-detail")

    adapter = module().ProjectTlsBundles(Failing())
    with pytest.raises(module().ProjectTlsError) as error:
        adapter.generate(EPOCH, IP, NOW)
    assert str(error.value) == "project_tls_denied"
    assert "synthetic-private-detail" not in repr(error.value)


def resign(certificate, signer, *, replacements=None, subject=None, issuer=None, public=None):
    replacements = replacements or {}
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject or certificate.subject)
        .issuer_name(issuer or certificate.issuer)
        .public_key(public or certificate.public_key())
        .serial_number(certificate.serial_number)
        .not_valid_before(certificate.not_valid_before_utc)
        .not_valid_after(certificate.not_valid_after_utc)
    )
    for extension in certificate.extensions:
        value = replacements.get(extension.oid, extension.value)
        builder = builder.add_extension(value, extension.critical)
    return builder.sign(signer, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)


@pytest.mark.parametrize(
    "mutation",
    ["missing_ip", "extra_dns", "http_client_auth", "leaf_ca", "leaf_signer", "ca_not_ca"],
)
def test_valid_signature_does_not_override_exact_san_usage_or_ca_constraints(mutation):
    adapter, protection, bundle = case()
    layer = bundle.http
    signer = serialization.load_pem_private_key(protection.private[layer.ca_key_protected], None)
    leaf = x509.load_pem_x509_certificate(layer.leaf_certificate_pem)
    ca = x509.load_pem_x509_certificate(layer.ca_certificate_pem)
    if mutation == "ca_not_ca":
        changed = resign(
            ca,
            signer,
            replacements={
                x509.ExtensionOID.BASIC_CONSTRAINTS: x509.BasicConstraints(False, None),
            },
        )
        layer = replace(layer, ca_certificate_pem=changed)
    else:
        san = list(leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)
        if mutation == "missing_ip":
            altered = x509.SubjectAlternativeName(san[:-1])
        elif mutation == "extra_dns":
            altered = x509.SubjectAlternativeName([*san, x509.DNSName("unapproved.example")])
        elif mutation == "http_client_auth":
            altered = x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
            )
        elif mutation == "leaf_ca":
            altered = x509.BasicConstraints(True, 0)
        else:
            altered = x509.KeyUsage(True, False, False, False, False, True, True, False, False)
        layer = replace(
            layer, leaf_certificate_pem=resign(leaf, signer, replacements={altered.oid: altered})
        )
    with pytest.raises(module().ProjectTlsError, match="project_tls_denied"):
        adapter.validate(replace(bundle, http=layer), EPOCH, IP, NOW)


def test_correct_purpose_certificates_cannot_share_ca_signing_key():
    adapter, protection, bundle = case()
    shared = serialization.load_pem_private_key(
        protection.private[bundle.http.ca_key_protected], None
    )
    layer = bundle.transport
    ca = x509.load_pem_x509_certificate(layer.ca_certificate_pem)
    leaf = x509.load_pem_x509_certificate(layer.leaf_certificate_pem)
    aki = x509.AuthorityKeyIdentifier.from_issuer_public_key(shared.public_key())
    ski = x509.SubjectKeyIdentifier.from_public_key(shared.public_key())
    ca_pem = resign(
        ca, shared, public=shared.public_key(), replacements={aki.oid: aki, ski.oid: ski}
    )
    leaf_pem = resign(leaf, shared, replacements={aki.oid: aki})
    changed = replace(
        layer,
        ca_certificate_pem=ca_pem,
        leaf_certificate_pem=leaf_pem,
        ca_key_protected=bundle.http.ca_key_protected,
    )
    with pytest.raises(module().ProjectTlsError, match="project_tls_denied"):
        adapter.validate(replace(bundle, transport=changed), EPOCH, IP, NOW)


def test_noop_protection_cannot_return_plaintext_ca_signing_key():
    class NoProtection:
        def protect(self, data):
            return data

        def unprotect(self, data):
            return data

    with pytest.raises(module().ProjectTlsError, match="project_tls_denied"):
        module().ProjectTlsBundles(NoProtection()).generate(EPOCH, IP, NOW)
