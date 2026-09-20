# Codex CLI 0.155.1 command contract

The command builder now accepts exactly `0.153.4` and `0.155.1`. It records the
selected runner version in the plan. This is syntax compatibility, not proof of
effective isolation, observed model identity, or permission to launch a model.
The coordinator's executable hash/version checks, approval binding, event
validation, and readiness verification remain required.

On 2026-09-20 the configured native Windows executable reported
`codex-cli 0.155.1`. Its installed npm package metadata reported
`@openai/codex` / `0.155.1-win32-x64`; the bundled README links to the official
CLI documentation. Native `--help` and `exec --help` both exited successfully.
They retain `--strict-config`, `--ignore-user-config`, `--ephemeral`, `--json`,
`--sandbox read-only`, `--model`, `--cd`, `--output-schema`, and stdin `-`.

The [official non-interactive documentation](https://developers.openai.com/codex/noninteractive/)
describes JSONL thread/turn/item events, token usage, JSON Schema output, and
user-config isolation. The [configuration reference](https://developers.openai.com/codex/config-reference/)
documents shell, multi-agent, app and hook feature settings. The builder keeps
the exact existing argv, including disabled tools/web search, zero project
document bytes, explicit model selection, and strict configuration handling.
No event parser acceptance was widened; unexpected events still fail closed.

Regression coverage compares the full argv for both supported versions and
rejects neighboring versions and prerelease suffixes. The 0.155.1 case failed
with `codex_command_contract_unsupported` before the allowlist change.
This check made no model calls, database writes, installation changes, or
environment-file edits. Effective runtime verification is a separate step.
