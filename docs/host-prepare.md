# Host Preparation

`dptest-host-manager` exists to prepare a Linux host for the `dptest-engine-agent` container.

The current implementation manages:

- `igb_uio` installation
- NIC binding assessment and execution
- hugepage assessment and configuration
- engine container start, stop, and removal
- basic runtime status inspection

## Important warnings

These operations affect the live host.

- Binding the wrong NIC can disconnect the host from the network.
- Binding a NIC that carries the default route or current SSH path is high risk.
- Hugepage changes are written through live sysfs files.
- Container startup expects hugepages and `igb_uio`-bound devices to be ready first.

## Required files

The script expects these files in the same directory:

- `dptest_engine_host_manager.sh`
- `igb_uio.tar.gz`
- `dpdk-devbind.py`

## Required host capabilities

At minimum:

- Linux host
- root privileges
- Docker installed
- shell tools such as `bash`, `ip`, `grep`, `sed`, and `awk`
- Python or Python 3 for `dpdk-devbind.py`

Optional but often required:

- `openssl` for automatic token generation during container startup
- matching kernel headers and kernel-devel packages for `igb_uio` build

## Safe operating sequence

The recommended sequence is:

1. inspect the current host state
2. install `igb_uio`
3. assess a NIC before binding it
4. bind only after reviewing the assessment
5. assess hugepages
6. apply hugepages
7. start the container
8. verify final state

## Inspect current state

```bash
cd dptest-host-manager
./dptest_engine_host_manager.sh show all
```

This gives a quick read of:

- module state
- NIC state
- hugepage state
- memory state

## Install `igb_uio`

```bash
sudo ./dptest_engine_host_manager.sh install-igb-uio ./igb_uio.tar.gz
```

If you explicitly want the script to attempt dependency installation:

```bash
sudo ./dptest_engine_host_manager.sh install-igb-uio ./igb_uio.tar.gz --auto-install-deps
```

## Assess NIC binding risk

Assessment should always happen before binding:

```bash
./dptest_engine_host_manager.sh assess-nic-binding <target> --json
```

Where `<target>` may be:

- a PCI address such as `0000:03:00.0`
- a Linux interface name such as `ens160`

The assessment is intended to tell you:

- which PCI device and interface were resolved
- which driver is currently active
- whether the interface has IP addresses
- whether it carries routes
- whether it carries the default route
- whether it looks like the current SSH management path
- whether explicit confirmation is required

## Bind a NIC

Only bind after reviewing the assessment:

```bash
sudo ./dptest_engine_host_manager.sh bind-nic <target> --confirm
```

The current script records rollback state under:

```text
/var/lib/igb_uio_manager/state.d/
```

## Restore NIC bindings

Restore one device:

```bash
sudo ./dptest_engine_host_manager.sh unbind-nic <target>
```

Restore all recorded bindings that are still bound to `igb_uio`:

```bash
sudo ./dptest_engine_host_manager.sh rollback-nic-binding
```

## Assess hugepages

Assessment first:

```bash
./dptest_engine_host_manager.sh assess-hugepages --json
```

The current script:

- detects or accepts an explicit hugepage size
- inspects NUMA layout when present
- calculates target pages per node
- defaults to three-fifths of each NUMA node's total memory when no explicit page count is provided

## Apply hugepages

```bash
sudo ./dptest_engine_host_manager.sh set-hugepages
```

Or with explicit values:

```bash
sudo ./dptest_engine_host_manager.sh set-hugepages --size-kb 2048 --pages-per-node 1024
```

The script stores a rollback snapshot in:

```text
/var/lib/igb_uio_manager/hugepages.last.state
```

## Roll back hugepages

```bash
sudo ./dptest_engine_host_manager.sh rollback-hugepages
```

## Start the engine container

After NIC binding and hugepages are ready:

```bash
sudo ./dptest_engine_host_manager.sh start-engine-container
```

Current behavior:

- requires at least one NIC bound to `igb_uio`
- allows at most two bound NICs for container startup
- maps `/dev/uioX` devices into the container
- mounts `/dev/hugepages`, `/tmp/virtio`, and `/etc/localtime`
- runs Docker with `--network host` and `--privileged`
- prints `DPTEST_AGENT_TOKEN` and `TOKEN`

Those token values are also written to:

```text
/var/lib/igb_uio_manager/container.last.env
```

## Stop or remove the container

Stop:

```bash
sudo ./dptest_engine_host_manager.sh stop-engine-container
```

Remove:

```bash
sudo ./dptest_engine_host_manager.sh clear-engine-container
```

## Recovery checklist

If something goes wrong, use this order:

1. run `show all`
2. stop or clear the container if needed
3. restore NICs with `unbind-nic` or `rollback-nic-binding`
4. restore hugepages with `rollback-hugepages`
5. confirm the Linux driver and route state are back to normal

## Related documents

- [quickstart.md](quickstart.md)
- [docker-runtime.md](docker-runtime.md)
- [faq.md](faq.md)
- [../dptest-host-manager/README.md](../dptest-host-manager/README.md)

