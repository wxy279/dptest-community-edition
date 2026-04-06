# dptest Host Manager

This directory contains the host-side preparation package for running `dptest-engine-agent`.

The main entrypoint is:

- `dptest_engine_host_manager.sh`

## Purpose

The host manager is responsible for the part of the system that cannot be safely delegated to the container:

- building and installing `igb_uio`
- assessing and changing NIC driver binding
- assessing and applying hugepage configuration
- starting, stopping, and removing the engine container
- reporting current host state

## Directory contents

- `dptest_engine_host_manager.sh`
- `dpdk-devbind.py`
- `cpu_layout.py`
- `igb_uio.tar.gz`

## Supported operating model

The current repository assumes:

- Linux host
- root access
- Docker available on the host
- the published image `wxy279/dptest-engine-agent:latest` pulled locally, or another image passed with `--image`

## Main commands

The script currently exposes:

- `install-igb-uio <igb_uio.tar.gz> [--auto-install-deps]`
- `assess-nic-binding <target> [target ...] [--json]`
- `bind-nic <target> [target ...] [--confirm]`
- `unbind-nic <target> [target ...]`
- `rollback-nic-binding`
- `assess-hugepages [--pages-per-node N] [--size-kb KB] [--json]`
- `set-hugepages [--pages-per-node N] [--size-kb KB]`
- `rollback-hugepages`
- `start-engine-container [--name NAME] [--image IMAGE] [--agent-token TOKEN] [--token TOKEN]`
- `stop-engine-container [--name NAME]`
- `clear-engine-container [--name NAME]`
- `show <igb_uio|nics|hugepages|memory|all>`

## Image pull

Before running `start-engine-container`, pull the published image:

```bash
docker pull wxy279/dptest-engine-agent:latest
```

The host-manager uses `wxy279/dptest-engine-agent:latest` as the default image for `start-engine-container`. Use `--image` only when you want to override that default.

## Safe workflow

The recommended operator sequence is:

1. inspect current host state with `show all`
2. install `igb_uio`
3. assess a NIC before binding
4. bind only after reviewing the assessment
5. assess hugepages
6. apply hugepages
7. start the engine container
8. record the printed token values

## Container-start behavior

The current script starts the engine container with:

- `--network host`
- `--privileged`
- `/dev/hugepages` mounted
- `/tmp/virtio` mounted
- `/etc/localtime` mounted read-only
- one mapped `/dev/uioX` device per bound NIC

It currently requires:

- at least one NIC bound to `igb_uio`
- at most two NICs bound to `igb_uio`
- hugepages already configured

## State files

The script stores operational state under:

- `/var/lib/igb_uio_manager/state.d/`
- `/var/lib/igb_uio_manager/hugepages.last.state`
- `/var/lib/igb_uio_manager/container.last.env`
- `/var/lib/igb_uio_manager/journal.log`

## Operational warnings

- Binding the wrong NIC can interrupt management connectivity.
- `unbind-nic` and `rollback-nic-binding` depend on state previously recorded by this script.
- Hugepage changes are live sysfs changes.
- `stop-engine-container` does not remove the container definition.
- Token values written to `container.last.env` should be treated as sensitive.

## Recommended usage

Start with:

- [../docs/host-prepare.md](../docs/host-prepare.md)
- [../examples/host-manager-commands.md](../examples/host-manager-commands.md)

AI-agent usage is documented in:

- [../integrations/openclaw/dptest-host-manager/README.md](../integrations/openclaw/dptest-host-manager/README.md)
