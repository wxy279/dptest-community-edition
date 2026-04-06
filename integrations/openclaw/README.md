# OpenClaw Integrations

This directory contains repository-local skills and workflow notes for AI agents that operate `dptest-community-edition`.

The goal is to let an AI agent interact with the repository using explicit, reviewable instructions rather than hidden assumptions.

## Integration split

Two main integration packages are provided:

### `dptest-host-manager`

Use this when the agent needs to operate on the Linux host:

- install `igb_uio`
- assess NIC binding risk
- bind or restore NICs
- assess or set hugepages
- start, stop, or remove the engine container
- inspect host runtime state

This is the high-risk, privileged side of the system.

### `dptest-engine-agent`

Use this when the agent needs to operate the API inside the container:

- inspect templates
- discover interfaces
- create object-model resources
- compile or preview test cases
- run or stop engine processes
- mutate metric, request-method, and protocol behavior
- use scenario presets

This is the API-driven orchestration side of the system.

## Recommended handoff order

A complete end-to-end session usually follows this order:

1. use `dptest-host-manager` to prepare the host
2. start the engine container and capture `DPTEST_AGENT_TOKEN`
3. switch to `dptest-engine-agent` for API-based modeling and runtime control

## Why these documents matter

Without the integration documents, an external AI agent would need to infer:

- which host operations are dangerous
- which API order is valid
- which template conventions are currently supported
- which repository constraints are intentional rather than accidental

These documents make those rules explicit.

## Documents in this directory

- `dptest-host-manager/README.md`
- `dptest-host-manager/SKILL.md`
- `dptest-host-manager/workflows/workflows.md`
- `dptest-engine-agent/README.md`
- `dptest-engine-agent/SKILL.md`
- `dptest-engine-agent/workflows/workflows.md`

## Related repository documents

- [../../README.md](../../README.md)
- [../../docs/architecture.md](../../docs/architecture.md)
- [../../docs/agent-integration.md](../../docs/agent-integration.md)
- [../../docs/host-prepare.md](../../docs/host-prepare.md)

