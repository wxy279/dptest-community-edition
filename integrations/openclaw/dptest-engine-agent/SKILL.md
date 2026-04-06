---
name: dptest-agent-v2-workflow
description: Operate the local dptest-agent-service-v2 API safely and accurately. Use when an AI agent needs to explain or execute the 0-to-1 test-case flow, inspect templates or live interfaces, create project resources, use scenario presets, preview or launch runs, switch metrics or request methods, or switch application instances between HTTPS and HTTP3.
version: 1.0.0
---

# dptest Agent V2 Workflow

Use this skill for the API service in the current repository.

Read `workflows/workflows.md` when the task needs:

- the recommended 0-to-1 object creation order
- the difference between raw CRUD flow and `scenario preset` flow
- dual-end guidance and scale-out patterns
- day-2 metric, request-method, or protocol switching
- current compile, preview, run, and stop semantics
- current repository constraints and guardrails

## Assumptions

Assume:

- the engine container is already running
- the API is reachable
- the caller has `DPTEST_AGENT_TOKEN`
- host preparation has already been completed outside this skill

## Core rules

1. Use `GET /v2/system/interfaces/live` before creating interface objects when the user needs current PCI, interface, or speed information.
2. Treat application instances as template-driven resources. The user-facing `params.target_hosts` value is a single host, not a list to be scaled by count.
3. Prefer preview endpoints before launch actions.
4. Explain that `compile` can deploy config, while `runs` performs compile, deploy, and engine-process launch.
5. Prefer mutating the existing application instance with `recipe-*`, `metric-*`, or `protocol-switch-*` when the user wants day-2 changes.
6. Prefer `scenario preset` when the user wants a reusable dual-end topology or wants to scale beyond one pair cleanly.
7. Treat standalone thread-policy and engine-launch-profile resources as legacy or advanced paths; the runtime can derive effective values automatically.

## Important current constraints

1. A client requires `interface_ref`, `subnet_ref`, `application_instance_ref`, and `load_profile_ref`.
2. A server requires `interface_ref`, `subnet_ref`, and `application_instance_ref`.
3. `launch-preview` and `runs` need `pci_addr` on each used interface.
4. Within one test case, the same `subnet_ref` cannot be reused across multiple client or server entries.
5. Worker-core selection is derived from NUMA0 CPU inventory and the number of client instances.
6. Engine launch settings are derived from total system memory and service defaults unless explicitly overridden.
7. HTTPS to HTTP3 switching for dual-end mode currently has a built-in mapping between `dual_end_https_midbox_sm2_gcm_rps` and `dual_end_http3_midbox_rps`.
8. Single-client HTTPS to HTTP3 switching is supported, but callers should pass `target_template_id`.

## Response guidance

When the user asks for a script or a sequence:

1. provide the 0-to-1 flow first
2. then provide the day-2 mutation flow if needed
3. call out the current repository limits instead of inventing unsupported behavior

