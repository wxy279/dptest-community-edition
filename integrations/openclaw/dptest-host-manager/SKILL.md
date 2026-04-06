---
name: igb-uio-manager
description: Safely operate dptest_engine_host_manager.sh to install igb_uio, assess and bind NICs, manage hugepages, start or stop the engine container, and report host runtime state.
version: 1.4.0
metadata:
  openclaw:
    requires:
      bins:
        - bash
        - ip
        - grep
        - sed
        - awk
        - docker
      anyBins:
        - python
        - python3
        - openssl
    os:
      - linux
---

# igb_uio Manager

Use this skill when the task is about host preparation or host-side lifecycle operations.

Read `workflows/workflows.md` when the task needs:

- a safe NIC-binding workflow
- a safe hugepage workflow
- a safe container-start workflow
- host-state inspection and recovery guidance

## Assumptions

Assume these files are in the same directory unless the user says otherwise:

- `dptest_engine_host_manager.sh`
- `igb_uio.tar.gz`
- `dpdk-devbind.py`

## Safety rules

1. Never bind a NIC before assessment.
2. Treat a default-route or SSH-management NIC as high risk.
3. Explain the risk before any binding change.
4. Only use `bind-nic ... --confirm` after explicit user approval.
5. Assess hugepages before changing them unless the user explicitly wants a direct apply.
6. Explain that hugepage changes modify live sysfs state.
7. Do not start the engine container unless at least one NIC is bound to `igb_uio`.
8. Explain that the current container-start path allows at most two bound NICs.
9. Return both printed token values after container startup.

## What to report after assessment

For NIC assessment, summarize:

- resolved PCI
- resolved interface name
- current driver
- IP addresses
- route count
- default-route status
- SSH-management-candidate status
- risk level
- whether confirmation is required

For hugepage assessment, summarize:

- selected hugepage size
- NUMA nodes found
- current per-node values
- calculated target values
- current total, free, reserved, and surplus pages
- whether rollback state already exists

