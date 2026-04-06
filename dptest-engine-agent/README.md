# dptest Engine Agent

This directory contains the container-image build context for the engine runtime.

The image combines two roles in one container:

- `dptest-agent-service-v2`
  The HTTP API used to model, compile, deploy, and run test cases.
- `dpdkproxy`
  The engine binary launched by the service after host preparation is complete.

Important licensing note:

- `dptest-agent-service-v2` and related original project materials are documented in the repository's Apache-2.0 licensing model unless otherwise noted
- `app/dpdkproxy` is a proprietary commercial binary and is not granted open-source copying, redistribution, or derivative-work rights by this repository

## Directory contents

Key paths in this directory:

- `Dockerfile`
- `dpdkproxy.conf`
- `app/`
- `lib64/`
- `uconf/`
- `cert/`
- `license/`
- `dptest-agent-v2/`

## Published image

The published runtime image can be pulled directly:

```bash
docker pull wxy279/dptest-engine-agent:latest
```

This is the recommended path for normal users. The image already contains both the engine binary and the agent service, so local image build is not required for standard deployment.

## Local build

If you are developing the image itself or validating local changes, you can still build it from this directory:

```bash
docker build -t wxy279/dptest-engine-agent:latest .
```

## What the Dockerfile does

The current Dockerfile:

1. builds OpenSSL 3.5.x
2. builds Python 3.12
3. creates a virtual environment
4. installs the Python service dependencies
5. copies the engine binary, shared libraries, templates, config, and asset files into the final image
6. starts the FastAPI service with `uvicorn`

## Runtime layout

Important paths used at runtime:

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

## API service

The current API service is implemented in:

- `dptest-agent-v2/codes/dptest_agent_service_v2.py`

The service currently supports:

- health checks
- application template listing
- live interface discovery
- CRUD for projects, interfaces, subnets, application instances, load profiles, clients, servers, and test cases
- compile-preview, launch-preview, compile, and run workflows
- summary and diagnosis endpoints
- scenario-preset composition
- metric, recipe, and protocol switching

## Built-in templates

The current `manifest.json` advertises these templates:

- `https_server_get_rps`
- `http3_server_get_rps`
- `http3_server_post_rps`
- `dual_end_https_midbox_sm2_gcm_rps`
- `dual_end_http3_midbox_rps`

Those definitions live under:

- `dptest-agent-v2/templates/manifest.json`
- `dptest-agent-v2/templates/*.conf`

## Authentication

The container expects bearer-token authentication through:

- `DPTEST_AGENT_TOKEN`

The current host-manager startup flow also preserves:

- `TOKEN`

In common operation, both values are set to the same token string.

## Default ports

The image declares:

- `18081` for the API service
- `10086` for engine monitor access used by the service

## Host expectations

This image is not intended to run in isolation without host preparation.

The current repository expects the host to provide:

- prepared hugepages
- one or more NICs bound to `igb_uio`
- mapped `/dev/uioX` devices
- Docker runtime with `--network host` and `--privileged`

The repository's preferred startup path is through:

- `../dptest-host-manager/dptest_engine_host_manager.sh`

## Data and logs

Operational data is stored under:

- `/opt/dptest-agent-v2/data`
- `/opt/dptest-agent-v2/data/compiled`
- `/opt/dptest-agent-v2/data/runs`

Generated config is deployed under:

- `/etc/dproxy`

Backups are stored under:

- `/etc/dproxy/backup`

## Notes on bundled material

This directory contains bundled runtime material such as:

- the engine binary
- shared libraries
- sample certificates
- configuration assets

Licensing guidance for bundled material:

- `app/dpdkproxy` must be treated as a proprietary commercial binary unless separately licensed by its owner
- bundled third-party libraries remain under their own upstream licenses
- sample certificates and keys should be reviewed before any public redistribution

See the repository-level `NOTICE.md` for the mixed-license and proprietary-component summary.

## Related documents

- [../docs/docker-runtime.md](../docs/docker-runtime.md)
- [../docs/agent-integration.md](../docs/agent-integration.md)
- [../integrations/openclaw/dptest-engine-agent/README.md](../integrations/openclaw/dptest-engine-agent/README.md)
