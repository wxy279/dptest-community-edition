# OpenClaw Integration for dptest Engine Agent

This package describes how an AI agent should operate the `dptest-agent-service-v2` API in this repository.

## When to use this package

Use the engine-agent integration after the host is already prepared and the container is already running.

Typical prerequisites:

- the engine container is running
- the API is reachable on port `18081`
- the caller has `DPTEST_AGENT_TOKEN`
- at least one usable interface object can be created with a valid `pci_addr`

## What this package contains

- `SKILL.md`
  Compact operational rules for the AI agent.
- `workflows/workflows.md`
  Expanded workflow guidance for 0-to-1 setup, scenario presets, and day-2 mutations.

## Current API scope

This package covers:

- template discovery
- live interface discovery
- project CRUD
- interface and subnet modeling
- application-instance modeling
- load-profile modeling
- client and server modeling
- test-case validation, preview, compile, and run
- run stop, summary, and diagnosis
- scenario-preset composition
- metric, recipe, and protocol switching

## What this package does not do

This package does not prepare the host.

For:

- `igb_uio`
- NIC binding
- hugepages
- container start and stop

use:

- `../dptest-host-manager/README.md`

## Recommended reading order for an AI agent

1. read `SKILL.md`
2. read `workflows/workflows.md`
3. verify the live environment with `/health` and `/v2/application-templates`
4. follow the 0-to-1 or scenario-preset workflow that matches the user request

## Related repository documents

- [../../../docs/agent-integration.md](../../../docs/agent-integration.md)
- [../../../examples/README.md](../../../examples/README.md)
- [../README.md](../README.md)

