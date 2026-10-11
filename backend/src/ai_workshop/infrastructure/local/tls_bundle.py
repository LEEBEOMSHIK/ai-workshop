"""Project-only TLS bytes; no filesystem, trust-store, Docker or Labs operations."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from ipaddress import IPv4Address
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from ai_workshop.infrastructure.local.credential_store_windows import ProtectionPort


class ProjectTlsError(ValueError):
    """Fixed sanitized failure; never carries key, certificate or crypto details."""


@dataclass(frozen=True, slots=True, eq=False)
class TlsLayer:
    ca_certificate_pem: bytes = field(repr=False)
    leaf_certificate_pem: bytes = field(repr=False)
    leaf_private_key_pem: bytes = field(repr=False)
    ca_key_protected: bytes = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class ProjectTlsBundle:
    epoch_id: UUID
    original_ipv4: str
    http: TlsLayer = field(repr=False)
    transport: TlsLayer = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class TlsFile:
    relative_path: str
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class TlsMaterialization:
    files: tuple[TlsFile, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class TlsPublicManifest:
    epoch_id: UUID
    original_ipv4: str
    http_ca_der_sha256: str
    http_leaf_der_sha256: str
    transport_ca_der_sha256: str
    transport_leaf_der_sha256: str
    not_valid_after: datetime
    http_ca_pem_sha256: str
    transport_ca_pem_sha256: str


def _inputs(epoch_id: UUID, original_ipv4: str, now: datetime) -> tuple[IPv4Address, datetime]:
    if type(epoch_id) is not UUID or epoch_id.int == 0 or type(original_ipv4) is not str:
        raise ValueError
    address = IPv4Address(original_ipv4)
    if (
        str(address) != original_ipv4
        or address.is_loopback
        or address.is_multicast
        or address.is_link_local
        or address.is_unspecified
        or address.is_reserved
        or type(now) is not datetime
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise ValueError
    return address, now.astimezone(UTC).replace(microsecond=0)


def _name(epoch_id: UUID, purpose: str, ca: bool) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(
                NameOID.COMMON_NAME, f"ai-workshop {epoch_id} {purpose} {'CA' if ca else 'node'}"
            )
        ]
    )


def _public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _private(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _bounded(data: bytes) -> bytes:
    if type(data) is not bytes or not 0 < len(data) <= 16384:
        raise ValueError
    return data


def _load_key(data: bytes) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(_bounded(data), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError
    if _private(key) != data:
        raise ValueError
    return key


def _load_cert(data: bytes) -> x509.Certificate:
    certificate = x509.load_pem_x509_certificate(_bounded(data))
    if certificate.public_bytes(serialization.Encoding.PEM) != data:
        raise ValueError
    return certificate


def _extensions(
    public: ec.EllipticCurvePublicKey,
    issuer: ec.EllipticCurvePublicKey,
    purpose: str,
    address: IPv4Address,
    *,
    ca: bool,
) -> list[tuple[x509.ExtensionType, bool]]:
    result: list[tuple[x509.ExtensionType, bool]] = [
        (x509.BasicConstraints(ca=ca, path_length=0 if ca else None), True),
        (
            x509.KeyUsage(
                digital_signature=not ca,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=ca,
                crl_sign=ca,
                encipher_only=False,
                decipher_only=False,
            ),
            True,
        ),
        (x509.SubjectKeyIdentifier.from_public_key(public), False),
        (x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer), False),
    ]
    if not ca:
        eku = [ExtendedKeyUsageOID.SERVER_AUTH]
        if purpose == "transport":
            eku.append(ExtendedKeyUsageOID.CLIENT_AUTH)
        result.extend(
            [
                (x509.ExtendedKeyUsage(eku), False),
                (
                    x509.SubjectAlternativeName(
                        [
                            x509.DNSName("localhost"),
                            x509.DNSName("elasticsearch"),
                            x509.IPAddress(IPv4Address("127.0.0.1")),
                            x509.IPAddress(address),
                        ]
                    ),
                    False,
                ),
            ]
        )
    return result


def _certificate(
    epoch_id: UUID,
    purpose: str,
    address: IPv4Address,
    now: datetime,
    key: ec.EllipticCurvePrivateKey,
    signer: ec.EllipticCurvePrivateKey,
    *,
    ca: bool,
) -> x509.Certificate:
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(epoch_id, purpose, ca))
        .issuer_name(_name(epoch_id, purpose, True))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365 if ca else 90))
    )
    for value, critical in _extensions(
        key.public_key(), signer.public_key(), purpose, address, ca=ca
    ):
        builder = builder.add_extension(value, critical=critical)
    return builder.sign(signer, hashes.SHA256())


class ProjectTlsBundles:
    def __init__(self, protection: ProtectionPort) -> None:
        self._protection = protection

    def generate(self, epoch_id: UUID, original_ipv4: str, now: datetime) -> ProjectTlsBundle:
        try:
            address, timestamp = _inputs(epoch_id, original_ipv4, now)
            layers = []
            for purpose in ("http", "transport"):
                signer, key = (
                    ec.generate_private_key(ec.SECP256R1()),
                    ec.generate_private_key(ec.SECP256R1()),
                )
                ca = _certificate(epoch_id, purpose, address, timestamp, signer, signer, ca=True)
                leaf = _certificate(epoch_id, purpose, address, timestamp, key, signer, ca=False)
                signer_pem = _private(signer)
                protected = _bounded(self._protection.protect(signer_pem))
                if protected == signer_pem:
                    raise ValueError
                layers.append(
                    TlsLayer(
                        ca.public_bytes(serialization.Encoding.PEM),
                        leaf.public_bytes(serialization.Encoding.PEM),
                        _private(key),
                        protected,
                    )
                )
            bundle = ProjectTlsBundle(epoch_id, original_ipv4, layers[0], layers[1])
            self.validate(bundle, epoch_id, original_ipv4, timestamp)
            return bundle
        except Exception:
            raise ProjectTlsError("project_tls_denied") from None

    def validate(
        self,
        bundle: ProjectTlsBundle,
        epoch_id: UUID,
        original_ipv4: str,
        now: datetime,
    ) -> TlsPublicManifest:
        try:
            address, timestamp = _inputs(epoch_id, original_ipv4, now)
            if (
                type(bundle) is not ProjectTlsBundle
                or bundle.epoch_id != epoch_id
                or bundle.original_ipv4 != original_ipv4
            ):
                raise ValueError
            fingerprints, public_keys, expirations = [], [], []
            for purpose, layer in (("http", bundle.http), ("transport", bundle.transport)):
                if type(layer) is not TlsLayer:
                    raise ValueError
                ca = _load_cert(layer.ca_certificate_pem)
                leaf = _load_cert(layer.leaf_certificate_pem)
                signer = _load_key(self._protection.unprotect(_bounded(layer.ca_key_protected)))
                if layer.ca_key_protected == _private(signer):
                    raise ValueError
                key = _load_key(layer.leaf_private_key_pem)
                ca.verify_directly_issued_by(ca)
                leaf.verify_directly_issued_by(ca)
                if ca.not_valid_before_utc != leaf.not_valid_before_utc:
                    raise ValueError
                for certificate, private_key, is_ca in ((ca, signer, True), (leaf, key, False)):
                    public = certificate.public_key()
                    if (
                        not isinstance(public, ec.EllipticCurvePublicKey)
                        or not isinstance(public.curve, ec.SECP256R1)
                        or not isinstance(certificate.signature_hash_algorithm, hashes.SHA256)
                        or certificate.subject != _name(epoch_id, purpose, is_ca)
                        or certificate.issuer != _name(epoch_id, purpose, True)
                        or not certificate.not_valid_before_utc
                        <= timestamp
                        < certificate.not_valid_after_utc
                        or certificate.not_valid_after_utc - certificate.not_valid_before_utc
                        != timedelta(days=365 if is_ca else 90, minutes=5)
                        or _public(public) != _public(private_key.public_key())
                    ):
                        raise ValueError
                    expected = _extensions(public, signer.public_key(), purpose, address, ca=is_ca)
                    actual = [(item.value, item.critical) for item in certificate.extensions]
                    if actual != expected:
                        raise ValueError
                    public_keys.append(_public(public))
                    fingerprints.append(certificate.fingerprint(hashes.SHA256()).hex())
                    expirations.append(certificate.not_valid_after_utc)
            if len(set(public_keys)) != 4:
                raise ValueError
            return TlsPublicManifest(
                epoch_id,
                original_ipv4,
                fingerprints[0],
                fingerprints[1],
                fingerprints[2],
                fingerprints[3],
                min(expirations),
                sha256(bundle.http.ca_certificate_pem).hexdigest(),
                sha256(bundle.transport.ca_certificate_pem).hexdigest(),
            )
        except Exception:
            raise ProjectTlsError("project_tls_denied") from None

    def materialize(
        self,
        bundle: ProjectTlsBundle,
        epoch_id: UUID,
        original_ipv4: str,
        now: datetime,
    ) -> TlsMaterialization:
        """Return six exact byte entries only; this method never writes a file."""
        self.validate(bundle, epoch_id, original_ipv4, now)
        files = []
        for purpose, layer in (("http", bundle.http), ("transport", bundle.transport)):
            files.extend(
                [
                    TlsFile(f"{purpose}/node.key", layer.leaf_private_key_pem),
                    TlsFile(f"{purpose}/node.crt", layer.leaf_certificate_pem),
                    TlsFile(f"{purpose}/ca.crt", layer.ca_certificate_pem),
                ]
            )
        return TlsMaterialization(tuple(files))
