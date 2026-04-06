# FAQ

## Is this project Linux-only?

For the critical host-preparation workflow, yes.

The current repository supports live NIC discovery, `igb_uio` handling, NIC binding, and hugepage configuration on Linux hosts.

## Why is root access required?

Because the host-manager changes live system state:

- kernel module installation
- NIC driver binding
- hugepage sysfs settings
- container lifecycle with privileged runtime options

## Why are `--network host` and `--privileged` used?

That is the current runtime model implemented by the host-manager.

The container needs direct access to:

- mapped `/dev/uioX` devices
- `/dev/hugepages`
- host network exposure for the API and monitor paths

## Why do I need `pci_addr` on interfaces?

The current launch-plan logic emits `-w <pci_addr>` arguments for the engine. Without `pci_addr`, `launch-preview` and `runs` cannot produce a valid launch plan.

## Why does the host-manager insist on assessing a NIC before binding?

Because binding can remove the NIC from the Linux network stack. If the interface carries IP addresses, routes, a default route, or the current SSH path, the host may become unreachable.

## Why does container startup fail when more than two NICs are bound to `igb_uio`?

The current host-manager startup flow explicitly enforces at least one and at most two bound NICs for container startup.

## What is the difference between `compile-preview`, `compile`, and `runs`?

- `compile-preview` shows what would be rendered
- `compile` can render and deploy the config
- `runs` performs compile, deploy, and process launch

## What is the easiest way to start?

Use this order:

1. build the image
2. prepare the host with `dptest-host-manager`
3. verify `/health`
4. follow the example walkthroughs in `examples/`

## Should I use raw CRUD or scenario presets?

Use raw CRUD when you want full control over each object.

Use `scenario preset` when you want:

- a reusable topology
- a scaled dual-end layout
- a higher-level workflow for composition

## Can I switch an existing application from HTTPS to HTTP3?

Yes, the current service includes:

- `protocol-switch-preview`
- `protocol-switch-apply`

For dual-end templates, the current built-in mapping is:

- `dual_end_https_midbox_sm2_gcm_rps`
- `dual_end_http3_midbox_rps`

## Where are tokens stored?

When the host-manager creates the container, the printed token values are also written to:

```text
/var/lib/igb_uio_manager/container.last.env
```

Treat that file as sensitive.

## Is the repository legally ready for public open-source release?

Not completely yet.

This documentation draft makes the repository understandable, but the current tree still needs:

- final outbound license selection
- final third-party notice verification
- redistribution review for bundled assets

