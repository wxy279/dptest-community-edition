# Architecture

This document describes the current repository architecture as implemented today.

## High-level model

The project is split into three layers:

1. host preparation
2. containerized orchestration and engine runtime
3. AI-agent integration

## Component boundaries

### `dptest-host-manager`

Responsibilities:

- build and install `igb_uio`
- assess NIC binding risk
- bind or restore NICs
- assess and configure hugepages
- start, stop, or remove the engine container
- report current host state

This component changes the live Linux host and should be treated as the boundary for privileged operations.

### `dptest-engine-agent`

Responsibilities:

- build the runtime image
- provide the `dptest-agent-service-v2` API
- hold the engine binary, templates, config assets, and runtime support files
- compile object-model resources into engine configuration
- optionally deploy config and launch the engine process
- expose run, monitor, summary, and diagnosis endpoints

This component is the control plane and runtime plane packaged together inside one container.

### `integrations/openclaw`

Responsibilities:

- describe safe agent behavior for host preparation
- describe the API-driven workflow for engine-agent operations
- make the repository usable by an external AI agent without reverse-engineering the codebase

This component is documentation and control guidance, not runtime code.

## Control flow

The normal control flow is:

1. an operator or AI agent prepares the Linux host with `dptest-host-manager`
2. the engine container is started
3. a client calls the `dptest-agent-service-v2` API
4. the service persists project objects
5. the service validates and compiles a selected test case
6. the service optionally deploys the generated config file
7. the service optionally launches the engine binary inside the same container
8. the service exposes run state, summary, diagnosis, and stop operations

## Data model

The current API models center on these resource types:

- project
- interface
- subnet
- application instance
- load profile
- client
- server
- test case
- scenario preset

The service supports both:

- low-level CRUD composition
- higher-level `scenario preset` composition

## Template-driven application model

Applications are template-driven.

The current implementation uses `manifest.json` to define:

- template IDs
- required and optional params
- defaults
- request method
- protocol family
- engine mode
- template placeholders
- focus metrics

This gives the service a stable layer for:

- config rendering
- validation
- mutation workflows
- protocol switching

## Runtime derivation model

Two parts of the runtime are derived automatically by the current code:

### Effective thread policy

Derived from:

- NUMA0 CPU inventory
- number of client instances

Current behavior:

- management core defaults to `0`
- worker cores are selected from the NUMA0 sequence after removing `0`
- selected worker count equals the number of clients

### Effective engine launch profile

Derived from:

- total system memory
- service defaults

Current behavior:

- usable memory is computed from detected total memory
- `socket_size_gb` is snapped down to one of the supported values
- the launch plan includes binary path, app args, EAL args, and environment overrides

## Deployment and execution

The service separates these steps conceptually:

- validate
- compile-preview
- launch-preview
- compile
- run

In current behavior:

- `compile` can render and optionally deploy config
- `runs` performs compile, deploy, and process launch as one workflow

## Storage locations

Host-side state:

- `/var/lib/igb_uio_manager/state.d/`
- `/var/lib/igb_uio_manager/hugepages.last.state`
- `/var/lib/igb_uio_manager/container.last.env`
- `/var/lib/igb_uio_manager/journal.log`

Container-side state:

- `/opt/dptest-agent-v2/data`
- `/opt/dptest-agent-v2/data/compiled`
- `/opt/dptest-agent-v2/data/runs`
- `/etc/dproxy`
- `/etc/dproxy/backup`

## Security model

Current security boundaries are simple:

- host-manager operations rely on root privileges and local trust
- engine-agent API operations rely on bearer-token authentication
- Docker runtime uses `--privileged` and host networking

Implications:

- host preparation should be treated as high risk
- tokens printed during container startup should be treated as secrets
- operational separation between host and container is functional, but not hard-isolated

## Current design tradeoffs

Strengths:

- single-container packaging for engine and control service
- clear host-prep boundary
- template-driven config rendering
- AI-agent operability through repository-native skills and workflows

Known tradeoffs:

- runtime depends on privileged host preparation
- Linux-only behavior for the critical host workflows
- legal review still needed for several bundled assets

## Related documents

- [quickstart.md](quickstart.md)
- [docker-runtime.md](docker-runtime.md)
- [agent-integration.md](agent-integration.md)
- [../integrations/openclaw/README.md](../integrations/openclaw/README.md)

