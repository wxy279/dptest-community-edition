# dptest Agent V2 Workflows

This document expands the AI-agent workflow rules for `dptest-agent-service-v2`.

## 0-to-1 object flow

Use this order for the normal hand-built workflow:

1. create the project
2. inspect `GET /v2/system/interfaces/live`
3. create one or more interfaces
4. create one or more subnets
5. create one or more application instances
6. create one or more load profiles
7. create one or more clients
8. create one or more servers if needed
9. create the test case
10. bind the client and server references to the test case
11. call `validate`
12. call `compile-preview`
13. call `launch-preview`
14. call `compile` or `runs`

## Why this order matters

- interface objects should reflect current PCI and link reality
- test cases cannot preview launches without valid interface `pci_addr`
- launch derivation depends on the final set of client instances and used interfaces

## Raw CRUD versus scenario preset

Use raw CRUD when:

- the user wants full control over each object
- the topology is small
- the task is exploratory

Use `scenario preset` when:

- the user wants a reusable topology
- the user wants a cleaner dual-end composition flow
- the user wants to scale from one pair to multiple pairs

## Scenario preset flow

Recommended order:

1. create the base project resources
2. create one scenario preset
3. inspect `compose-preview`
4. materialize with `compose-apply`
5. validate, preview, compile, or run the generated test case

The scenario-preset layer should be described as:

- topology composition
- not a replacement for application templates
- not a replacement for host preparation

## Dual-end guidance

For current dual-end behavior:

- a client and a server can share the same `application_instance_ref`
- a client and a server usually use different `interface_ref`
- a client and a server usually use different `subnet_ref`
- only clients carry `load_profile_ref`

Typical one-pair layout:

- `client1 -> interface_client_1 + subnet_client_1 + app1 + load1`
- `server1 -> interface_server_1 + subnet_server_1 + app1`
- `testcase1 -> [client1] + [server1]`

## Day-2 mutation flow

When the base topology already exists, prefer mutating the current application instance instead of rebuilding the test case.

### Metric and request-method changes

Use:

- `recipe-preview`
- `recipe-apply`
- `metric-preview`
- `metric-switch`

Use these for:

- `TPS`, `RPS`, and `TPUT` changes
- `GET` to `POST` changes
- response-body and request-body changes
- redirect or cookie behavior changes
- latency or connection-behavior changes

### Protocol changes

Use:

- `protocol-switch-preview`
- `protocol-switch-apply`

Use these to switch an existing application instance between:

- `HTTPS`
- `HTTP3`

Current built-in dual-end mapping:

- `dual_end_https_midbox_sm2_gcm_rps` <-> `dual_end_http3_midbox_rps`

## Application-instance conventions

When describing current payload expectations:

- `params.target_hosts` is a single host value
- template-specific controls remain in `params`
- metric or recipe changes belong to the application instance

Common parameter areas include:

- target host and ports
- HTTP path and request method
- POST body controls
- TLS controls
- response-body controls
- latency controls
- persistent-session and redirect controls

## Compile and run semantics

Describe current behavior like this:

- `validate` checks resource consistency and derived runtime requirements
- `compile-preview` shows what would be rendered
- `launch-preview` shows the engine launch plan
- `compile` can render and deploy configuration
- `runs` performs compile, deploy, and process launch

Useful run endpoints:

- `GET /v2/runs`
- `GET /v2/runs/{run_id}`
- `POST /v2/runs/{run_id}/stop`
- `GET /v2/runs/{run_id}/summary`
- `GET /v2/runs/{run_id}/diagnosis`

## Derived runtime behavior

### Effective thread policy

Current behavior:

- management core defaults to `0`
- NUMA0 CPU inventory is discovered from Linux or environment override
- worker cores are selected after removing core `0`
- worker count equals the number of client instances

### Effective engine launch profile

Current behavior:

- total memory is detected from Linux or environment override
- socket size is derived from available memory and snapped to supported sizes
- launch plan includes the binary path, app args, EAL args, and env overrides

## Constraints to call out

1. A client requires `interface_ref`, `subnet_ref`, `application_instance_ref`, and `load_profile_ref`.
2. A server requires `interface_ref`, `subnet_ref`, and `application_instance_ref`.
3. `launch-preview` and `runs` require `pci_addr` on every used interface.
4. One test case cannot reuse the same `subnet_ref` across multiple bound client or server entries.
5. Automatic interface discovery and automatic CPU/memory derivation are Linux-oriented features.
6. Protocol switching preserves only the parameters compatible with the target template.

## Recommended AI-agent operating style

An AI agent should:

1. verify the live environment first
2. explain why each object is needed
3. prefer preview endpoints over immediate launch
4. reuse the existing application instance for day-2 changes
5. use scenario presets for reusable dual-end topologies

