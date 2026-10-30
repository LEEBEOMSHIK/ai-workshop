# Public Elasticsearch software packets

`es-9.5.2-public-descriptor-packets.json.gz` contains the exact UTF-8 stdout of the five fixed `javap -c -p -constants` commands in `access_epoch_security_descriptor_source._CLASSES`. The public class definitions come from the existing Elasticsearch 9.5.2 software, not document/index contents, credentials or an operating database.

The bytes were read on 2026-10-22 from the original pinned image after checking the original Docker daemon, container, image and unchanged running lifetime before and after the reads. Every uncompressed packet matched the already reviewed `_PINS`; no content or newline normalization was performed. This is test input for the external process boundary. It is not a capability, historical termination evidence or proof that a test executed against the original environment.

The archive has a fixed schema version and ordered class/SHA/body entries, deterministic gzip timestamp 0, and compressed SHA256 `a5923aa842c8eab385cc858c14fa59b7adac7201ca0f39f668a7f24c8951f168`. Its size is 50,051 bytes. Tests must bound decompression, require exactly five entries in `_CLASSES` order and compare each body against `_PINS` before use. They must not replace the production pins to make a fixture pass.

The original software ownership and license apply to these public class definitions. No model, image, JAR, source document or raw private response is bundled here.
