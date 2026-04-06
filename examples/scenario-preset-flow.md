# Scenario Preset Flow

This example shows the higher-level `scenario preset` workflow for repeatable topology composition.

## When to use this flow

Use a scenario preset when you want:

- a reusable topology description
- a cleaner dual-end scale-out path
- less manual object wiring than raw CRUD

## Assumptions

- the engine container is running
- `BASE_URL` and `TOKEN` are exported
- you already know the target interface and subnet values

## 1. Create the base resources

Create:

- project
- interface
- subnet
- application instance
- load profile

Those are the shared building blocks referenced by the scenario preset.

## 2. Create the scenario preset

Example payload:

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_preset_demo/scenario-presets" \
  -d '{
    "scenario_preset_id": "scenario_preset_demo",
    "name": "scenario preset demo",
    "mode": "client_only",
    "default_load_profile_ref": "load_preset_base",
    "client_slots": [
      {
        "slot_id": "client0",
        "interface_ref": "if_preset_demo",
        "subnet_ref": "subnet_preset_demo",
        "application_instance_ref": "app_preset_base",
        "load_profile_ref": "load_preset_base"
      }
    ]
  }'
```

## 3. Preview the composition

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_preset_demo/scenario-presets/scenario_preset_demo/compose-preview" \
  -d '{
    "test_case_id": "tc_preset_demo",
    "name": "preset-generated test case"
  }'
```

Use the preview to inspect:

- generated clients and servers
- generated test case
- effective thread policy
- effective engine launch profile

## 4. Apply the composition

```bash
curl --noproxy '*' -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${BASE_URL}/v2/projects/proj_preset_demo/scenario-presets/scenario_preset_demo/compose-apply" \
  -d '{
    "test_case_id": "tc_preset_demo",
    "name": "preset-generated test case"
  }'
```

## 5. Launch through the generated test case

After apply, use the normal validation and run flow on the generated test case:

- `validate`
- `compile-preview`
- `launch-preview`
- `runs`

## 6. Scale from one pair to more pairs

To scale up later:

1. add more `client_slots`
2. add more `server_slots` if needed
3. preview again
4. apply again

This is the main advantage of the scenario-preset path over hand-built object wiring.

