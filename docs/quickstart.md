# Quick Start

This quick start walks through the shortest supported path from a fresh repository checkout to a running engine agent and a first API-driven test-case workflow.

## Scope

This guide assumes:

- a Linux host
- root access for host preparation
- Docker installed locally
- at least one NIC available for DPDK-style binding
- the repository checked out locally

## Step 1: Pull the published container image

From any shell with Docker access:

```bash
docker pull wxy279/dptest-engine-agent:latest
```

This image includes:

- the `dpdkproxy` engine binary
- the `dptest-agent-service-v2` API service
- Python 3.12 and the service virtual environment
- application templates and runtime config assets

Local image build is optional and mainly intended for image development. Normal deployment can use the published image directly.

## Step 2: Prepare the host

Read [host-prepare.md](host-prepare.md) before running live host changes.

The normal preparation order is:

1. install `igb_uio`
2. assess the target NIC binding risk
3. bind one NIC to `igb_uio`
4. assess hugepages
5. apply hugepages
6. start the engine container

Example:

```bash
cd dptest-host-manager
sudo ./dptest_engine_host_manager.sh install-igb-uio ./igb_uio.tar.gz
./dptest_engine_host_manager.sh assess-nic-binding <interface-or-pci> --json
sudo ./dptest_engine_host_manager.sh bind-nic <interface-or-pci> --confirm
./dptest_engine_host_manager.sh assess-hugepages --json
sudo ./dptest_engine_host_manager.sh set-hugepages
sudo ./dptest_engine_host_manager.sh start-engine-container
```

Record the printed values for:

- `DPTEST_AGENT_TOKEN`
- `TOKEN`

## Step 3: Verify the service

The container starts the API service on port `18081`.

Health check:

```bash
curl --noproxy '*' -sS http://127.0.0.1:18081/health
```

Expected result:

- an HTTP `200`
- a lightweight JSON health response

## Step 4: Query the available templates

Most `/v2/*` endpoints require bearer-token authentication:

```bash
export BASE_URL=http://127.0.0.1:18081
export TOKEN=<value-printed-by-start-engine-container>

curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  "${BASE_URL}/v2/application-templates"
```

## Step 5: Run the first modeling flow

Choose one of these routes:

- object-by-object flow described in [agent-integration.md](agent-integration.md)
- example walkthroughs in [../examples/README.md](../examples/README.md)

Recommended first-run path:

1. create a project
2. inspect `GET /v2/system/interfaces/live`
3. create an interface
4. create a subnet
5. create an application instance
6. create a load profile
7. create a client
8. create a test case
9. call `validate`
10. call `compile-preview`
11. call `launch-preview`
12. call `runs` when ready to launch

## Step 6: Inspect runtime state

Useful endpoints:

- `GET /v2/runs`
- `GET /v2/runs/{run_id}`
- `GET /v2/runs/{run_id}/summary`
- `GET /v2/runs/{run_id}/diagnosis`
- `GET /v2/summary/current`
- `GET /v2/diagnosis/current`

Useful host-side checks:

```bash
cd dptest-host-manager
./dptest_engine_host_manager.sh show all
```

## What to read next

- [architecture.md](architecture.md)
- [host-prepare.md](host-prepare.md)
- [docker-runtime.md](docker-runtime.md)
- [agent-integration.md](agent-integration.md)
- [faq.md](faq.md)
