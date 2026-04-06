# Agent Integration

This document explains how a user or AI agent should operate the `dptest-agent-service-v2` API in the current repository.

## Authentication

Most `/v2/*` endpoints require:

```text
Authorization: Bearer <DPTEST_AGENT_TOKEN>
```

The token is typically printed by:

```bash
sudo ./dptest_engine_host_manager.sh start-engine-container
```

## Base URL

Typical local base URL:

```text
http://127.0.0.1:18081
```

## API groups

The current API surface includes:

- health
- application templates
- live system interfaces
- projects
- interfaces
- subnets
- application instances
- load profiles
- clients
- servers
- test cases
- runs
- scenario presets
- summary and diagnosis

## Recommended 0-to-1 flow

The normal object-by-object workflow is:

1. create a project
2. inspect `GET /v2/system/interfaces/live`
3. create one or more interfaces
4. create one or more subnets
5. create one or more application instances
6. create one or more load profiles
7. create one or more clients
8. create one or more servers if needed
9. create a test case
10. bind the client and server references to the test case
11. run `validate`
12. run `compile-preview`
13. run `launch-preview`
14. run `compile` or `runs`

## Why `GET /v2/system/interfaces/live` comes first

The current code exposes live Linux interface inventory so the caller can discover:

- interface name
- PCI address
- speed and link details
- DPDK-relevant metadata

That lets the caller populate `interfaces` correctly, especially `pci_addr`.

## Application model

An application instance is template-driven.

The current repository expects:

- `template_id`
- `name`
- `params`
- optional `metric_profile`
- optional `recipe`

Important convention:

- `params.target_hosts` is a single target host value
- the service internally treats target-host count as fixed to `1`

## Test-case model

The current behavior distinguishes:

- `client_only`
- `server_only`
- `dual_end`

Important current constraints:

- a client needs `interface_ref`, `subnet_ref`, `application_instance_ref`, and `load_profile_ref`
- a server needs `interface_ref`, `subnet_ref`, and `application_instance_ref`
- `launch-preview` and `runs` need `pci_addr` on each used interface
- within one test case, the same `subnet_ref` cannot be reused across multiple client or server entries

## Scenario preset workflow

When the user wants a reusable topology rather than hand-built CRUD wiring, the current repository supports:

- `POST /v2/projects/{project_id}/scenario-presets`
- `compose-preview`
- `compose-apply`
- `compose-run`

Recommended pattern:

1. create the base project resources
2. create one scenario preset
3. inspect `compose-preview`
4. apply with `compose-apply`
5. run the generated test case or use `compose-run`

## Day-2 mutation workflows

The current service supports mutation on the existing application instance.

### Metric and request-method mutation

Endpoints:

- `recipe-preview`
- `recipe-apply`
- `metric-preview`
- `metric-switch`

Use these when the user wants to:

- switch between `TPS`, `RPS`, and `TPUT`
- switch between `GET` and `POST`
- update request, redirect, connection, response, or latency behavior without rebuilding the full test case

### Protocol mutation

Endpoints:

- `protocol-switch-preview`
- `protocol-switch-apply`

Use these when the user wants to switch an application instance between:

- `HTTPS`
- `HTTP3`

Important current behavior:

- dual-end templates have a built-in mapping between `dual_end_https_midbox_sm2_gcm_rps` and `dual_end_http3_midbox_rps`
- single-client switching is supported, but callers should provide `target_template_id`

## Compile and run semantics

Current semantics:

- `compile-preview` validates and renders without deployment
- `compile` can deploy config
- `runs` performs compile, deploy, and engine-process launch

Useful run endpoints:

- `POST /v2/projects/{project_id}/test-cases/{test_case_id}/runs`
- `GET /v2/runs`
- `GET /v2/runs/{run_id}`
- `POST /v2/runs/{run_id}/stop`
- `GET /v2/runs/{run_id}/summary`
- `GET /v2/runs/{run_id}/diagnosis`

## Example: query templates

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  "${BASE_URL}/v2/application-templates"
```

## Example: create a project

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects" \
  -d '{
    "project_id": "proj_demo",
    "name": "demo project",
    "description": "first API-driven project"
  }'
```

## Example: inspect live interfaces

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  "${BASE_URL}/v2/system/interfaces/live"
```

## Example: validate before launch

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -X POST \
  "${BASE_URL}/v2/projects/${PROJECT_ID}/test-cases/${TEST_CASE_ID}/validate"
```

## Recommended operating style for AI agents

An AI agent should:

1. inspect live interfaces before proposing interface objects
2. prefer `scenario preset` for reusable or scaled dual-end topologies
3. use preview endpoints before destructive or launch actions
4. prefer mutation endpoints over rebuilding objects when the user wants day-2 changes
5. explain current repository constraints instead of inventing unsupported paths

## Related documents

- [quickstart.md](quickstart.md)
- [architecture.md](architecture.md)
- [../examples/README.md](../examples/README.md)
- [../integrations/openclaw/dptest-engine-agent/README.md](../integrations/openclaw/dptest-engine-agent/README.md)

