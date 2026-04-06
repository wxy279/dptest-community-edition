#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_URL="${BASE_URL:-http://127.0.0.1:18081}"
TOKEN="${TOKEN:-${DPTEST_AGENT_TOKEN:-}}"

# Use dedicated HTTPS/HTTP1.1-prefixed vars to avoid pollution from prior HTTP3 scripts.
HTTPS11_PROJECT_ID="${HTTPS11_PROJECT_ID:-proj_https11_demo}"
HTTPS11_IF_ID="${HTTPS11_IF_ID:-if0}"
HTTPS11_SUBNET_ID="${HTTPS11_SUBNET_ID:-subnet_https11_client_01}"
HTTPS11_APP_ID="${HTTPS11_APP_ID:-app_https11_get_01}"
HTTPS11_LOAD_ID="${HTTPS11_LOAD_ID:-load_https11_get_full}"
HTTPS11_CLIENT_ID="${HTTPS11_CLIENT_ID:-client_https11_01}"
HTTPS11_TESTCASE_ID="${HTTPS11_TESTCASE_ID:-tc_https11_get_single_client}"
HTTPS11_STATE_FILE="${HTTPS11_STATE_FILE:-$SCRIPT_DIR/.single_https11_server_full_flow.env}"

HTTPS11_APP_TEMPLATE_ID="${HTTPS11_APP_TEMPLATE_ID:-https_server_get_rps}"
HTTPS11_APP_NAME="${HTTPS11_APP_NAME:-https1.1 get single target}"
HTTPS11_DUT_TARGET_HOST="${HTTPS11_DUT_TARGET_HOST:-192.168.65.131}"
HTTPS11_DUT_ACCESS_PORT="${HTTPS11_DUT_ACCESS_PORT:-443}"
HTTPS11_DUT_REQUEST_PATH="${HTTPS11_DUT_REQUEST_PATH:-/index.html}"
HTTPS11_SNI_HOST="${HTTPS11_SNI_HOST:-demo.local}"
HTTPS11_DUT_HOST_HEADER="${HTTPS11_DUT_HOST_HEADER:-${HTTPS11_DUT_TARGET_HOST}:${HTTPS11_DUT_ACCESS_PORT}}"
HTTPS11_TLS_MIN_VERSION="${HTTPS11_TLS_MIN_VERSION:-TLSv1.2}"
HTTPS11_TLS_MAX_VERSION="${HTTPS11_TLS_MAX_VERSION:-TLSv1.2}"
HTTPS11_TLS_CIPHER="${HTTPS11_TLS_CIPHER:-AES128-SHA256}"
HTTPS11_HTTP_VERSION="${HTTPS11_HTTP_VERSION:-1.1}"
HTTPS11_CLIENT_PROFILE="${HTTPS11_CLIENT_PROFILE:-GoogleChrome}"
HTTPS11_SERVER_PROFILE="${HTTPS11_SERVER_PROFILE:-Apache Server 2.0}"
HTTPS11_BROWSER="${HTTPS11_BROWSER:-firefox}"
HTTPS11_CUSTOM_HEADER_NAME="${HTTPS11_CUSTOM_HEADER_NAME:-X-Custom-Header}"
HTTPS11_CUSTOM_HEADER_VALUE="${HTTPS11_CUSTOM_HEADER_VALUE:-CustomValue}"
HTTPS11_PCI_ADDR="${HTTPS11_PCI_ADDR:-0000:02:03.0}"


# Map to generic local names for simpler payload assembly.
PROJECT_ID="$HTTPS11_PROJECT_ID"
IF_ID="$HTTPS11_IF_ID"
SUBNET_ID="$HTTPS11_SUBNET_ID"
APP_ID="$HTTPS11_APP_ID"
LOAD_ID="$HTTPS11_LOAD_ID"
CLIENT_ID="$HTTPS11_CLIENT_ID"
TESTCASE_ID="$HTTPS11_TESTCASE_ID"
STATE_FILE="$HTTPS11_STATE_FILE"
APP_TEMPLATE_ID="$HTTPS11_APP_TEMPLATE_ID"
APP_NAME="$HTTPS11_APP_NAME"
DUT_TARGET_HOST="$HTTPS11_DUT_TARGET_HOST"
DUT_ACCESS_PORT="$HTTPS11_DUT_ACCESS_PORT"
DUT_REQUEST_PATH="$HTTPS11_DUT_REQUEST_PATH"
SNI_HOST="$HTTPS11_SNI_HOST"
DUT_HOST_HEADER="$HTTPS11_DUT_HOST_HEADER"
TLS_MIN_VERSION="$HTTPS11_TLS_MIN_VERSION"
TLS_MAX_VERSION="$HTTPS11_TLS_MAX_VERSION"
TLS_CIPHER="$HTTPS11_TLS_CIPHER"
HTTP_VERSION="$HTTPS11_HTTP_VERSION"
CLIENT_PROFILE="$HTTPS11_CLIENT_PROFILE"
SERVER_PROFILE="$HTTPS11_SERVER_PROFILE"
BROWSER="$HTTPS11_BROWSER"
CUSTOM_HEADER_NAME="$HTTPS11_CUSTOM_HEADER_NAME"
CUSTOM_HEADER_VALUE="$HTTPS11_CUSTOM_HEADER_VALUE"
PCI_ADDR="$HTTPS11_PCI_ADDR"

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: TOKEN or DPTEST_AGENT_TOKEN is required"
  exit 1
fi

curl_json() {
  local method="$1" url="$2" body="${3:-}"
  if [[ -z "$body" ]]; then
    curl --noproxy '*' -sS --connect-timeout 5 --max-time 120 \
      -H "Authorization: Bearer ${TOKEN}" -X "$method" "$url"
  else
    curl --noproxy '*' -sS --connect-timeout 5 --max-time 120 \
      -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
      -X "$method" -d "$body" "$url"
  fi
}

