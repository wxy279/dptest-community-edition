# dptest Community Edition

`dptest-community-edition` is a host-prepared, containerized performance test engine package for DPDK-style traffic generation and service orchestration.

It saves users time and improves performance-testing efficiency by providing an AI agent service that helps model, compile, deploy, and run tests faster.

## Edition positioning

The current Community Edition is designed for development validation, protocol exploration, and small-scale testing. It supports AI-assisted testing, HTTP/3, Chinese commercial cryptography, PQC, and dual-end simulation, making it a strong fit for local integration, solution demos, issue reproduction, and capability verification.

The Pro Edition is intended for formal project testing and production-grade performance evaluation. It provides larger test scale, longer test duration, more complete automation capabilities, and richer result analysis.

The Enterprise Edition is intended for team-based, platform-based, and continuous regression programs. It adds distributed load testing, centralized scheduling, team collaboration, permission management, centralized reporting, and AI-driven automation workflows.

For Pro or Enterprise editions, contact `dpdkproxysupport@163.com`.

## Core capabilities

This edition provides a high-performance HTTP(S) load testing engine with support for:

- HTTP/1.1 and HTTP/3
- TLS 1.2 and TLS 1.3
- TLCP with SM2, SM3, and SM4
- post-quantum cryptography algorithms
- both client-side and server-side simulation
- mixed traffic patterns such as `HTTP3-DUT-HTTP3`, `HTTPS/1.1-DUT-HTTP/1.1`, and `HTTP3-DUT-HTTP/1.1`
- diverse HTTP semantics for advanced testing scenarios

Both client and server support cookies and automatic redirect following. The engine supports multiple POST upload methods, and the server side can simulate a real static resource server by serving directories and files.

The runtime also supports advanced connection and crypto customization, including:

- TCP connection termination behavior
- cipher suites
- curves
- signature algorithms
- SNI
- sending `close_notify`

This repository is organized around three cooperating parts:

1. `dptest-engine-agent`
   Builds the runtime image that contains both the `dptest-agent-service-v2` API service and the `dpdkproxy` engine binary.
2. `dptest-host-manager`
   Prepares the Linux host for DPDK-style runtime by installing `igb_uio`, assessing and binding NICs, configuring hugepages, and starting or stopping the container.
3. `integrations/openclaw`
   Provides AI-agent-facing skills and workflows so an external agent can operate the host manager and the engine agent safely.

## Repository status

This repository is being prepared for public release.

- The documentation in this commit is a release draft intended to make the repository understandable and navigable on GitHub.
- The code paths and runtime behavior described here were derived from the current repository contents.
- Final legal review is still required for the outbound license and third-party redistribution notice.

Important licensing note:

- the repository's original code and documentation are published under Apache-2.0 unless otherwise noted
- the bundled `dptest-engine-agent/app/dpdkproxy` binary is a proprietary commercial component and is not granted open-source copying, redistribution, or derivative-work rights by this repository

See:

- [LICENSE](LICENSE)
- [NOTICE.md](NOTICE.md)
- [CHANGELOG.md](CHANGELOG.md)

## What this project does

At a high level, the system does the following:

1. Prepares a Linux host for DPDK-oriented NIC access.
2. Runs a container that exposes an HTTP API on port `18081`.
3. Lets users or AI agents create projects, interfaces, subnets, applications, load profiles, clients, servers, test cases, and scenario presets through the API.
4. Compiles those objects into engine configuration.
5. Optionally deploys the generated config and launches the engine binary inside the same container.
6. Exposes monitor, summary, diagnosis, and run-management endpoints for day-2 operations.

## Current feature set

Based on the current repository state, the community edition includes:

- host preparation for `igb_uio`, NIC binding, hugepage management, and engine container lifecycle
- a FastAPI-based control service with bearer-token authentication
- object-model APIs for projects, interfaces, subnets, application instances, load profiles, clients, servers, test cases, and scenario presets
- template-driven application definitions from `dptest-engine-agent/dptest-agent-v2/templates/manifest.json`
- compile-preview, launch-preview, compile, run, stop, summary, and diagnosis workflows
- application mutation workflows for metric switching, request-method switching, and HTTPS/HTTP3 protocol switching

The current built-in application templates are:

- `https_server_get_rps`
- `http3_server_get_rps`
- `http3_server_post_rps`
- `dual_end_https_midbox_sm2_gcm_rps`
- `dual_end_http3_midbox_rps`

## Quick start path

The shortest path to a successful first run is:

1. Read [docs/host-prepare.md](docs/host-prepare.md).
2. Pull the published image described in [dptest-engine-agent/README.md](dptest-engine-agent/README.md).
3. Use [dptest-host-manager/README.md](dptest-host-manager/README.md) to prepare the host and start the container.
4. Verify `GET /health` on `http://<host>:18081/health`.
5. Follow [docs/agent-integration.md](docs/agent-integration.md) or the examples in [examples/README.md](examples/README.md) to create a project and run a test case.

## Repository layout

```text
.
├── docs/
├── examples/
├── integrations/
│   └── openclaw/
├── dptest-engine-agent/
├── dptest-host-manager/
├── README.md
├── CHANGELOG.md
├── LICENSE
└── NOTICE.md
```

## Documentation map

Core documents:

- [docs/quickstart.md](docs/quickstart.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/host-prepare.md](docs/host-prepare.md)
- [docs/docker-runtime.md](docs/docker-runtime.md)
- [docs/agent-integration.md](docs/agent-integration.md)
- [docs/faq.md](docs/faq.md)

Component documents:

- [dptest-engine-agent/README.md](dptest-engine-agent/README.md)
- [dptest-host-manager/README.md](dptest-host-manager/README.md)

AI integration documents:

- [integrations/openclaw/README.md](integrations/openclaw/README.md)
- [integrations/openclaw/dptest-engine-agent/README.md](integrations/openclaw/dptest-engine-agent/README.md)
- [integrations/openclaw/dptest-host-manager/README.md](integrations/openclaw/dptest-host-manager/README.md)

Examples:

- [examples/README.md](examples/README.md)

## Runtime assumptions

The current implementation assumes:

- a Linux host for live NIC discovery, NIC binding, and hugepage management
- root privileges for host preparation steps
- Docker available on the host
- at least one NIC bound to `igb_uio` before starting the engine container
- hugepages configured before container startup
- bearer-token authentication for most `/v2/*` APIs

## Current operational limits

The current repository behavior includes these notable limits:

- host preparation and live interface discovery are Linux-only
- the host-manager container startup flow requires at least one and at most two NICs bound to `igb_uio`
- `launch-preview` and `runs` require `pci_addr` on all used interfaces
- the service derives effective thread policy from NUMA0 CPU inventory and the number of client instances
- the service derives effective engine launch profile from total system memory and service defaults
- protocol switching for dual-end templates currently has a built-in mapping between `dual_end_https_midbox_sm2_gcm_rps` and `dual_end_http3_midbox_rps`

## Release notes for maintainers

Before publishing broadly, review the following:

- replace the draft `LICENSE` with the approved outbound open-source license
- replace the draft `NOTICE.md` with verified third-party attributions
- verify that the bundled binary, libraries, scripts, and certificate assets are permitted for redistribution
- consider adding CI checks for markdown links and documentation freshness
