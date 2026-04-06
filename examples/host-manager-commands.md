# Host Manager Command Examples

This example shows the safest operator sequence for `dptest-host-manager`.

## 1. Verify the package contents

```bash
cd dptest-host-manager
ls -l
```

Confirm that these files exist together:

- `dptest_engine_host_manager.sh`
- `igb_uio.tar.gz`
- `dpdk-devbind.py`

## 2. Pull the published image

```bash
docker pull wxy279/dptest-engine-agent:latest
```

## 3. Inspect current host state

```bash
./dptest_engine_host_manager.sh show all
```

## 4. Install `igb_uio`

```bash
sudo ./dptest_engine_host_manager.sh install-igb-uio ./igb_uio.tar.gz
```

## 5. Assess a NIC before binding

```bash
./dptest_engine_host_manager.sh assess-nic-binding ens160 --json
```

Review:

- current driver
- IP addresses
- route count
- default route status
- SSH management candidate status
- risk level

## 6. Bind only after review

```bash
sudo ./dptest_engine_host_manager.sh bind-nic ens160 --confirm
```

## 7. Assess hugepages

```bash
./dptest_engine_host_manager.sh assess-hugepages --json
```

## 8. Apply hugepages

```bash
sudo ./dptest_engine_host_manager.sh set-hugepages
```

## 9. Start the engine container

```bash
sudo ./dptest_engine_host_manager.sh start-engine-container
```

Record:

- `DPTEST_AGENT_TOKEN`
- `TOKEN`

The default image for this command is `wxy279/dptest-engine-agent:latest`. Override it with `--image` only when needed.

## 10. Verify final state

```bash
./dptest_engine_host_manager.sh show all
```

## 11. Recovery examples

Restore one NIC:

```bash
sudo ./dptest_engine_host_manager.sh unbind-nic ens160
```

Rollback recorded NIC bindings:

```bash
sudo ./dptest_engine_host_manager.sh rollback-nic-binding
```

Rollback hugepages:

```bash
sudo ./dptest_engine_host_manager.sh rollback-hugepages
```

Stop the container:

```bash
sudo ./dptest_engine_host_manager.sh stop-engine-container
```

Remove the container:

```bash
sudo ./dptest_engine_host_manager.sh clear-engine-container
```