pretty() { python3 -m json.tool; }
log() { echo; echo "[$(date '+%F %T')] $*"; }

APP_PARAMS_JSON="$(python3 - "$DUT_TARGET_HOST" "$DUT_HOST_HEADER" "$DUT_REQUEST_PATH" "$DUT_ACCESS_PORT" "$SNI_HOST" "$TLS_MIN_VERSION" "$TLS_MAX_VERSION" "$TLS_CIPHER" "$HTTP_VERSION" "$CLIENT_PROFILE" "$SERVER_PROFILE" "$BROWSER" "$CUSTOM_HEADER_NAME" "$CUSTOM_HEADER_VALUE" <<'PY'
import json, sys
(target_host, host_header, request_path, access_port, sni_host,
 tls_min_version, tls_max_version, tls_cipher, http_version,
 client_profile, server_profile, browser, custom_header_name,
 custom_header_value) = sys.argv[1:15]
params = {
    'target_hosts': target_host,
    'ACCESS_PORT': int(access_port),
    'REQUEST_PATH': request_path,
    'TLS_MIN_VERSION': tls_min_version,
    'TLS_MAX_VERSION': tls_max_version,
    'TLS_CIPHER': tls_cipher,
    'SNI_HOST': sni_host,
    'HOST_HEADER': host_header,
    'HTTP_VERSION': http_version,
    'CLIENT_PROFILE': client_profile,
    'SERVER_PROFILE': server_profile,
    'BROWSER': browser,
    'CUSTOM_HEADER_NAME': custom_header_name,
    'CUSTOM_HEADER_VALUE': custom_header_value,
}
print(json.dumps(params, ensure_ascii=False))
PY
)"

log "0. health"
curl_json GET "$BASE_URL/health" | pretty

log "1. create project"
curl_json POST "$BASE_URL/v2/projects" "{\"project_id\":\"$PROJECT_ID\",\"name\":\"https11 base\",\"description\":\"0-1 bootstrap base for https1.1 get\"}" | pretty

log "2. create interface"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/interfaces" "{\"interface_id\":\"$IF_ID\",\"dpdk_port_id\":0,\"pci_addr\":\"$PCI_ADDR\",\"label\":\"single-port\"}" | pretty

log "3. create subnet"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/subnets" "{\"subnet_id\":\"$SUBNET_ID\",\"name\":\"$SUBNET_ID\",\"base_addr\":\"192.168.65.240\",\"count\":1,\"network\":\"192.168.65.0\",\"netmask\":24,\"default_gw\":\"192.168.65.1\"}" | pretty

log "4. create application instance (template_id=$APP_TEMPLATE_ID -> stress_https_1.1_server_get_rps.conf)"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/application-instances" "{\"application_instance_id\":\"$APP_ID\",\"template_id\":\"$APP_TEMPLATE_ID\",\"name\":\"$APP_NAME\",\"params\":$APP_PARAMS_JSON}" | pretty

log "5. create load profile"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/load-profiles" "{\"load_profile_id\":\"$LOAD_ID\",\"name\":\"baseline\",\"stress_type\":\"run\",\"stress_mode\":\"SimUsers\",\"max_connection_attemps\":9223372036854775807,\"stages\":[{\"stage\":\"delay\",\"repetitions\":1,\"height\":0,\"ramp_time\":0,\"steady_time\":5},{\"stage\":\"ramp up\",\"repetitions\":1,\"height\":2,\"ramp_time\":2,\"steady_time\":2},{\"stage\":\"steady State\",\"repetitions\":1,\"height\":10,\"ramp_time\":2,\"steady_time\":60},{\"stage\":\"ramp down\",\"repetitions\":1,\"height\":0,\"ramp_time\":6,\"steady_time\":0}]}" | pretty

log "6. create client"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/clients" "{\"client_instance_id\":\"$CLIENT_ID\",\"interface_ref\":\"$IF_ID\",\"subnet_ref\":\"$SUBNET_ID\",\"application_instance_ref\":\"$APP_ID\",\"load_profile_ref\":\"$LOAD_ID\"}" | pretty

log "7. create test case"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/test-cases" "{\"test_case_id\":\"$TESTCASE_ID\",\"name\":\"https11 single client base\",\"mode\":\"client_only\"}" | pretty

log "8. bind test case"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/test-cases/$TESTCASE_ID/bindings" "{\"client_instance_ids\":[\"$CLIENT_ID\"],\"server_instance_ids\":[]}" | pretty

log "9. validate"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/test-cases/$TESTCASE_ID/validate" | pretty

log "10. compile-preview"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/test-cases/$TESTCASE_ID/compile-preview" | pretty

log "11. launch-preview"
curl_json POST "$BASE_URL/v2/projects/$PROJECT_ID/test-cases/$TESTCASE_ID/launch-preview" | pretty

cat > "$STATE_FILE" <<EOF2
export BASE_URL="$BASE_URL"
export TOKEN="$TOKEN"
export PROJECT_ID="$PROJECT_ID"
export APP_ID="$APP_ID"
export TESTCASE_ID="$TESTCASE_ID"
export APP_TEMPLATE_ID="$APP_TEMPLATE_ID"
export HTTPS11_PROJECT_ID="$PROJECT_ID"
export HTTPS11_APP_ID="$APP_ID"
export HTTPS11_TESTCASE_ID="$TESTCASE_ID"
export HTTPS11_APP_TEMPLATE_ID="$APP_TEMPLATE_ID"
EOF2

log "done"
echo "state saved to: $STATE_FILE"
echo "next: source $STATE_FILE && $SCRIPT_DIR/switch_recipe_and_run_https11_server.sh"
