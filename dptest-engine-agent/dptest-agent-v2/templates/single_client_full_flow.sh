#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_URL="${BASE_URL:-http://127.0.0.1:18081}"
TOKEN="${TOKEN:-${DPTEST_AGENT_TOKEN:-}}"

PROJECT_ID="${PROJECT_ID:-proj_single_nic_demo}"
IF_ID="${IF_ID:-if0}"
SUBNET_ID="${SUBNET_ID:-subnet_client_01}"
APP_ID="${APP_ID:-app_http3_get_01}"
LOAD_ID="${LOAD_ID:-load_http3_get_full}"
CLIENT_ID="${CLIENT_ID:-client_01}"
TESTCASE_ID="${TESTCASE_ID:-tc_http3_get_single_client}"
STATE_FILE="${STATE_FILE:-$SCRIPT_DIR/.single_client_full_flow.env}"

APP_TEMPLATE_ID="${APP_TEMPLATE_ID:-http3_server_get_rps}"
APP_NAME="${APP_NAME:-http3 get single target}"
DUT_TARGET_HOST="${DUT_TARGET_HOST:-192.168.65.131}"
DUT_HOST_HEADER="${DUT_HOST_HEADER:-192.168.65.131:443}"
DUT_REQUEST_PATH="${DUT_REQUEST_PATH:-/}"
DUT_ACCESS_PORT="${DUT_ACCESS_PORT:-443}"
SNI_HOST="${SNI_HOST:-demo.local}"
PCI_ADDR="${PCI_ADDR:-0000:02:03.0}"

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: TOKEN or DPTEST_AGENT_TOKEN is required"
  exit 1
fi

curl_json() {
  local method="$1" url="$2" body="${3:-}"
  if [[ -z "$body" ]]; then
    curl --noproxy '*' -sS --connect-timeout 5 --max-time 120 -H "Authorization: Bearer ${TOKEN}" -X "$method" "$url"
  else
    curl --noproxy '*' -sS --connect-timeout 5 --max-time 120 -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' -X "$method" -d "$body" "$url"
  fi
}

pretty() { python3 -m json.tool; }
log() { echo; echo "[$(date '+%F %T')] $*"; }

APP_PARAMS_JSON="$(python3 - "$DUT_TARGET_HOST" "$DUT_HOST_HEADER" "$DUT_REQUEST_PATH" "$DUT_ACCESS_PORT" "$APP_TEMPLATE_ID" "$SNI_HOST" <<'PY'
import json, sys
target_host, host_header, request_path, access_port, template_id, sni_host = sys.argv[1:7]
params = {
    'target_hosts': target_host,
    'HOST_HEADER': host_header,
    'REQUEST_PATH': request_path,
    'ACCESS_PORT': int(access_port),
}
if template_id == 'https_server_get_rps':
    params['SNI_HOST'] = sni_host
print(json.dumps(params, ensure_ascii=False))
PY
)"

log "0. health"
curl_json GET "$BASE_URL/health" | pretty

log "1. create project"
curl_json POST "$BASE_URL/v2/projects" "{\"project_id\":\"$PROJECT_ID\",\"name\":\"single nic base\",\"description\":\"0-1 bootstrap base\"}" | pretty

log "2. create interface"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/interfaces" "{\"interface_id\":\"$IF_ID\",\"dpdk_port_id\":0,\"pci_addr\":\"$PCI_ADDR\",\"label\":\"single-port\"}" | pretty

log "3. create subnet"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/subnets" "{\"subnet_id\":\"$SUBNET_ID\",\"name\":\"$SUBNET_ID\",\"base_addr\":\"192.168.65.240\",\"count\":1,\"network\":\"192.168.65.0\",\"netmask\":24,\"default_gw\":\"192.168.65.1\"}" | pretty

log "4. create application instance"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/application-instances" "{\"application_instance_id\":\"$APP_ID\",\"template_id\":\"$APP_TEMPLATE_ID\",\"name\":\"$APP_NAME\",\"params\":$APP_PARAMS_JSON}" | pretty

log "5. create load profile"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/load-profiles" "{\"load_profile_id\":\"$LOAD_ID\",\"name\":\"baseline\",\"stress_type\":\"run\",\"stress_mode\":\"SimUsers\",\"max_connection_attemps\":9223372036854775807,\"stages\":[{\"stage\":\"delay\",\"repetitions\":1,\"height\":0,\"ramp_time\":0,\"steady_time\":10},{\"stage\":\"ramp up\",\"repetitions\":1,\"height\":2,\"ramp_time\":2,\"steady_time\":2},{\"stage\":\"stair step\",\"repetitions\":1,\"height\":2,\"ramp_time\":2,\"steady_time\":2},{\"stage\":\"steady State\",\"repetitions\":1,\"height\":10,\"ramp_time\":2,\"steady_time\":120},{\"stage\":\"ramp down\",\"repetitions\":1,\"height\":0,\"ramp_time\":8,\"steady_time\":0}]}" | pretty

log "6. create client"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/clients" "{\"client_instance_id\":\"$CLIENT_ID\",\"interface_ref\":\"$IF_ID\",\"subnet_ref\":\"$SUBNET_ID\",\"application_instance_ref\":\"$APP_ID\",\"load_profile_ref\":\"$LOAD_ID\"}" | pretty

log "7. create test case"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/test-cases" "{\"test_case_id\":\"$TESTCASE_ID\",\"name\":\"single client base\",\"mode\":\"client_only\"}" | pretty

log "8. bind test case"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/test-cases/$TESTCASE_ID/bindings" "{\"client_instance_ids\":[\"$CLIENT_ID\"],\"server_instance_ids\":[]}" | pretty

log "9. validate"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/test-cases/$TESTCASE_ID/validate" | pretty

log "10. compile-preview"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/test-cases/$TESTCASE_ID/compile-preview" | pretty

log "11. launch-preview"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/test-cases/$TESTCASE_ID/launch-preview" | pretty

cat > "$STATE_FILE" <<EOF
export BASE_URL="$BASE_URL"
export TOKEN="$TOKEN"
export PROJECT_ID="$PROJECT_ID"
export APP_ID="$APP_ID"
export TESTCASE_ID="$TESTCASE_ID"
export APP_TEMPLATE_ID="$APP_TEMPLATE_ID"
EOF

log "done"
echo "state saved to: $STATE_FILE"
echo "next: source $STATE_FILE && $SCRIPT_DIR/switch_metric_on_existing_base.sh"
