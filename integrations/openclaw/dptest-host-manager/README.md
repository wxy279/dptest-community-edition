# OpenClaw Integration for dptest Host Manager

This package describes how an AI agent should operate the host-side preparation workflow in this repository.

## When to use this package

Use the host-manager integration when the task requires actions outside the container, including:

- `igb_uio` installation
- NIC risk assessment and binding
- hugepage assessment and configuration
- engine container startup or cleanup
- current host-state inspection

## What this package contains

- `SKILL.md`
  Compact operating rules for the AI agent.
- `workflows/workflows.md`
  Expanded safe workflows for bind, hugepages, container start, and recovery.

## Why this package is separate

Host preparation is the highest-risk part of the system.

It can:

- disconnect the host from the network
- change live memory settings
- alter the kernel driver attached to a NIC

For that reason, these instructions are intentionally separate from the engine-agent API workflow.

## Required local files

The current workflow expects:

- `dptest_engine_host_manager.sh`
- `igb_uio.tar.gz`
- `dpdk-devbind.py`

to be present in the same directory.

## Typical workflow

1. inspect current host state
2. install `igb_uio`
3. assess the target NIC
4. bind only after approval
5. assess hugepages
6. apply hugepages
7. start the engine container
8. capture and return `DPTEST_AGENT_TOKEN` and `TOKEN`

## Hand-off to engine-agent integration

After the container is running and the token has been captured, hand off to:

- `../dptest-engine-agent/README.md`

for the API-driven part of the workflow.

## Related repository documents

- [../../../docs/host-prepare.md](../../../docs/host-prepare.md)
- [../../../examples/host-manager-commands.md](../../../examples/host-manager-commands.md)
- [../README.md](../README.md)

