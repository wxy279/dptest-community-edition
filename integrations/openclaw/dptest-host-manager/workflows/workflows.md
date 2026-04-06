# dptest Host Manager Workflows

This document expands the AI-agent workflow rules for host preparation.

## Golden rule

Treat host preparation as a review-first workflow, not an instant-execution workflow.

## Package verification

Before acting, verify that the working directory contains:

- `dptest_engine_host_manager.sh`
- `igb_uio.tar.gz`
- `dpdk-devbind.py`

## NIC workflow

Recommended order:

1. inspect current host state
2. run `assess-nic-binding <target> --json`
3. summarize the risk
4. wait for explicit approval
5. run `bind-nic <target> --confirm`
6. verify with `show nics`

Risk signals to call out:

- default route present
- interface appears to be the current SSH path
- interface has active IP addresses
- interface has existing routes

## Hugepage workflow

Recommended order:

1. run `assess-hugepages --json`
2. summarize current hugepage state
3. summarize calculated target values
4. wait for explicit approval
5. run `set-hugepages`
6. verify with `show hugepages`

If rollback is requested:

1. run `rollback-hugepages`
2. verify with `show hugepages`

## Container-start workflow

Before starting the container:

1. confirm `igb_uio` is loaded
2. confirm at least one NIC is bound to `igb_uio`
3. confirm hugepages are configured
4. confirm the image exists locally
5. run `start-engine-container`
6. return both printed token values

Current repository constraints:

- at least one bound NIC is required
- at most two bound NICs are allowed
- token values are sensitive

## Stop and cleanup workflow

Use:

- `stop-engine-container` when the user wants to keep the container definition
- `clear-engine-container` when the user wants the container removed

Explain the difference before acting.

## Recovery workflow

If an operation fails or the user asks to restore state, use this order:

1. inspect with `show all`
2. stop or remove the container if needed
3. restore NIC bindings with `unbind-nic` or `rollback-nic-binding`
4. restore hugepages with `rollback-hugepages`
5. verify final state

## Reporting expectations

After assessment or change operations, report:

- what target or scope was used
- whether the operation succeeded
- what the resulting host state is
- what rollback path exists

