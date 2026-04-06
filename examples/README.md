# Examples

This directory contains documentation-first examples for common repository workflows.

The goal is to give GitHub readers a clear starting point without requiring them to inspect the codebase first.

## Included examples

- [host-manager-commands.md](host-manager-commands.md)
  Safe host preparation sequence for `igb_uio`, NIC binding, hugepages, and container startup.
- [single-client-http3-flow.md](single-client-http3-flow.md)
  End-to-end object-model flow for a single-client HTTP/3 test case.
- [scenario-preset-flow.md](scenario-preset-flow.md)
  Higher-level topology flow using scenario presets.

## How to use these examples

1. prepare the host first
2. start the container and capture the bearer token
3. export `BASE_URL` and `TOKEN`
4. follow the example that matches your intended workflow

Suggested defaults:

```bash
export BASE_URL=http://127.0.0.1:18081
export TOKEN=<DPTEST_AGENT_TOKEN>
```

## Notes

- The examples are intentionally documentation-oriented and may require local value changes such as host IPs, PCI addresses, subnet ranges, and template IDs.
- Use `GET /v2/application-templates` and `GET /v2/system/interfaces/live` before applying example payloads on a real environment.

