# Docker Runtime

This document describes the current runtime layout and startup assumptions for the `dptest-engine-agent` image.

## Image role

The image built from `dptest-engine-agent/Dockerfile` packages both:

- the `dptest-agent-service-v2` HTTP API service
- the `dpdkproxy` engine binary and supporting runtime files

This means orchestration and engine execution happen inside the same container.

Licensing note:

- the service and documentation around it are part of the repository's open-source materials unless otherwise noted
- the bundled `dpdkproxy` engine binary is a proprietary commercial component and should not be assumed to be freely copyable, redistributable, or modifiable

## Published image

```bash
docker pull wxy279/dptest-engine-agent:latest
```

This is the recommended runtime image for normal deployment. The host-manager uses the same image name as its default `start-engine-container` target.

## Optional local build

If you need to rebuild the runtime image locally from this repository:

```bash
cd dptest-engine-agent
docker build -t wxy279/dptest-engine-agent:latest .
```

## Image layout

Important runtime paths from the current Dockerfile:

- `/usr/local/dproxy/app`
- `/usr/local/dproxy/lib64`
- `/usr/local/dproxy/uconf`
- `/etc/dproxy`
- `/etc/dproxy/backup`
- `/usr/share/dproxy/cert`
- `/usr/share/dproxy/license`
- `/opt/dptest-agent-v2/codes`
- `/opt/dptest-agent-v2/templates`
- `/opt/dptest-agent-v2/data`
- `/opt/dptest-agent-v2/data/compiled`
- `/tmp/dptest-agent-v2/rendered`

## Default container process

The current image starts:

```text
python -m uvicorn dptest_agent_service_v2:app --host 0.0.0.0 --port 18081
```

## Exposed ports

The Dockerfile declares:

- `18081` for the agent API
- `10086` for engine monitor access used by the service

In practice, the host-manager starts the container with `--network host`, so those ports are exposed directly on the host network namespace.

## Required runtime mounts and devices

The host-manager currently starts the container with:

- `--network host`
- `--privileged`
- `-v /dev/hugepages:/dev/hugepages`
- `-v /tmp/virtio:/tmp/virtio`
- `-v /etc/localtime:/etc/localtime:ro`
- `--device=/dev/uioX:/dev/uioX` for each bound NIC

This reflects the repository's intended runtime model:

- host-side DPDK preparation happens outside the container
- the container consumes already-prepared UIO devices and hugepages

## Important environment variables

The Dockerfile sets or expects the following key variables:

- `DPTEST_AGENT_TOKEN`
  Bearer token expected by the API service.
- `TOKEN`
  A general token value preserved by the host-manager and commonly kept equal to `DPTEST_AGENT_TOKEN`.
- `DPTEST_TEMPLATE_DIR`
  Defaults to `/opt/dptest-agent-v2/templates`.
- `DPTEST_DEPLOY_DIR`
  Defaults to `/etc/dproxy`.
- `DPTEST_DEPLOY_FILENAME`
  Defaults to `dpdkproxy.conf`.
- `DPTEST_BACKUP_DIR`
  Defaults to `/etc/dproxy/backup`.
- `DPTEST_RENDER_DIR`
  Defaults to `/tmp/dptest-agent-v2/rendered`.
- `DPTEST_ENGINE_MONITOR_URL`
  Defaults to `http://127.0.0.1:10086/run/monitor`.
- `DPTEST_STAGE_MAP`
  Defines the stage-name mapping used by the service.
- `DPTEST_V2_BASE_DIR`
  Defaults to `/opt/dptest-agent-v2`.
- `DPTEST_V2_DATA_DIR`
  Defaults to `/opt/dptest-agent-v2/data`.
- `DPTEST_V2_DB_PATH`
  Defaults to `/opt/dptest-agent-v2/data/dptest_agent_v2.db`.
- `DPTEST_V2_COMPILED_DIR`
  Defaults to `/opt/dptest-agent-v2/data/compiled`.

The service also supports runtime overrides for:

- NUMA0 CPU inventory
- system memory
- engine binary path
- engine memory channels
- engine log level
- extra app args
- extra EAL args
- extra environment variables

## Launch model

The service compiles user-created objects into:

- rendered configuration content
- a deployable config file
- an engine launch plan containing the binary path, app args, EAL args, and environment overrides

For launched runs, the current code:

- builds a launch plan
- starts the engine process with `subprocess.Popen`
- writes stdout and stderr logs under the run log directory
- tracks run state through the API

## Data persistence

The current service persists operational data under:

- `/opt/dptest-agent-v2/data`
- `/opt/dptest-agent-v2/data/compiled`
- `/opt/dptest-agent-v2/data/runs` when run logs are present

Generated config is deployed under:

- `/etc/dproxy/dpdkproxy.conf` by default

Backups are stored under:

- `/etc/dproxy/backup`

## Current runtime limits

The current repository behavior implies these constraints:

- the host-manager startup path expects at most two `igb_uio` NIC bindings
- `launch-preview` and `runs` need `pci_addr` on all used interfaces
- automatic NUMA0 CPU detection and live interface discovery are Linux-only
- engine launch profile derivation depends on total-memory detection or the related override variables

## Troubleshooting

If the container starts but the API does not respond:

1. confirm Docker is using `--network host`
2. verify the container is running
3. verify port `18081` is listening on the host
4. inspect container logs

If the service is healthy but launches fail:

1. confirm the interfaces in the test case include `pci_addr`
2. confirm hugepages are mounted into the container
3. confirm the relevant `/dev/uioX` devices are mapped
4. inspect the run logs under the service data directory

## Related documents

- [quickstart.md](quickstart.md)
- [architecture.md](architecture.md)
- [agent-integration.md](agent-integration.md)
- [../dptest-engine-agent/README.md](../dptest-engine-agent/README.md)
