#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-${BASE_URL:-http://127.0.0.1:18081}}"
TOKEN="${TOKEN:-${DPTEST_AGENT_TOKEN:-}}"
if [[ -z "$TOKEN" ]]; then
  echo "TOKEN or DPTEST_AGENT_TOKEN is required" >&2
  exit 1
fi

PROJECT_ID="${PRESET_PROJECT_ID:-proj_preset_demo}"
INTERFACE_ID="${PRESET_INTERFACE_ID:-if_preset_demo}"
SUBNET_ID="${PRESET_SUBNET_ID:-subnet_preset_demo}"
BASE_APP_ID="${PRESET_BASE_APP_ID:-app_preset_base}"
LOAD_ID="${PRESET_LOAD_ID:-load_preset_base}"
SCENARIO_PRESET_ID="${SCENARIO_PRESET_ID:-scenario_preset_demo}"
STATE_FILE="${STATE_FILE:-./.scenario_preset_full_flow.env}"

PRESET_MODE="${PRESET_MODE:-client_only}"
PRESET_TEMPLATE_ID="${PRESET_TEMPLATE_ID:-https_server_get_rps}"
PRESET_TARGET_HOST="${PRESET_TARGET_HOST:-192.168.65.131}"
PRESET_ACCESS_PORT="${PRESET_ACCESS_PORT:-443}"
PRESET_REQUEST_PATH="${PRESET_REQUEST_PATH:-/index.html}"
PRESET_SNI_HOST="${PRESET_SNI_HOST:-demo.local}"
PRESET_HOST_HEADER="${PRESET_HOST_HEADER:-demo.local}"
PRESET_INTERFACE_PCI_ADDR="${PRESET_INTERFACE_PCI_ADDR:-0000:19:00.0}"
PRESET_DPDK_PORT_ID="${PRESET_DPDK_PORT_ID:-0}"
PRESET_SUBNET_BASE_ADDR="${PRESET_SUBNET_BASE_ADDR:-172.16.50.10}"
PRESET_SUBNET_COUNT="${PRESET_SUBNET_COUNT:-1}"
PRESET_SUBNET_NETWORK="${PRESET_SUBNET_NETWORK:-172.16.50.0}"
PRESET_SUBNET_NETMASK="${PRESET_SUBNET_NETMASK:-24}"
PRESET_SUBNET_GW="${PRESET_SUBNET_GW:-172.16.50.1}"
log() { echo "[$(date '+%F %T')] $*"; }
pretty() { python3 -m json.tool 2>/dev/null || cat; }

curl_json() {
  local method="$1" url="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl --noproxy '*' -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -X "$method" "$url" -d "$body"
  else
    curl --noproxy '*' -sS -H "Authorization: Bearer $TOKEN" -X "$method" "$url"
  fi
}

log "1. create project"
curl_json POST "$BASE_URL/v2/projects" "{\"project_id\":\"$PROJECT_ID\",\"name\":\"scenario preset demo\"}" | pretty

log "2. create interface"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/interfaces" "{\"interface_id\":\"$INTERFACE_ID\",\"dpdk_port_id\":$PRESET_DPDK_PORT_ID,\"pci_addr\":\"$PRESET_INTERFACE_PCI_ADDR\"}" | pretty

log "3. create subnet"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/subnets" "{\"subnet_id\":\"$SUBNET_ID\",\"name\":\"$SUBNET_ID\",\"base_addr\":\"$PRESET_SUBNET_BASE_ADDR\",\"count\":$PRESET_SUBNET_COUNT,\"network\":\"$PRESET_SUBNET_NETWORK\",\"netmask\":$PRESET_SUBNET_NETMASK,\"default_gw\":\"$PRESET_SUBNET_GW\"}" | pretty

log "4. create baseline application instance"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/application-instances" "{\"application_instance_id\":\"$BASE_APP_ID\",\"template_id\":\"$PRESET_TEMPLATE_ID\",\"name\":\"preset baseline app\",\"params\":{\"target_hosts\":\"$PRESET_TARGET_HOST\",\"ACCESS_PORT\":$PRESET_ACCESS_PORT,\"REQUEST_PATH\":\"$PRESET_REQUEST_PATH\",\"TLS_MIN_VERSION\":\"TLSv1.2\",\"TLS_MAX_VERSION\":\"TLSv1.2\",\"TLS_CIPHER\":\"AES128-SHA256\",\"SNI_HOST\":\"$PRESET_SNI_HOST\",\"HOST_HEADER\":\"$PRESET_HOST_HEADER\"}}" | pretty

log "5. create baseline load profile"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/load-profiles" "{\"load_profile_id\":\"$LOAD_ID\",\"name\":\"preset baseline load\",\"stress_type\":\"run\",\"stress_mode\":\"SimUsers\",\"max_connection_attemps\":9223372036854775807,\"stages\":[{\"stage\":\"delay\",\"repetitions\":1,\"height\":0,\"ramp_time\":0,\"steady_time\":1}]}" | pretty

log "6. create scenario preset"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/scenario-presets" "{\"scenario_preset_id\":\"$SCENARIO_PRESET_ID\",\"name\":\"scenario preset demo\",\"mode\":\"$PRESET_MODE\",\"default_load_profile_ref\":\"$LOAD_ID\",\"client_slots\":[{\"slot_id\":\"client0\",\"interface_ref\":\"$INTERFACE_ID\",\"subnet_ref\":\"$SUBNET_ID\",\"application_instance_ref\":\"$BASE_APP_ID\",\"load_profile_ref\":\"$LOAD_ID\"}]}" | pretty

cat > "$STATE_FILE" <<ENV
export BASE_URL="$BASE_URL"
export TOKEN="$TOKEN"
export PRESET_PROJECT_ID="$PROJECT_ID"
export SCENARIO_PRESET_ID="$SCENARIO_PRESET_ID"
export PRESET_INTERFACE_ID="$INTERFACE_ID"
export PRESET_SUBNET_ID="$SUBNET_ID"
export PRESET_BASE_APP_ID="$BASE_APP_ID"
export PRESET_LOAD_ID="$LOAD_ID"
ENV

log "done. state written to $STATE_FILE"
