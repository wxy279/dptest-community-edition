# Single-Client HTTP/3 Flow

This example demonstrates the object-by-object flow for a single-client HTTP/3 test case.

## Assumptions

- the engine container is running
- `BASE_URL` points to the API service
- `TOKEN` contains the bearer token
- you have already identified a valid `pci_addr`

## Suggested environment

```bash
export BASE_URL=http://127.0.0.1:18081
export TOKEN=<DPTEST_AGENT_TOKEN>
export PROJECT_ID=proj_single_http3_demo
export TEST_CASE_ID=tc_single_http3_demo
```

## 1. Create the project

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects" \
  -d '{
    "project_id": "proj_single_http3_demo",
    "name": "single http3 demo",
    "description": "single-client http3 walkthrough"
  }'
```

## 2. Inspect live interfaces

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  "${BASE_URL}/v2/system/interfaces/live"
```

## 3. Create an interface

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/interfaces" \
  -d '{
    "interface_id": "if0",
    "dpdk_port_id": 0,
    "pci_addr": "0000:02:03.0",
    "label": "client-port"
  }'
```

## 4. Create a subnet

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/subnets" \
  -d '{
    "subnet_id": "subnet_client_01",
    "name": "subnet_client_01",
    "base_addr": "192.168.65.240",
    "count": 1,
    "network": "192.168.65.0",
    "netmask": 24,
    "default_gw": "192.168.65.1"
  }'
```

## 5. Create an application instance

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/application-instances" \
  -d '{
    "application_instance_id": "app_http3_get_01",
    "template_id": "http3_server_get_rps",
    "name": "single-client http3 app",
    "params": {
      "target_hosts": "192.168.65.131",
      "HOST_HEADER": "192.168.65.131:443",
      "REQUEST_PATH": "/",
      "ACCESS_PORT": 443
    }
  }'
```

## 6. Create a load profile

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/load-profiles" \
  -d '{
    "load_profile_id": "load_http3_get_full",
    "name": "baseline",
    "stress_type": "run",
    "stress_mode": "SimUsers",
    "max_connection_attemps": 9223372036854775807,
    "stages": [
      {"stage": "delay", "repetitions": 1, "height": 0, "ramp_time": 0, "steady_time": 20},
      {"stage": "ramp up", "repetitions": 1, "height": 2, "ramp_time": 2, "steady_time": 2},
      {"stage": "stair step", "repetitions": 1, "height": 2, "ramp_time": 2, "steady_time": 2},
      {"stage": "steady State", "repetitions": 1, "height": 10, "ramp_time": 2, "steady_time": 120},
      {"stage": "ramp down", "repetitions": 1, "height": 0, "ramp_time": 8, "steady_time": 0}
    ]
  }'
```

## 7. Create a client

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/clients" \
  -d '{
    "client_instance_id": "client_01",
    "interface_ref": "if0",
    "subnet_ref": "subnet_client_01",
    "application_instance_ref": "app_http3_get_01",
    "load_profile_ref": "load_http3_get_full"
  }'
```

## 8. Create and bind a test case

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/test-cases" \
  -d '{
    "test_case_id": "tc_single_http3_demo",
    "name": "single http3 demo",
    "mode": "client_only"
  }'
```

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/test-cases/tc_single_http3_demo/bindings" \
  -d '{
    "client_instance_ids": ["client_01"],
    "server_instance_ids": []
  }'
```

## 9. Preview and run

Validate:

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/test-cases/tc_single_http3_demo/validate"
```

Compile preview:

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/test-cases/tc_single_http3_demo/compile-preview"
```

Launch preview:

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/test-cases/tc_single_http3_demo/launch-preview"
```

Run:

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_single_http3_demo/test-cases/tc_single_http3_demo/runs" \
  -d '{
    "run_mode": "run",
    "apply_after_deploy": true
  }'
```
