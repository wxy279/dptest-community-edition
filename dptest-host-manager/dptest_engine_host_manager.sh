#!/usr/bin/env bash
set -euo pipefail

# dptest_engine_host_manager.sh
#
# Commands:
#   install-igb-uio <igb_uio.tar.gz> [--auto-install-deps]
#   assess-nic-binding <target> [target ...] [--json]
#   bind-nic <target> [target ...] [--confirm]
#   unbind-nic <target> [target ...]
#   rollback-nic-binding
#   assess-hugepages [--pages-per-node N] [--size-kb KB] [--json]
#   set-hugepages [--pages-per-node N] [--size-kb KB]
#   rollback-hugepages
#   start-engine-container [--name NAME] [--image IMAGE] [--agent-token TOKEN] [--token TOKEN]
#   stop-engine-container [--name NAME]
#   clear-engine-container [--name NAME]
#   show <igb_uio|nics|hugepages|memory|all>
#
# Target:
#   A target may be either:
#   - a PCI address, such as 0000:03:00.0
#   - a Linux interface name, such as ens192
#
# Notes:
#   - All comments and user-facing messages in this script are intentionally in English.
#   - This script looks for dpdk-devbind.py in the same directory as this script first.
#   - Binding records are stored under /var/lib/igb_uio_manager/state.d/
#   - rollback-nic-binding restores all recorded PCI devices that are still
#     currently bound to igb_uio.
#   - The bind-nic command does not prompt interactively. Use --confirm explicitly
#     if the assessment indicates confirmation is required.
#   - Hugepage configuration uses per-node nr_hugepages sysfs files when NUMA
#     nodes are present. If --pages-per-node is not provided, the script uses
#     three-fifths of each NUMA node's total memory to calculate the target.

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
KVER="$(uname -r)"
KSRC="/lib/modules/${KVER}/build"

STATE_ROOT="/var/lib/igb_uio_manager"
STATE_DIR="${STATE_ROOT}/state.d"
JOURNAL_FILE="${STATE_ROOT}/journal.log"
HUGEPAGES_STATE_FILE="${STATE_ROOT}/hugepages.last.state"
CONTAINER_ENV_FILE="${STATE_ROOT}/container.last.env"
CONTAINER_NAME_DEFAULT="dptest-engine-agent"
CONTAINER_IMAGE_DEFAULT="wxy279/dptest-engine-agent:latest"

AUTO_INSTALL_DEPS="false"
OUTPUT_JSON="false"
CONFIRM="false"
COMMAND=""
PKG_TAR=""
TARGET_LIST=()
HUGEPAGES_PAGES_PER_NODE=""
HUGEPAGES_SIZE_KB=""
SHOW_SCOPE=""
CONTAINER_NAME="${CONTAINER_NAME_DEFAULT}"
CONTAINER_IMAGE="${CONTAINER_IMAGE_DEFAULT}"
CONTAINER_AGENT_TOKEN=""
CONTAINER_TOKEN=""
CONTAINER_BOUND_PCIS=()
CONTAINER_UIO_DEVICES=()

usage() {
  cat <<EOF
Usage:
  ${SCRIPT_NAME} install-igb-uio <igb_uio.tar.gz> [--auto-install-deps]
  ${SCRIPT_NAME} assess-nic-binding <target> [target ...] [--json]
  ${SCRIPT_NAME} bind-nic <target> [target ...] [--confirm]
  ${SCRIPT_NAME} unbind-nic <target> [target ...]
  ${SCRIPT_NAME} rollback-nic-binding
  ${SCRIPT_NAME} assess-hugepages [--pages-per-node N] [--size-kb KB] [--json]
  ${SCRIPT_NAME} set-hugepages [--pages-per-node N] [--size-kb KB]
  ${SCRIPT_NAME} rollback-hugepages
  ${SCRIPT_NAME} start-engine-container [--name NAME] [--image IMAGE] [--agent-token TOKEN] [--token TOKEN]
  ${SCRIPT_NAME} stop-engine-container [--name NAME]
  ${SCRIPT_NAME} clear-engine-container [--name NAME]
  ${SCRIPT_NAME} show <igb_uio|nics|hugepages|memory|all>

Examples:
  ${SCRIPT_NAME} install-igb-uio ./igb_uio.tar.gz
  ${SCRIPT_NAME} install-igb-uio ./igb_uio.tar.gz --auto-install-deps

  ${SCRIPT_NAME} assess-nic-binding 0000:03:00.0
  ${SCRIPT_NAME} assess-nic-binding ens192 --json
  ${SCRIPT_NAME} bind-nic ens192 --confirm
  ${SCRIPT_NAME} unbind-nic ens192
  ${SCRIPT_NAME} rollback-nic-binding

  ${SCRIPT_NAME} assess-hugepages
  ${SCRIPT_NAME} assess-hugepages --json
  ${SCRIPT_NAME} assess-hugepages --size-kb 2048
  ${SCRIPT_NAME} set-hugepages
  ${SCRIPT_NAME} set-hugepages --pages-per-node 1024
  ${SCRIPT_NAME} set-hugepages --size-kb 1048576 --pages-per-node 4
  ${SCRIPT_NAME} rollback-hugepages

  ${SCRIPT_NAME} start-engine-container
  ${SCRIPT_NAME} start-engine-container --agent-token mytoken --token mytoken
  ${SCRIPT_NAME} stop-engine-container
  ${SCRIPT_NAME} clear-engine-container

  ${SCRIPT_NAME} show <igb_uio|nics|hugepages|memory|all>
EOF
}

log() {
  echo "[INFO]  $*"
}

warn() {
  echo "[WARN]  $*" >&2
}

err() {
  echo "[ERROR] $*" >&2
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

is_module_loaded() {
  local mod="$1"
  grep -q "^${mod}[[:space:]]" /proc/modules 2>/dev/null
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "This command must be run as root."
    exit 1
  fi
}

detect_pkg_manager() {
  if have_cmd dnf; then
    echo "dnf"
    return
  fi
  if have_cmd yum; then
    echo "yum"
    return
  fi
  if have_cmd apt-get; then
    echo "apt-get"
    return
  fi
  echo ""
}

print_install_hint_for_cmd() {
  local cmd="$1"
  local pm
  pm="$(detect_pkg_manager)"

  case "$cmd" in
    gcc|make|tar|modinfo|depmod|modprobe|insmod|grep|basename|readlink|sed|awk|cut|date|paste|tr|sort|cat)
      case "$pm" in
        dnf)
          echo "Run: dnf install -y gcc make tar kmod coreutils grep sed gawk"
          ;;
        yum)
          echo "Run: yum install -y gcc make tar kmod coreutils grep sed gawk"
          ;;
        apt-get)
          echo "Run: apt-get update && apt-get install -y build-essential tar kmod coreutils grep sed gawk"
          ;;
        *)
          echo "Please install the package providing command: ${cmd}"
          ;;
      esac
      ;;
    python|python3)
      case "$pm" in
        dnf)
          echo "Run: dnf install -y python3"
          ;;
        yum)
          echo "Run: yum install -y python"
          ;;
        apt-get)
          echo "Run: apt-get update && apt-get install -y python3"
          ;;
        *)
          echo "Please install Python."
          ;;
      esac
      ;;
    ip)
      case "$pm" in
        dnf)
          echo "Run: dnf install -y iproute"
          ;;
        yum)
          echo "Run: yum install -y iproute"
          ;;
        apt-get)
          echo "Run: apt-get update && apt-get install -y iproute2"
          ;;
        *)
          echo "Please install the package providing the ip command."
          ;;
      esac
      ;;
    docker)
      case "$pm" in
        dnf)
          echo "Run: dnf install -y docker"
          ;;
        yum)
          echo "Run: yum install -y docker"
          ;;
        apt-get)
          echo "Run: apt-get update && apt-get install -y docker.io"
          ;;
        *)
          echo "Please install Docker."
          ;;
      esac
      ;;
    openssl)
      case "$pm" in
        dnf)
          echo "Run: dnf install -y openssl"
          ;;
        yum)
          echo "Run: yum install -y openssl"
          ;;
        apt-get)
          echo "Run: apt-get update && apt-get install -y openssl"
          ;;
        *)
          echo "Please install OpenSSL."
          ;;
      esac
      ;;
    *)
      echo "Please install the package providing command: ${cmd}"
      ;;
  esac
}

print_kernel_devel_hint() {
  local pm
  pm="$(detect_pkg_manager)"

  case "$pm" in
    dnf)
      echo "Run: dnf install -y kernel-devel-${KVER} kernel-headers-${KVER}"
      ;;
    yum)
      echo "Run: yum install -y kernel-devel-${KVER} kernel-headers-${KVER}"
      ;;
    apt-get)
      echo "Run: apt-get update && apt-get install -y linux-headers-${KVER}"
      ;;
    *)
      echo "Please install kernel build packages matching the running kernel: ${KVER}"
      ;;
  esac
}

auto_install_basic_deps() {
  local pm
  pm="$(detect_pkg_manager)"

  if [[ -z "${pm}" ]]; then
    err "No supported package manager was detected for automatic dependency installation."
    return 1
  fi

  log "Trying to install missing dependencies automatically with ${pm}"

  case "$pm" in
    dnf)
      dnf install -y gcc make tar kmod coreutils grep sed gawk iproute "kernel-devel-${KVER}" "kernel-headers-${KVER}"
      ;;
    yum)
      yum install -y gcc make tar kmod coreutils grep sed gawk iproute "kernel-devel-${KVER}" "kernel-headers-${KVER}"
      ;;
    apt-get)
      apt-get update
      apt-get install -y build-essential tar kmod coreutils grep sed gawk iproute2 "linux-headers-${KVER}"
      ;;
    *)
      err "Unsupported package manager: ${pm}"
      return 1
      ;;
  esac
}

get_python_cmd() {
  if have_cmd python; then
    echo "python"
    return 0
  fi
  if have_cmd python3; then
    echo "python3"
    return 0
  fi
  return 1
}

find_devbind() {
  local candidates=(
    "${SCRIPT_DIR}/dpdk-devbind.py"
    "dpdk-devbind.py"
    "/usr/share/dpdk/usertools/dpdk-devbind.py"
    "/usr/local/share/dpdk/usertools/dpdk-devbind.py"
    "/opt/dpdk/usertools/dpdk-devbind.py"
    "/usr/local/src/dpdk/usertools/dpdk-devbind.py"
  )

  local p
  for p in "${candidates[@]}"; do
    if [[ "${p}" == "dpdk-devbind.py" ]]; then
      if have_cmd dpdk-devbind.py; then
        command -v dpdk-devbind.py
        return 0
      fi
    else
      if [[ -f "${p}" ]]; then
        echo "${p}"
        return 0
      fi
    fi
  done

  return 1
}

ensure_state_dirs() {
  mkdir -p "${STATE_DIR}"
  touch "${JOURNAL_FILE}"
}

sanitize_pci_for_filename() {
  local pci="$1"
  echo "${pci}" | sed 's/[:.]/_/g'
}

state_file_for_pci() {
  local pci="$1"
  local key
  key="$(sanitize_pci_for_filename "${pci}")"
  echo "${STATE_DIR}/${key}.state"
}

find_state_file_by_ifname() {
  local ifname="$1"
  local f
  shopt -s nullglob
  for f in "${STATE_DIR}"/*.state; do
    if [[ "$(read_state_value "${f}" "INTERFACE_NAME")" == "${ifname}" ]]; then
      echo "${f}"
      shopt -u nullglob
      return 0
    fi
  done
  shopt -u nullglob
  return 1
}

append_journal() {
  local action="$1"
  local pci="$2"
  local from_driver="$3"
  local to_driver="$4"
  local now_epoch
  local now_iso

  now_epoch="$(date +%s)"
  now_iso="$(date '+%Y-%m-%d %H:%M:%S')"

  echo "${now_epoch}|${now_iso}|${action}|${pci}|${from_driver}|${to_driver}" >> "${JOURNAL_FILE}"
}

read_state_value() {
  local state_file="$1"
  local key="$2"
  grep "^${key}=" "${state_file}" | head -n1 | cut -d'=' -f2-
}

write_state_file() {
  local pci="$1"
  local ifname="$2"
  local orig_driver="$3"
  local orig_operstate="$4"
  local ip_csv="$5"
  local route_count="$6"
  local default_route="$7"
  local ssh_candidate="$8"
  local bound_at_epoch="$9"
  local bound_at_iso="${10}"

  local state_file
  state_file="$(state_file_for_pci "${pci}")"

  cat > "${state_file}" <<EOF
PCI_ADDR=${pci}
INTERFACE_NAME=${ifname}
ORIGINAL_DRIVER=${orig_driver}
ORIGINAL_OPERSTATE=${orig_operstate}
ORIGINAL_IP_LIST=${ip_csv}
ORIGINAL_ROUTE_COUNT=${route_count}
DEFAULT_ROUTE_IFACE=${default_route}
SSH_MANAGEMENT_CANDIDATE=${ssh_candidate}
BOUND_AT_EPOCH=${bound_at_epoch}
BOUND_AT_ISO=${bound_at_iso}
TARGET_DRIVER=igb_uio
EOF
}

check_install_requirements() {
  local missing=0
  local cmd

  for cmd in tar make gcc modprobe depmod insmod modinfo grep basename readlink sed awk cut date; do
    if ! have_cmd "${cmd}"; then
      err "Required command not found: ${cmd}"
      print_install_hint_for_cmd "${cmd}"
      missing=1
    fi
  done

  if [[ "${missing}" -ne 0 && "${AUTO_INSTALL_DEPS}" == "true" ]]; then
    auto_install_basic_deps || true
  fi

  missing=0
  for cmd in tar make gcc modprobe depmod insmod modinfo grep basename readlink sed awk cut date; do
    if ! have_cmd "${cmd}"; then
      err "Still missing required command: ${cmd}"
      missing=1
    fi
  done

  if [[ "${missing}" -ne 0 ]]; then
    exit 2
  fi

  if [[ ! -d "${KSRC}" || ! -f "${KSRC}/Makefile" ]]; then
    err "Kernel build directory is missing: ${KSRC}"
    print_kernel_devel_hint

    if [[ "${AUTO_INSTALL_DEPS}" == "true" ]]; then
      auto_install_basic_deps || true
    fi
  fi

  if [[ ! -d "${KSRC}" || ! -f "${KSRC}/Makefile" ]]; then
    err "Kernel build directory is still missing after checks: ${KSRC}"
    exit 3
  fi
}

check_network_requirements() {
  local cmd
  for cmd in ip grep sed awk cut date basename readlink; do
    if ! have_cmd "${cmd}"; then
      err "Required command not found: ${cmd}"
      print_install_hint_for_cmd "${cmd}"
      exit 4
    fi
  done
}

check_bind_requirements() {
  local py
  local devbind

  check_network_requirements

  py="$(get_python_cmd)" || {
    err "Python was not found."
    print_install_hint_for_cmd "python"
    exit 5
  }

  devbind="$(find_devbind)" || {
    err "dpdk-devbind.py was not found."
    err "Place dpdk-devbind.py in the same directory as this script."
    exit 6
  }

  log "Using Python interpreter: ${py}"
  log "Using dpdk-devbind.py: ${devbind}"
}

check_hugepage_requirements() {
  local cmd
  for cmd in grep sed awk cut date basename readlink tr sort cat; do
    if ! have_cmd "${cmd}"; then
      err "Required command not found: ${cmd}"
      print_install_hint_for_cmd "${cmd}"
      exit 7
    fi
  done

  if [[ ! -d "/sys/kernel/mm/hugepages" ]]; then
    err "Hugepage sysfs directory was not found: /sys/kernel/mm/hugepages"
    exit 8
  fi
}

check_docker_requirements() {
  local cmd

  for cmd in docker grep sed awk cut date basename readlink sort cat; do
    if ! have_cmd "${cmd}"; then
      err "Required command not found: ${cmd}"
      print_install_hint_for_cmd "${cmd}"
      exit 26
    fi
  done
}

check_container_start_requirements() {
  check_hugepage_requirements
  check_docker_requirements
}

prepare_workspace() {
  WORKDIR="$(mktemp -d /tmp/igb_uio_build.XXXXXX)"
  trap 'rm -rf "${WORKDIR}"' EXIT

  log "Extracting source package: ${PKG_TAR}"
  tar -xzf "${PKG_TAR}" -C "${WORKDIR}"

  if [[ -d "${WORKDIR}/igb_uio" ]]; then
    SRC_DIR="${WORKDIR}/igb_uio"
  else
    SRC_DIR="${WORKDIR}"
  fi

  if [[ ! -f "${SRC_DIR}/igb_uio.c" ]]; then
    err "igb_uio.c was not found after extracting the source package."
    err "Expected source layout: either ./igb_uio/igb_uio.c or ./igb_uio.c inside the tarball."
    exit 7
  fi

  if [[ ! -f "${SRC_DIR}/Makefile" && ! -f "${SRC_DIR}/Kbuild" ]]; then
    err "Neither Makefile nor Kbuild was found in the source directory: ${SRC_DIR}"
    exit 8
  fi
}

build_module() {
  log "Building igb_uio for kernel: ${KVER}"
  log "Using kernel build directory: ${KSRC}"
  log "Using source directory: ${SRC_DIR}"

  unset CC || true
  unset HOSTCC || true
  unset ARCH || true
  unset CROSS_COMPILE || true
  unset LLVM || true
  unset LLVM_IAS || true
  unset KCFLAGS || true
  unset KCPPFLAGS || true
  unset CFLAGS || true
  unset CPPFLAGS || true
  unset LDFLAGS || true

  make -C "${KSRC}" M="${SRC_DIR}" clean
  make -C "${KSRC}" M="${SRC_DIR}"

  if [[ ! -f "${SRC_DIR}/igb_uio.ko" ]]; then
    err "Build completed but igb_uio.ko was not generated."
    exit 9
  fi

  log "Build successful: ${SRC_DIR}/igb_uio.ko"
}

install_module() {
  local target_dir="/lib/modules/${KVER}/extra"
  local target_ko="${target_dir}/igb_uio.ko"

  mkdir -p "${target_dir}"
  cp -f "${SRC_DIR}/igb_uio.ko" "${target_ko}"

  log "Module installed to: ${target_ko}"

  depmod -a
  log "depmod completed"

  modprobe uio
  log "Loaded module: uio"

  if modprobe igb_uio 2>/dev/null; then
    log "Loaded module: igb_uio"
  else
    insmod "${target_ko}"
    log "Loaded module with insmod: ${target_ko}"
  fi

  log "Waiting 5 seconds for module load state to settle"
  sleep 5

  if ! is_module_loaded "igb_uio"; then
    err "igb_uio does not appear to be loaded after installation."
    exit 10
  fi

  log "Module load verification passed"
  modinfo "${target_ko}" | grep -E '^(filename|name|vermagic):' || true
}

ensure_igb_uio_loaded() {
  modprobe uio || true
  modprobe igb_uio || true
  sleep 5

  if ! is_module_loaded "igb_uio"; then
    err "igb_uio is not loaded."
    err "Run the install-igb-uio command first."
    exit 11
  fi
}

is_pci_addr() {
  local s="$1"
  [[ "${s}" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$ ]]
}

pci_exists() {
  local pci="$1"
  [[ -d "/sys/bus/pci/devices/${pci}" ]]
}

ifname_exists() {
  local ifname="$1"
  [[ -e "/sys/class/net/${ifname}" ]]
}

get_ifname_from_pci() {
  local pci="$1"
  local netdir="/sys/bus/pci/devices/${pci}/net"
  if [[ -d "${netdir}" ]]; then
    ls "${netdir}" 2>/dev/null | head -n1 || true
  else
    echo ""
  fi
}

get_pci_from_ifname() {
  local ifname="$1"
  local devlink="/sys/class/net/${ifname}/device"
  if [[ -L "${devlink}" || -e "${devlink}" ]]; then
    basename "$(readlink -f "${devlink}")"
  else
    echo ""
  fi
}

get_current_driver() {
  local pci="$1"
  local driver_link="/sys/bus/pci/devices/${pci}/driver"
  if [[ -L "${driver_link}" ]]; then
    basename "$(readlink -f "${driver_link}")"
  else
    echo ""
  fi
}

get_meminfo_value() {
  local key="$1"
  awk -v k="${key}" '$1 == k ":" {print $2; exit}' /proc/meminfo
}

get_bound_igb_uio_pcis() {
  local devpath

  for devpath in /sys/bus/pci/drivers/igb_uio/*:*; do
    [[ -e "${devpath}" ]] || continue
    basename "${devpath}"
  done | sort -V
}

get_uio_name_for_pci() {
  local pci="$1"
  local uio_dir="/sys/bus/pci/devices/${pci}/uio"

  if [[ ! -d "${uio_dir}" ]]; then
    echo ""
    return 0
  fi

  ls "${uio_dir}" 2>/dev/null | grep -E '^uio[0-9]+$' | sort -V | head -n1 || true
}

join_by_comma() {
  local IFS=','
  echo "$*"
}

ensure_hugepages_ready_for_container() {
  local total_pages

  total_pages="$(get_meminfo_value "HugePages_Total")"
  if [[ -z "${total_pages}" || "${total_pages}" -eq 0 ]]; then
    err "HugePages_Total is 0."
    err "Configure hugepages before starting the engine container."
    exit 27
  fi

  if [[ ! -d "/dev/hugepages" ]]; then
    err "/dev/hugepages was not found."
    err "Ensure hugetlbfs is mounted before starting the engine container."
    exit 28
  fi
}

collect_container_devices() {
  local pci
  local uio_name
  local uio_path

  CONTAINER_BOUND_PCIS=()
  CONTAINER_UIO_DEVICES=()

  while IFS= read -r pci; do
    [[ -z "${pci}" ]] && continue
    CONTAINER_BOUND_PCIS+=("${pci}")
  done < <(get_bound_igb_uio_pcis)

  if (( ${#CONTAINER_BOUND_PCIS[@]} == 0 )); then
    err "No NIC is currently bound to igb_uio."
    err "Bind at least one NIC with bind-nic before starting the engine container."
    exit 29
  fi

  if (( ${#CONTAINER_BOUND_PCIS[@]} > 2 )); then
    err "At most two NICs may be bound to igb_uio for engine container startup."
    err "Currently bound PCI devices: $(join_by_comma "${CONTAINER_BOUND_PCIS[@]}")"
    exit 30
  fi

  for pci in "${CONTAINER_BOUND_PCIS[@]}"; do
    uio_name="$(get_uio_name_for_pci "${pci}")"
    if [[ -z "${uio_name}" ]]; then
      err "No UIO device was found for PCI device: ${pci}"
      exit 31
    fi

    uio_path="/dev/${uio_name}"
    if [[ ! -e "${uio_path}" ]]; then
      err "Expected UIO device node was not found: ${uio_path}"
      exit 32
    fi

    CONTAINER_UIO_DEVICES+=("${uio_path}")
  done
}

prepare_container_tokens() {
  local generated_token=""

  if [[ -n "${CONTAINER_AGENT_TOKEN}" && -z "${CONTAINER_TOKEN}" ]]; then
    CONTAINER_TOKEN="${CONTAINER_AGENT_TOKEN}"
  fi

  if [[ -n "${CONTAINER_TOKEN}" && -z "${CONTAINER_AGENT_TOKEN}" ]]; then
    CONTAINER_AGENT_TOKEN="${CONTAINER_TOKEN}"
  fi

  if [[ -z "${CONTAINER_AGENT_TOKEN}" && -z "${CONTAINER_TOKEN}" ]]; then
    if ! have_cmd openssl; then
      err "OpenSSL was not found, so tokens cannot be generated automatically."
      err "Provide --agent-token and --token explicitly, or install openssl."
      print_install_hint_for_cmd "openssl"
      exit 33
    fi

    generated_token="$(openssl rand -hex 32)"
    CONTAINER_AGENT_TOKEN="${generated_token}"
    CONTAINER_TOKEN="${generated_token}"
  fi
}

docker_container_exists() {
  docker ps -a --filter "name=^/${CONTAINER_NAME}$" --format '{{.ID}}' | grep -q .
}

docker_container_running() {
  docker ps --filter "name=^/${CONTAINER_NAME}$" --format '{{.ID}}' | grep -q .
}

ensure_container_image_exists() {
  if ! docker image inspect "${CONTAINER_IMAGE}" >/dev/null 2>&1; then
    err "Docker image was not found locally: ${CONTAINER_IMAGE}"
    err "Pull it first, for example: docker pull ${CONTAINER_IMAGE}"
    exit 34
  fi
}

write_container_env_file() {
  local now_epoch
  local now_iso
  local old_umask

  now_epoch="$(date +%s)"
  now_iso="$(date '+%Y-%m-%d %H:%M:%S')"
  old_umask="$(umask)"
  umask 077

  cat > "${CONTAINER_ENV_FILE}" <<EOF
CONTAINER_NAME=${CONTAINER_NAME}
CONTAINER_IMAGE=${CONTAINER_IMAGE}
BOUND_PCIS=$(join_by_comma "${CONTAINER_BOUND_PCIS[@]}")
UIO_DEVICES=$(join_by_comma "${CONTAINER_UIO_DEVICES[@]}")
DPTEST_AGENT_TOKEN=${CONTAINER_AGENT_TOKEN}
TOKEN=${CONTAINER_TOKEN}
STARTED_AT_EPOCH=${now_epoch}
STARTED_AT_ISO=${now_iso}
EOF

  umask "${old_umask}"
}

print_saved_container_tokens() {
  local saved_agent_token=""
  local saved_token=""
  local saved_image=""

  if [[ ! -f "${CONTAINER_ENV_FILE}" ]]; then
    warn "Saved container token file was not found: ${CONTAINER_ENV_FILE}"
    return 0
  fi

  saved_agent_token="$(read_state_value "${CONTAINER_ENV_FILE}" "DPTEST_AGENT_TOKEN")"
  saved_token="$(read_state_value "${CONTAINER_ENV_FILE}" "TOKEN")"
  saved_image="$(read_state_value "${CONTAINER_ENV_FILE}" "CONTAINER_IMAGE")"

  echo "Container name: ${CONTAINER_NAME}"
  [[ -n "${saved_image}" ]] && echo "Container image: ${saved_image}"
  [[ -n "${saved_agent_token}" ]] && echo "DPTEST_AGENT_TOKEN=${saved_agent_token}"
  [[ -n "${saved_token}" ]] && echo "TOKEN=${saved_token}"
  echo "Saved token file: ${CONTAINER_ENV_FILE}"
}

start_engine_container() {
  local docker_args=()
  local device_path

  ensure_igb_uio_loaded
  ensure_hugepages_ready_for_container
  collect_container_devices

  if docker_container_exists; then
    if docker_container_running; then
      err "The engine container is already running: ${CONTAINER_NAME}"
      exit 35
    fi

    warn "Reusing existing stopped container: ${CONTAINER_NAME}"
    warn "Image and token arguments are ignored when restarting an existing container."
    docker start "${CONTAINER_NAME}"
    log "Engine container started successfully"
    print_saved_container_tokens
    return 0
  fi

  prepare_container_tokens
  ensure_container_image_exists

  mkdir -p /tmp/virtio
  write_container_env_file

  docker_args=(
    run
    -itd
    --name "${CONTAINER_NAME}"
    --network host
    --privileged
  )

  for device_path in "${CONTAINER_UIO_DEVICES[@]}"; do
    docker_args+=("--device=${device_path}:${device_path}")
  done

  docker_args+=(
    -v /dev/hugepages:/dev/hugepages
    -v /tmp/virtio:/tmp/virtio
    -v /etc/localtime:/etc/localtime:ro
    -e "DPTEST_AGENT_TOKEN=${CONTAINER_AGENT_TOKEN}"
    -e "TOKEN=${CONTAINER_TOKEN}"
    "${CONTAINER_IMAGE}"
  )

  log "Starting engine container: ${CONTAINER_NAME}"
  docker "${docker_args[@]}"

  log "Engine container started successfully"
  echo "Container name: ${CONTAINER_NAME}"
  echo "Container image: ${CONTAINER_IMAGE}"
  echo "Bound PCI devices: $(join_by_comma "${CONTAINER_BOUND_PCIS[@]}")"
  echo "Mapped UIO devices: $(join_by_comma "${CONTAINER_UIO_DEVICES[@]}")"
  echo "DPTEST_AGENT_TOKEN=${CONTAINER_AGENT_TOKEN}"
  echo "TOKEN=${CONTAINER_TOKEN}"
  echo "Saved token file: ${CONTAINER_ENV_FILE}"
}

stop_engine_container() {
  if ! docker_container_exists; then
    warn "No container with name ${CONTAINER_NAME} was found."
    return 0
  fi

  if docker_container_running; then
    log "Stopping engine container: ${CONTAINER_NAME}"
    docker stop "${CONTAINER_NAME}"
    log "Engine container stopped"
    log "The container definition was kept and can be started again with start-engine-container"
  else
    warn "Container exists but is not running: ${CONTAINER_NAME}"
  fi
}

clear_engine_container() {
  if ! docker_container_exists; then
    warn "No container with name ${CONTAINER_NAME} was found."
    return 0
  fi

  log "Removing engine container: ${CONTAINER_NAME}"
  docker rm -f "${CONTAINER_NAME}"
  log "Engine container removed"
}

resolve_target_runtime() {
  local target="$1"
  RESOLVED_PCI=""
  RESOLVED_IFNAME=""

  if is_pci_addr "${target}"; then
    if ! pci_exists "${target}"; then
      return 1
    fi
    RESOLVED_PCI="${target}"
    RESOLVED_IFNAME="$(get_ifname_from_pci "${target}")"
    return 0
  fi

  if ifname_exists "${target}"; then
    RESOLVED_IFNAME="${target}"
    RESOLVED_PCI="$(get_pci_from_ifname "${target}")"
    if [[ -z "${RESOLVED_PCI}" ]]; then
      return 1
    fi
    return 0
  fi

  return 1
}

resolve_target_with_state_fallback() {
  local target="$1"
  local state_file

  if resolve_target_runtime "${target}"; then
    return 0
  fi

  if ! is_pci_addr "${target}"; then
    state_file="$(find_state_file_by_ifname "${target}" || true)"
    if [[ -n "${state_file}" && -f "${state_file}" ]]; then
      RESOLVED_PCI="$(read_state_value "${state_file}" "PCI_ADDR")"
      RESOLVED_IFNAME="$(read_state_value "${state_file}" "INTERFACE_NAME")"
      if [[ -n "${RESOLVED_PCI}" ]]; then
        return 0
      fi
    fi
  fi

  return 1
}

get_operstate() {
  local ifname="$1"
  if [[ -n "${ifname}" && -f "/sys/class/net/${ifname}/operstate" ]]; then
    cat "/sys/class/net/${ifname}/operstate"
  else
    echo "N/A"
  fi
}

get_ip_list_nl() {
  local ifname="$1"
  if [[ -z "${ifname}" || ! -e "/sys/class/net/${ifname}" ]]; then
    return 0
  fi
  ip -o addr show dev "${ifname}" 2>/dev/null | awk '{print $4}'
}

get_ip_list_csv() {
  local ifname="$1"
  local nl
  nl="$(get_ip_list_nl "${ifname}")"
  echo "${nl}" | paste -sd, - | sed 's/^,$//'
}

get_route_list4_nl() {
  local ifname="$1"
  if [[ -z "${ifname}" || ! -e "/sys/class/net/${ifname}" ]]; then
    return 0
  fi
  ip -o route show dev "${ifname}" 2>/dev/null || true
}

get_route_list6_nl() {
  local ifname="$1"
  if [[ -z "${ifname}" || ! -e "/sys/class/net/${ifname}" ]]; then
    return 0
  fi
  ip -o -6 route show dev "${ifname}" 2>/dev/null || true
}

has_active_routes() {
  local ifname="$1"
  local r4
  local r6
  r4="$(get_route_list4_nl "${ifname}")"
  r6="$(get_route_list6_nl "${ifname}")"
  if [[ -n "${r4}" || -n "${r6}" ]]; then
    echo "true"
  else
    echo "false"
  fi
}

is_default_route_iface() {
  local ifname="$1"
  if [[ -z "${ifname}" ]]; then
    echo "false"
    return
  fi
  if ip route show default 2>/dev/null | grep -q " dev ${ifname}\b"; then
    echo "true"
    return
  fi
  if ip -6 route show default 2>/dev/null | grep -q " dev ${ifname}\b"; then
    echo "true"
    return
  fi
  echo "false"
}

is_ssh_management_candidate() {
  local ifname="$1"
  local client_ip=""
  local route_out=""

  if [[ -z "${ifname}" ]]; then
    echo "false"
    return
  fi

  if [[ -n "${SSH_CONNECTION:-}" ]]; then
    client_ip="$(echo "${SSH_CONNECTION}" | awk '{print $1}')"
  elif [[ -n "${SSH_CLIENT:-}" ]]; then
    client_ip="$(echo "${SSH_CLIENT}" | awk '{print $1}')"
  fi

  if [[ -z "${client_ip}" ]]; then
    echo "false"
    return
  fi

  route_out="$(ip route get "${client_ip}" 2>/dev/null || true)"
  if echo "${route_out}" | grep -q " dev ${ifname}\b"; then
    echo "true"
  else
    echo "false"
  fi
}

count_route_lines() {
  local ifname="$1"
  local count=0
  local r4
  local r6

  r4="$(get_route_list4_nl "${ifname}")"
  r6="$(get_route_list6_nl "${ifname}")"

  if [[ -n "${r4}" ]]; then
    count=$((count + $(echo "${r4}" | grep -c . || true)))
  fi
  if [[ -n "${r6}" ]]; then
    count=$((count + $(echo "${r6}" | grep -c . || true)))
  fi

  echo "${count}"
}

collect_assessment() {
  local target="$1"

  if ! resolve_target_runtime "${target}"; then
    err "Target could not be resolved to a valid PCI device or interface: ${target}"
    return 1
  fi

  ASSESS_TARGET_INPUT="${target}"
  ASSESS_PCI="${RESOLVED_PCI}"
  ASSESS_IFNAME="${RESOLVED_IFNAME}"
  ASSESS_DRIVER="$(get_current_driver "${ASSESS_PCI}")"
  ASSESS_OPERSTATE="$(get_operstate "${ASSESS_IFNAME}")"
  ASSESS_IPS_NL="$(get_ip_list_nl "${ASSESS_IFNAME}")"
  ASSESS_IPS_CSV="$(get_ip_list_csv "${ASSESS_IFNAME}")"
  ASSESS_ROUTES4_NL="$(get_route_list4_nl "${ASSESS_IFNAME}")"
  ASSESS_ROUTES6_NL="$(get_route_list6_nl "${ASSESS_IFNAME}")"
  ASSESS_ROUTE_COUNT="$(count_route_lines "${ASSESS_IFNAME}")"
  ASSESS_HAS_ACTIVE_ROUTES="$(has_active_routes "${ASSESS_IFNAME}")"
  ASSESS_DEFAULT_ROUTE="$(is_default_route_iface "${ASSESS_IFNAME}")"
  ASSESS_SSH_MGMT_CANDIDATE="$(is_ssh_management_candidate "${ASSESS_IFNAME}")"

  ASSESS_REQUIRES_CONFIRMATION="false"
  ASSESS_SAFE_TO_BIND="true"
  ASSESS_RISK_LEVEL="low"
  ASSESS_REASONS_NL=""

  if [[ "${ASSESS_DEFAULT_ROUTE}" == "true" ]]; then
    ASSESS_RISK_LEVEL="high"
    ASSESS_SAFE_TO_BIND="false"
    ASSESS_REQUIRES_CONFIRMATION="true"
    ASSESS_REASONS_NL="${ASSESS_REASONS_NL}"$'Interface carries a default route.\n'
  fi

  if [[ "${ASSESS_SSH_MGMT_CANDIDATE}" == "true" ]]; then
    ASSESS_RISK_LEVEL="high"
    ASSESS_SAFE_TO_BIND="false"
    ASSESS_REQUIRES_CONFIRMATION="true"
    ASSESS_REASONS_NL="${ASSESS_REASONS_NL}"$'Interface appears to be used by the current SSH management path.\n'
  fi

  if [[ "${ASSESS_HAS_ACTIVE_ROUTES}" == "true" ]]; then
    if [[ "${ASSESS_RISK_LEVEL}" != "high" ]]; then
      ASSESS_RISK_LEVEL="high"
    fi
    ASSESS_SAFE_TO_BIND="false"
    ASSESS_REQUIRES_CONFIRMATION="true"
    ASSESS_REASONS_NL="${ASSESS_REASONS_NL}"$'Interface still has active routes in the routing table.\n'
  fi

  if [[ -n "${ASSESS_IPS_CSV}" ]]; then
    if [[ "${ASSESS_RISK_LEVEL}" == "low" ]]; then
      ASSESS_RISK_LEVEL="medium"
    fi
    ASSESS_SAFE_TO_BIND="false"
    ASSESS_REQUIRES_CONFIRMATION="true"
    ASSESS_REASONS_NL="${ASSESS_REASONS_NL}"$'Interface still has IP addresses assigned.\n'
  fi

  if [[ "${ASSESS_OPERSTATE}" == "up" || "${ASSESS_OPERSTATE}" == "unknown" ]]; then
    if [[ "${ASSESS_RISK_LEVEL}" == "low" ]]; then
      ASSESS_RISK_LEVEL="medium"
    fi
    ASSESS_SAFE_TO_BIND="false"
    ASSESS_REQUIRES_CONFIRMATION="true"
    ASSESS_REASONS_NL="${ASSESS_REASONS_NL}"$'Interface is not clearly inactive.\n'
  fi

  if [[ -z "${ASSESS_IFNAME}" ]]; then
    ASSESS_REASONS_NL="${ASSESS_REASONS_NL}"$'No Linux interface name is currently associated with this PCI device.\n'
  fi

  return 0
}

print_assessment_human() {
  echo "Target input: ${ASSESS_TARGET_INPUT}"
  echo "Resolved PCI: ${ASSESS_PCI}"
  echo "Resolved interface: ${ASSESS_IFNAME:-<none>}"
  echo "Current driver: ${ASSESS_DRIVER:-<none>}"
  echo "Interface operstate: ${ASSESS_OPERSTATE}"
  echo "IP addresses: ${ASSESS_IPS_CSV:-<none>}"
  echo "Route count: ${ASSESS_ROUTE_COUNT}"
  echo "Has active routes: ${ASSESS_HAS_ACTIVE_ROUTES}"
  echo "Default route interface: ${ASSESS_DEFAULT_ROUTE}"
  echo "SSH management candidate: ${ASSESS_SSH_MGMT_CANDIDATE}"
  echo "Risk level: ${ASSESS_RISK_LEVEL}"
  echo "Safe to bind directly: ${ASSESS_SAFE_TO_BIND}"
  echo "Requires confirmation: ${ASSESS_REQUIRES_CONFIRMATION}"
  echo "Reasons:"
  if [[ -n "${ASSESS_REASONS_NL}" ]]; then
    while IFS= read -r line; do
      [[ -z "${line}" ]] && continue
      echo "  - ${line}"
    done <<< "${ASSESS_REASONS_NL}"
  else
    echo "  - No significant risk indicators were detected."
  fi
  echo "IPv4 routes:"
  if [[ -n "${ASSESS_ROUTES4_NL}" ]]; then
    while IFS= read -r line; do
      [[ -z "${line}" ]] && continue
      echo "  - ${line}"
    done <<< "${ASSESS_ROUTES4_NL}"
  else
    echo "  - <none>"
  fi
  echo "IPv6 routes:"
  if [[ -n "${ASSESS_ROUTES6_NL}" ]]; then
    while IFS= read -r line; do
      [[ -z "${line}" ]] && continue
      echo "  - ${line}"
    done <<< "${ASSESS_ROUTES6_NL}"
  else
    echo "  - <none>"
  fi
}

json_escape() {
  printf '%s' "$1" | sed ':a;N;$!ba;s/\\/\\\\/g;s/"/\\"/g;s/\n/\\n/g'
}

json_string() {
  printf '"%s"' "$(json_escape "$1")"
}

json_bool() {
  if [[ "$1" == "true" ]]; then
    printf 'true'
  else
    printf 'false'
  fi
}

json_string_or_null() {
  if [[ -n "$1" ]]; then
    json_string "$1"
  else
    printf 'null'
  fi
}

json_array_from_nl() {
  local input="$1"
  local first="true"
  local line
  printf '['
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    if [[ "${first}" == "true" ]]; then
      first="false"
    else
      printf ','
    fi
    json_string "${line}"
  done <<< "${input}"
  printf ']'
}

print_assessment_json() {
  printf '{'
  printf '"target_input":'; json_string "${ASSESS_TARGET_INPUT}"; printf ','
  printf '"resolved_pci":'; json_string "${ASSESS_PCI}"; printf ','
  printf '"resolved_ifname":'; json_string_or_null "${ASSESS_IFNAME}"; printf ','
  printf '"current_driver":'; json_string_or_null "${ASSESS_DRIVER}"; printf ','
  printf '"operstate":'; json_string "${ASSESS_OPERSTATE}"; printf ','
  printf '"ip_addresses":'; json_array_from_nl "${ASSESS_IPS_NL}"; printf ','
  printf '"ipv4_routes":'; json_array_from_nl "${ASSESS_ROUTES4_NL}"; printf ','
  printf '"ipv6_routes":'; json_array_from_nl "${ASSESS_ROUTES6_NL}"; printf ','
  printf '"route_count":%s,' "${ASSESS_ROUTE_COUNT}"
  printf '"has_active_routes":'; json_bool "${ASSESS_HAS_ACTIVE_ROUTES}"; printf ','
  printf '"default_route_interface":'; json_bool "${ASSESS_DEFAULT_ROUTE}"; printf ','
  printf '"ssh_management_candidate":'; json_bool "${ASSESS_SSH_MGMT_CANDIDATE}"; printf ','
  printf '"risk_level":'; json_string "${ASSESS_RISK_LEVEL}"; printf ','
  printf '"safe_to_bind":'; json_bool "${ASSESS_SAFE_TO_BIND}"; printf ','
  printf '"requires_confirmation":'; json_bool "${ASSESS_REQUIRES_CONFIRMATION}"; printf ','
  printf '"reasons":'; json_array_from_nl "${ASSESS_REASONS_NL}"
  printf '}'
}

bring_interface_down_and_clear() {
  local ifname="$1"

  if [[ -z "${ifname}" ]]; then
    log "No Linux interface name is associated with this PCI device. Skipping interface shutdown and route cleanup."
    return 0
  fi

  if [[ ! -e "/sys/class/net/${ifname}" ]]; then
    warn "Interface does not exist in /sys/class/net anymore: ${ifname}"
    return 0
  fi

  log "Bringing interface down: ${ifname}"
  ip link set dev "${ifname}" down || true

  log "Flushing IP addresses from interface: ${ifname}"
  ip addr flush dev "${ifname}" || true

  log "Flushing IPv4 routes for interface: ${ifname}"
  ip route flush dev "${ifname}" || true

  log "Flushing IPv6 routes for interface: ${ifname}"
  ip -6 route flush dev "${ifname}" || true
}

bind_one_target() {
  local target="$1"
  local py
  local devbind
  local now_epoch
  local now_iso
  local state_file

  py="$(get_python_cmd)"
  devbind="$(find_devbind)"

  if ! collect_assessment "${target}"; then
    exit 12
  fi

  if [[ "${ASSESS_DRIVER}" == "igb_uio" ]]; then
    warn "Target is already bound to igb_uio: ${target}"
    return 0
  fi

  if [[ "${ASSESS_REQUIRES_CONFIRMATION}" == "true" && "${CONFIRM}" != "true" ]]; then
    print_assessment_human
    err "Confirmation is required for this bind operation."
    err "Re-run the bind-nic command with --confirm if you want to proceed."
    exit 13
  fi

  now_epoch="$(date +%s)"
  now_iso="$(date '+%Y-%m-%d %H:%M:%S')"
  write_state_file \
    "${ASSESS_PCI}" \
    "${ASSESS_IFNAME}" \
    "${ASSESS_DRIVER}" \
    "${ASSESS_OPERSTATE}" \
    "${ASSESS_IPS_CSV}" \
    "${ASSESS_ROUTE_COUNT}" \
    "${ASSESS_DEFAULT_ROUTE}" \
    "${ASSESS_SSH_MGMT_CANDIDATE}" \
    "${now_epoch}" \
    "${now_iso}"

  state_file="$(state_file_for_pci "${ASSESS_PCI}")"

  append_journal "bind_prepare" "${ASSESS_PCI}" "${ASSESS_DRIVER}" "igb_uio"

  bring_interface_down_and_clear "${ASSESS_IFNAME}"

  log "Binding PCI device to igb_uio: ${ASSESS_PCI}"
  log "Original driver recorded as: ${ASSESS_DRIVER:-<none>}"

  if ! "${py}" "${devbind}" --bind=igb_uio "${ASSESS_PCI}"; then
    append_journal "bind_failed" "${ASSESS_PCI}" "${ASSESS_DRIVER}" "igb_uio"
    rm -f "${state_file}"
    err "Failed to bind PCI device to igb_uio: ${ASSESS_PCI}"
    exit 14
  fi

  sleep 2

  if [[ "$(get_current_driver "${ASSESS_PCI}")" != "igb_uio" ]]; then
    append_journal "bind_failed_verify" "${ASSESS_PCI}" "${ASSESS_DRIVER}" "igb_uio"
    rm -f "${state_file}"
    err "Binding verification failed for PCI device: ${ASSESS_PCI}"
    exit 15
  fi

  append_journal "bind" "${ASSESS_PCI}" "${ASSESS_DRIVER}" "igb_uio"
  log "Binding successful: ${ASSESS_PCI} -> igb_uio"
}

unbind_one_target() {
  local target="$1"
  local py
  local devbind
  local pci
  local ifname
  local state_file
  local orig_driver
  local current_driver

  py="$(get_python_cmd)"
  devbind="$(find_devbind)"

  if ! resolve_target_with_state_fallback "${target}"; then
    err "Target could not be resolved for unbind: ${target}"
    exit 16
  fi

  pci="${RESOLVED_PCI}"
  ifname="${RESOLVED_IFNAME}"
  state_file="$(state_file_for_pci "${pci}")"

  if [[ ! -f "${state_file}" ]]; then
    err "No recorded bind state was found for target: ${target}"
    err "This script can only restore devices that were previously bound with recorded state."
    exit 17
  fi

  orig_driver="$(read_state_value "${state_file}" "ORIGINAL_DRIVER")"
  current_driver="$(get_current_driver "${pci}")"

  if [[ "${current_driver}" != "igb_uio" ]]; then
    warn "Target is not currently bound to igb_uio."
    warn "PCI: ${pci}"
    warn "Current driver: ${current_driver:-<none>}"
  fi

  if [[ -n "${orig_driver}" ]]; then
    log "Restoring PCI device to original driver: ${pci} -> ${orig_driver}"
    modprobe "${orig_driver}" || true
    "${py}" "${devbind}" --bind="${orig_driver}" "${pci}"
    append_journal "unbind" "${pci}" "igb_uio" "${orig_driver}"
  else
    log "No original driver was recorded. Unbinding PCI device from current driver: ${pci}"
    "${py}" "${devbind}" --unbind "${pci}"
    append_journal "unbind" "${pci}" "igb_uio" "<none>"
  fi

  rm -f "${state_file}"

  log "Unbind/restore operation completed for PCI: ${pci}"
  if [[ -n "${ifname}" ]]; then
    log "Recorded interface name: ${ifname}"
  fi
}

rollback_all_bound_nics() {
  local f
  local pci
  local state_epoch
  local current_driver
  local candidates=()
  local entry
  local restored_count=0

  shopt -s nullglob
  for f in "${STATE_DIR}"/*.state; do
    pci="$(read_state_value "${f}" "PCI_ADDR")"
    state_epoch="$(read_state_value "${f}" "BOUND_AT_EPOCH")"
    current_driver="$(get_current_driver "${pci}")"

    if [[ "${current_driver}" == "igb_uio" ]]; then
      if [[ -z "${state_epoch}" ]]; then
        state_epoch="0"
      fi
      candidates+=("${state_epoch}|${pci}")
    fi
  done
  shopt -u nullglob

  if (( ${#candidates[@]} == 0 )); then
    err "No rollback candidates were found."
    err "There are no recorded PCI devices currently bound to igb_uio."
    exit 18
  fi

  while IFS= read -r entry; do
    [[ -n "${entry}" ]] || continue
    pci="${entry#*|}"
    log "Rolling back bound PCI device: ${pci}"
    unbind_one_target "${pci}"
    restored_count=$((restored_count + 1))
  done < <(printf '%s\n' "${candidates[@]}" | sort -t'|' -k1,1nr -k2,2)

  log "Rolled back ${restored_count} NIC binding(s)"
}


get_node_names() {
  local d
  local names=()

  for d in /sys/devices/system/node/node[0-9]*; do
    [[ -d "${d}" ]] || continue
    names+=("$(basename "${d}")")
  done

  if (( ${#names[@]} == 0 )); then
    echo "global"
  else
    printf '%s
' "${names[@]}" | sort -V
  fi
}

get_hugepage_sizes_kb() {
  local base=""
  local d

  if ls /sys/devices/system/node/node0/hugepages/hugepages-*kB >/dev/null 2>&1; then
    base="/sys/devices/system/node/node0/hugepages"
  else
    base="/sys/kernel/mm/hugepages"
  fi

  for d in "${base}"/hugepages-*kB; do
    [[ -d "${d}" ]] || continue
    basename "${d}" | sed -E 's/^hugepages-([0-9]+)kB$/\1/'
  done | sort -n
}

get_hugepage_file_path() {
  local node_name="$1"
  local size_kb="$2"
  local leaf="$3"

  if [[ "${node_name}" == "global" ]]; then
    echo "/sys/kernel/mm/hugepages/hugepages-${size_kb}kB/${leaf}"
  else
    echo "/sys/devices/system/node/${node_name}/hugepages/hugepages-${size_kb}kB/${leaf}"
  fi
}

get_hugepage_value() {
  local node_name="$1"
  local size_kb="$2"
  local leaf="$3"
  local path

  path="$(get_hugepage_file_path "${node_name}" "${size_kb}" "${leaf}")"
  if [[ -f "${path}" ]]; then
    cat "${path}"
  else
    echo "0"
  fi
}

set_hugepage_value() {
  local node_name="$1"
  local size_kb="$2"
  local leaf="$3"
  local value="$4"
  local path

  path="$(get_hugepage_file_path "${node_name}" "${size_kb}" "${leaf}")"
  if [[ ! -f "${path}" ]]; then
    err "Hugepage sysfs path was not found: ${path}"
    exit 19
  fi

  echo "${value}" > "${path}"
}

get_node_memtotal_kb() {
  local node_name="$1"
  if [[ "${node_name}" == "global" ]]; then
    awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo
  else
    awk '/MemTotal/ {print $(NF-1); exit}' "/sys/devices/system/node/${node_name}/meminfo"
  fi
}

format_kb_human() {
  local kb="$1"
  if [[ -z "${kb}" ]]; then
    echo "0 kB"
    return
  fi

  if (( kb % 1048576 == 0 )); then
    echo "$((kb / 1048576)) GB"
  elif (( kb % 1024 == 0 )); then
    echo "$((kb / 1024)) MB"
  else
    echo "${kb} kB"
  fi
}

parse_size_to_kb() {
  local raw="$1"
  local up
  up="$(echo "${raw}" | tr '[:lower:]' '[:upper:]')"

  if [[ "${up}" =~ ^([0-9]+)(KB|K)$ ]]; then
    echo "${BASH_REMATCH[1]}"
  elif [[ "${up}" =~ ^([0-9]+)(MB|M)$ ]]; then
    echo "$(( ${BASH_REMATCH[1]} * 1024 ))"
  elif [[ "${up}" =~ ^([0-9]+)(GB|G)$ ]]; then
    echo "$(( ${BASH_REMATCH[1]} * 1024 * 1024 ))"
  elif [[ "${up}" =~ ^([0-9]+)$ ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo ""
  fi
}

get_default_hugepage_size_kb() {
  awk '/^Hugepagesize:/ {print $2; exit}' /proc/meminfo
}

get_hugetlbfs_mount_page_size_kb() {
  local raw
  raw="$(awk '$3=="hugetlbfs" {print $4}' /proc/mounts 2>/dev/null | tr ',' '\n' | awk -F= '$1=="pagesize" {print $2; exit}')"
  if [[ -z "${raw}" ]]; then
    echo ""
    return
  fi
  parse_size_to_kb "${raw}"
}

is_supported_hugepage_size_kb() {
  local size_kb="$1"
  local s
  while IFS= read -r s; do
    [[ -z "${s}" ]] && continue
    if [[ "${s}" == "${size_kb}" ]]; then
      return 0
    fi
  done < <(get_hugepage_sizes_kb)
  return 1
}

sum_hugepages_for_size_kb() {
  local size_kb="$1"
  local total=0
  local node_name
  local value
  while IFS= read -r node_name; do
    [[ -z "${node_name}" ]] && continue
    value="$(get_hugepage_value "${node_name}" "${size_kb}" nr_hugepages)"
    total=$(( total + value ))
  done < <(get_node_names)
  echo "${total}"
}

detect_hugepage_size_kb() {
  if [[ -n "${HUGEPAGES_SIZE_KB}" ]]; then
    if is_supported_hugepage_size_kb "${HUGEPAGES_SIZE_KB}"; then
      echo "${HUGEPAGES_SIZE_KB}"
      return 0
    fi
    err "Requested hugepage size is not supported on this system: ${HUGEPAGES_SIZE_KB} kB"
    exit 20
  fi

  local active_sizes=()
  local s
  local total
  while IFS= read -r s; do
    [[ -z "${s}" ]] && continue
    total="$(sum_hugepages_for_size_kb "${s}")"
    if (( total > 0 )); then
      active_sizes+=("${s}")
    fi
  done < <(get_hugepage_sizes_kb)

  if (( ${#active_sizes[@]} == 1 )); then
    echo "${active_sizes[0]}"
    return 0
  fi

  local mount_size
  mount_size="$(get_hugetlbfs_mount_page_size_kb)"
  if [[ -n "${mount_size}" ]] && is_supported_hugepage_size_kb "${mount_size}"; then
    echo "${mount_size}"
    return 0
  fi

  local default_size
  default_size="$(get_default_hugepage_size_kb)"
  if [[ -n "${default_size}" ]] && is_supported_hugepage_size_kb "${default_size}"; then
    echo "${default_size}"
    return 0
  fi

  local sizes=()
  while IFS= read -r s; do
    [[ -z "${s}" ]] && continue
    sizes+=("${s}")
  done < <(get_hugepage_sizes_kb)

  if (( ${#sizes[@]} == 1 )); then
    echo "${sizes[0]}"
    return 0
  fi

  err "Unable to determine the active hugepage size automatically. Use --size-kb explicitly."
  exit 21
}

get_target_pages_for_node() {
  local node_name="$1"
  local size_kb="$2"
  local memtotal_kb

  if [[ -n "${HUGEPAGES_PAGES_PER_NODE}" ]]; then
    echo "${HUGEPAGES_PAGES_PER_NODE}"
    return 0
  fi

  memtotal_kb="$(get_node_memtotal_kb "${node_name}")"
  echo $(( (memtotal_kb * 3 / 5) / size_kb ))
}

snapshot_hugepages_state() {
  ensure_state_dirs

  local now_epoch
  local now_iso
  local node_names=()
  local size_list=()
  local node_name
  local size_kb
  local nodes_csv
  local sizes_csv

  now_epoch="$(date +%s)"
  now_iso="$(date '+%Y-%m-%d %H:%M:%S')"

  while IFS= read -r node_name; do
    [[ -z "${node_name}" ]] && continue
    node_names+=("${node_name}")
  done < <(get_node_names)

  while IFS= read -r size_kb; do
    [[ -z "${size_kb}" ]] && continue
    size_list+=("${size_kb}")
  done < <(get_hugepage_sizes_kb)

  nodes_csv="$(printf '%s,' "${node_names[@]}" | sed 's/,$//')"
  sizes_csv="$(printf '%s,' "${size_list[@]}" | sed 's/,$//')"

  {
    echo "SNAPSHOT_AT_EPOCH=${now_epoch}"
    echo "SNAPSHOT_AT_ISO=${now_iso}"
    echo "NODE_LIST=${nodes_csv}"
    echo "SIZE_LIST=${sizes_csv}"
    for node_name in "${node_names[@]}"; do
      for size_kb in "${size_list[@]}"; do
        echo "HP_${size_kb}_${node_name}=$(get_hugepage_value "${node_name}" "${size_kb}" nr_hugepages)"
      done
    done
  } > "${HUGEPAGES_STATE_FILE}"
}

assess_hugepages_collect() {
  HP_ASSESS_SIZE_KB="$(detect_hugepage_size_kb)"
  HP_ASSESS_NODE_NAMES_NL="$(get_node_names)"
  HP_ASSESS_AVAILABLE_SIZES_NL="$(get_hugepage_sizes_kb)"
  HP_ASSESS_DEFAULT_SIZE_KB="$(get_default_hugepage_size_kb)"
  HP_ASSESS_MOUNT_SIZE_KB="$(get_hugetlbfs_mount_page_size_kb)"
}

print_hugepages_assessment_human() {
  local node_name
  local memtotal_kb
  local current_pages
  local target_pages
  local current_mem_kb
  local target_mem_kb

  echo "Detected hugepage size: ${HP_ASSESS_SIZE_KB} kB ($(format_kb_human "${HP_ASSESS_SIZE_KB}"))"
  echo "Default hugepage size from /proc/meminfo: ${HP_ASSESS_DEFAULT_SIZE_KB:-<none>} kB"
  echo "HugeTLBFS mount page size: ${HP_ASSESS_MOUNT_SIZE_KB:-<none>} kB"
  echo "Available hugepage sizes:"
  while IFS= read -r node_name; do
    [[ -z "${node_name}" ]] && continue
    echo "  - ${node_name}"
  done <<< "$(echo "${HP_ASSESS_AVAILABLE_SIZES_NL}" | awk '{print $0 " kB"}')"

  echo "Node assessment:"
  while IFS= read -r node_name; do
    [[ -z "${node_name}" ]] && continue
    memtotal_kb="$(get_node_memtotal_kb "${node_name}")"
    current_pages="$(get_hugepage_value "${node_name}" "${HP_ASSESS_SIZE_KB}" nr_hugepages)"
    target_pages="$(get_target_pages_for_node "${node_name}" "${HP_ASSESS_SIZE_KB}")"
    current_mem_kb=$(( current_pages * HP_ASSESS_SIZE_KB ))
    target_mem_kb=$(( target_pages * HP_ASSESS_SIZE_KB ))
    echo "  - Node: ${node_name}"
    echo "    MemTotal: ${memtotal_kb} kB ($(format_kb_human "${memtotal_kb}"))"
    echo "    Current pages: ${current_pages}"
    echo "    Current reserved memory: $(format_kb_human "${current_mem_kb}")"
    echo "    Target pages: ${target_pages}"
    echo "    Target reserved memory: $(format_kb_human "${target_mem_kb}")"
    if [[ -z "${HUGEPAGES_PAGES_PER_NODE}" ]]; then
      echo "    Target basis: three-fifths of node memory"
    else
      echo "    Target basis: explicit --pages-per-node value"
    fi
  done <<< "${HP_ASSESS_NODE_NAMES_NL}"
}

print_hugepages_assessment_json() {
  local node_name
  local first="true"
  local memtotal_kb
  local current_pages
  local target_pages

  printf '{'
  printf '"detected_size_kb":%s,' "${HP_ASSESS_SIZE_KB}"
  printf '"detected_size_human":'; json_string "$(format_kb_human "${HP_ASSESS_SIZE_KB}")"; printf ','
  printf '"default_size_kb":'; if [[ -n "${HP_ASSESS_DEFAULT_SIZE_KB}" ]]; then printf '%s' "${HP_ASSESS_DEFAULT_SIZE_KB}"; else printf 'null'; fi; printf ','
  printf '"mount_size_kb":'; if [[ -n "${HP_ASSESS_MOUNT_SIZE_KB}" ]]; then printf '%s' "${HP_ASSESS_MOUNT_SIZE_KB}"; else printf 'null'; fi; printf ','
  printf '"available_sizes_kb":'; json_array_from_nl "${HP_ASSESS_AVAILABLE_SIZES_NL}"; printf ','
  printf '"nodes":['
  while IFS= read -r node_name; do
    [[ -z "${node_name}" ]] && continue
    memtotal_kb="$(get_node_memtotal_kb "${node_name}")"
    current_pages="$(get_hugepage_value "${node_name}" "${HP_ASSESS_SIZE_KB}" nr_hugepages)"
    target_pages="$(get_target_pages_for_node "${node_name}" "${HP_ASSESS_SIZE_KB}")"
    if [[ "${first}" == "true" ]]; then
      first="false"
    else
      printf ','
    fi
    printf '{'
    printf '"node":'; json_string "${node_name}"; printf ','
    printf '"memtotal_kb":%s,' "${memtotal_kb}"
    printf '"current_pages":%s,' "${current_pages}"
    printf '"target_pages":%s' "${target_pages}"
    printf '}'
  done <<< "${HP_ASSESS_NODE_NAMES_NL}"
  printf ']'
  printf '}'
}

set_hugepages() {
  local size_kb
  local node_name
  local target_pages
  local verify_pages

  size_kb="$(detect_hugepage_size_kb)"
  snapshot_hugepages_state

  log "Using hugepage size: ${size_kb} kB ($(format_kb_human "${size_kb}"))"

  while IFS= read -r node_name; do
    [[ -z "${node_name}" ]] && continue
    target_pages="$(get_target_pages_for_node "${node_name}" "${size_kb}")"
    log "Setting hugepages for ${node_name}: ${target_pages} pages of size ${size_kb} kB"
    set_hugepage_value "${node_name}" "${size_kb}" nr_hugepages "${target_pages}"
  done < <(get_node_names)

  sleep 2

  while IFS= read -r node_name; do
    [[ -z "${node_name}" ]] && continue
    target_pages="$(get_target_pages_for_node "${node_name}" "${size_kb}")"
    verify_pages="$(get_hugepage_value "${node_name}" "${size_kb}" nr_hugepages)"
    if [[ "${verify_pages}" != "${target_pages}" ]]; then
      err "Hugepage configuration verification failed for ${node_name}."
      err "Expected ${target_pages} pages, got ${verify_pages}."
      err "You can restore the previous configuration with: ${SCRIPT_NAME} rollback-hugepages"
      exit 22
    fi
  done < <(get_node_names)

  append_journal "hugepages_set" "size=${size_kb}" "snapshot=${HUGEPAGES_STATE_FILE}" "pages_per_node=${HUGEPAGES_PAGES_PER_NODE:-auto_3_5}"
  log "Hugepage configuration completed successfully"
}

rollback_hugepages() {
  local node_list
  local size_list
  local node_name
  local size_kb
  local target_value
  local verify_value
  local IFS_OLD="$IFS"

  if [[ ! -f "${HUGEPAGES_STATE_FILE}" ]]; then
    err "No hugepage snapshot file was found: ${HUGEPAGES_STATE_FILE}"
    exit 23
  fi

  node_list="$(read_state_value "${HUGEPAGES_STATE_FILE}" "NODE_LIST")"
  size_list="$(read_state_value "${HUGEPAGES_STATE_FILE}" "SIZE_LIST")"

  IFS=','
  for node_name in ${node_list}; do
    [[ -z "${node_name}" ]] && continue
    for size_kb in ${size_list}; do
      [[ -z "${size_kb}" ]] && continue
      target_value="$(read_state_value "${HUGEPAGES_STATE_FILE}" "HP_${size_kb}_${node_name}")"
      if [[ -z "${target_value}" ]]; then
        target_value="0"
      fi
      log "Restoring hugepages for ${node_name}, size ${size_kb} kB: ${target_value}"
      set_hugepage_value "${node_name}" "${size_kb}" nr_hugepages "${target_value}"
    done
  done
  IFS="$IFS_OLD"

  sleep 2

  IFS=','
  for node_name in ${node_list}; do
    [[ -z "${node_name}" ]] && continue
    for size_kb in ${size_list}; do
      [[ -z "${size_kb}" ]] && continue
      target_value="$(read_state_value "${HUGEPAGES_STATE_FILE}" "HP_${size_kb}_${node_name}")"
      if [[ -z "${target_value}" ]]; then
        target_value="0"
      fi
      verify_value="$(get_hugepage_value "${node_name}" "${size_kb}" nr_hugepages)"
      if [[ "${verify_value}" != "${target_value}" ]]; then
        err "Hugepage rollback verification failed for ${node_name}, size ${size_kb} kB."
        err "Expected ${target_value}, got ${verify_value}."
        exit 24
      fi
    done
  done
  IFS="$IFS_OLD"

  append_journal "hugepages_rollback" "snapshot=${HUGEPAGES_STATE_FILE}" "from=last" "to=restored"
  log "Hugepage rollback completed successfully"
}


print_section_header() {
  local title="$1"
  echo
  echo "========== ${title} =========="
}

safe_cat_first_line() {
  local file_path="$1"
  if [[ -f "${file_path}" ]]; then
    head -n1 "${file_path}"
  else
    echo ""
  fi
}

show_igb_uio_status() {
  print_section_header "igb_uio status"

  local loaded="no"
  local module_line=""
  local module_file="/lib/modules/${KVER}/extra/igb_uio.ko"

  if is_module_loaded "igb_uio"; then
    loaded="yes"
    module_line="$(grep '^igb_uio[[:space:]]' /proc/modules 2>/dev/null || true)"
  fi

  echo "Kernel version: ${KVER}"
  echo "igb_uio loaded: ${loaded}"
  echo "uio loaded: $(is_module_loaded 'uio' && echo yes || echo no)"

  if [[ -n "${module_line}" ]]; then
    echo "Loaded module line: ${module_line}"
  fi

  if [[ -f "${module_file}" ]]; then
    echo "Installed module file: ${module_file}"
    if have_cmd modinfo; then
      modinfo "${module_file}" | grep -E '^(filename|name|vermagic|version):' || true
    fi
  else
    echo "Installed module file: <not found at ${module_file}>"
  fi

  if [[ -f "${JOURNAL_FILE}" ]]; then
    echo "Journal file: ${JOURNAL_FILE}"
    tail -n 5 "${JOURNAL_FILE}" 2>/dev/null || true
  else
    echo "Journal file: <not found>"
  fi
}

show_nics_status() {
  print_section_header "NIC binding status"

  local ifname
  local pci
  local driver
  local state
  local ips
  local route_count
  local dpdk_bound
  local seen_pcis=" "

  printf '%-16s %-14s %-16s %-10s %-8s %-6s %s\n' "Interface" "PCI" "Driver" "OperState" "DPDK" "Routes" "IP addresses"
  printf '%-16s %-14s %-16s %-10s %-8s %-6s %s\n' "--------" "---" "------" "---------" "----" "------" "------------"

  for ifname in $(ls /sys/class/net 2>/dev/null | sort); do
    [[ "${ifname}" == "lo" ]] && continue
    pci="$(get_pci_from_ifname "${ifname}")"
    if [[ -z "${pci}" ]]; then
      continue
    fi
    driver="$(get_current_driver "${pci}")"
    state="$(get_operstate "${ifname}")"
    ips="$(get_ip_list_csv "${ifname}")"
    route_count="$(count_route_lines "${ifname}")"
    if [[ "${driver}" == "igb_uio" ]]; then
      dpdk_bound="yes"
    else
      dpdk_bound="no"
    fi
    [[ -z "${ips}" ]] && ips="<none>"
    printf '%-16s %-14s %-16s %-10s %-8s %-6s %s\n' "${ifname}" "${pci}" "${driver:-<none>}" "${state}" "${dpdk_bound}" "${route_count}" "${ips}"
    seen_pcis+="${pci} "
  done

  local devpath
  for devpath in /sys/bus/pci/drivers/igb_uio/*:*; do
    [[ -e "${devpath}" ]] || continue
    pci="$(basename "${devpath}")"
    if [[ " ${seen_pcis} " == *" ${pci} "* ]]; then
      continue
    fi
    printf '%-16s %-14s %-16s %-10s %-8s %-6s %s\n' "<none>" "${pci}" "igb_uio" "N/A" "yes" "0" "<none>"
  done

  echo
  echo "Recorded bind state files:"
  if compgen -G "${STATE_DIR}/*.state" >/dev/null 2>&1; then
    ls -1 "${STATE_DIR}"/*.state 2>/dev/null
  else
    echo "<none>"
  fi
}

show_hugepages_status() {
  print_section_header "Hugepages status"

  local hp_total hp_free hp_rsvd hp_surp hp_size_kb
  hp_total="$(awk '/^HugePages_Total:/ {print $2; exit}' /proc/meminfo)"
  hp_free="$(awk '/^HugePages_Free:/ {print $2; exit}' /proc/meminfo)"
  hp_rsvd="$(awk '/^HugePages_Rsvd:/ {print $2; exit}' /proc/meminfo)"
  hp_surp="$(awk '/^HugePages_Surp:/ {print $2; exit}' /proc/meminfo)"
  hp_size_kb="$(awk '/^Hugepagesize:/ {print $2; exit}' /proc/meminfo)"

  echo "HugePages_Total: ${hp_total:-0}"
  echo "HugePages_Free:  ${hp_free:-0}"
  echo "HugePages_Rsvd:  ${hp_rsvd:-0}"
  echo "HugePages_Surp:  ${hp_surp:-0}"
  echo "Hugepagesize:    ${hp_size_kb:-0} kB ($(format_kb_human "${hp_size_kb:-0}"))"

  local size_kb
  local node_name
  local current_pages
  local free_pages
  local resv_pages
  local total_mem_kb

  echo
  echo "Per-node hugepage configuration:"
  while IFS= read -r size_kb; do
    [[ -z "${size_kb}" ]] && continue
    echo "  Size ${size_kb} kB ($(format_kb_human "${size_kb}"))"
    while IFS= read -r node_name; do
      [[ -z "${node_name}" ]] && continue
      current_pages="$(get_hugepage_value "${node_name}" "${size_kb}" nr_hugepages)"
      free_pages="$(get_hugepage_value "${node_name}" "${size_kb}" free_hugepages)"
      resv_pages="$(get_hugepage_value "${node_name}" "${size_kb}" resv_hugepages)"
      total_mem_kb=$(( current_pages * size_kb ))
      echo "    - Node: ${node_name}, current=${current_pages}, free=${free_pages}, reserved=${resv_pages}, reserved_memory=$(format_kb_human "${total_mem_kb}")"
    done < <(get_node_names)
  done < <(get_hugepage_sizes_kb)

  if [[ -f "${HUGEPAGES_STATE_FILE}" ]]; then
    echo
    echo "Hugepage rollback snapshot: ${HUGEPAGES_STATE_FILE}"
    grep -E '^(SNAPSHOT_AT_ISO|NODE_LIST|SIZE_LIST)=' "${HUGEPAGES_STATE_FILE}" || true
  else
    echo
    echo "Hugepage rollback snapshot: <not found>"
  fi
}

show_memory_status() {
  print_section_header "System memory status"

  local mem_total mem_free mem_available buffers cached swap_total swap_free
  mem_total="$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo)"
  mem_free="$(awk '/^MemFree:/ {print $2; exit}' /proc/meminfo)"
  mem_available="$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo)"
  buffers="$(awk '/^Buffers:/ {print $2; exit}' /proc/meminfo)"
  cached="$(awk '/^Cached:/ {print $2; exit}' /proc/meminfo)"
  swap_total="$(awk '/^SwapTotal:/ {print $2; exit}' /proc/meminfo)"
  swap_free="$(awk '/^SwapFree:/ {print $2; exit}' /proc/meminfo)"

  echo "MemTotal:      ${mem_total:-0} kB ($(format_kb_human "${mem_total:-0}"))"
  echo "MemFree:       ${mem_free:-0} kB ($(format_kb_human "${mem_free:-0}"))"
  echo "MemAvailable:  ${mem_available:-0} kB ($(format_kb_human "${mem_available:-0}"))"
  echo "Buffers:       ${buffers:-0} kB ($(format_kb_human "${buffers:-0}"))"
  echo "Cached:        ${cached:-0} kB ($(format_kb_human "${cached:-0}"))"
  echo "SwapTotal:     ${swap_total:-0} kB ($(format_kb_human "${swap_total:-0}"))"
  echo "SwapFree:      ${swap_free:-0} kB ($(format_kb_human "${swap_free:-0}"))"
}

show_status() {
  case "${SHOW_SCOPE}" in
    igb_uio)
      show_igb_uio_status
      ;;
    nics)
      show_nics_status
      ;;
    hugepages)
      check_hugepage_requirements
      show_hugepages_status
      ;;
    memory)
      show_memory_status
      ;;
    all)
      check_hugepage_requirements
      show_igb_uio_status
      show_nics_status
      show_hugepages_status
      show_memory_status
      ;;
    *)
      err "Unsupported show scope: ${SHOW_SCOPE}"
      exit 25
      ;;
  esac
}

parse_args() {
  if [[ "$#" -lt 1 ]]; then
    usage
    exit 1
  fi

  COMMAND="$1"
  shift

  case "${COMMAND}" in
    install-igb-uio)
      if [[ "$#" -lt 1 ]]; then
        err "The install-igb-uio command requires a source package argument."
        usage
        exit 1
      fi

      PKG_TAR="$1"
      shift

      while [[ "$#" -gt 0 ]]; do
        case "$1" in
          --auto-install-deps)
            AUTO_INSTALL_DEPS="true"
            shift
            ;;
          -h|--help)
            usage
            exit 0
            ;;
          *)
            err "Unknown option for install-igb-uio: $1"
            usage
            exit 1
            ;;
        esac
      done

      if [[ ! -f "${PKG_TAR}" ]]; then
        err "Source package not found: ${PKG_TAR}"
        exit 1
      fi
      ;;
    assess-nic-binding)
      while [[ "$#" -gt 0 ]]; do
        case "$1" in
          --json)
            OUTPUT_JSON="true"
            shift
            ;;
          -h|--help)
            usage
            exit 0
            ;;
          *)
            TARGET_LIST+=("$1")
            shift
            ;;
        esac
      done
      if [[ "${#TARGET_LIST[@]}" -lt 1 ]]; then
        err "The assess-nic-binding command requires at least one target."
        usage
        exit 1
      fi
      ;;
    bind-nic)
      while [[ "$#" -gt 0 ]]; do
        case "$1" in
          --confirm)
            CONFIRM="true"
            shift
            ;;
          -h|--help)
            usage
            exit 0
            ;;
          *)
            TARGET_LIST+=("$1")
            shift
            ;;
        esac
      done
      if [[ "${#TARGET_LIST[@]}" -lt 1 ]]; then
        err "The bind-nic command requires at least one target."
        usage
        exit 1
      fi
      ;;
    unbind-nic)
      while [[ "$#" -gt 0 ]]; do
        case "$1" in
          -h|--help)
            usage
            exit 0
            ;;
          *)
            TARGET_LIST+=("$1")
            shift
            ;;
        esac
      done
      if [[ "${#TARGET_LIST[@]}" -lt 1 ]]; then
        err "The unbind-nic command requires at least one target."
        usage
        exit 1
      fi
      ;;
    rollback-nic-binding)
      if [[ "$#" -ne 0 ]]; then
        err "The rollback-nic-binding command does not accept extra arguments."
        usage
        exit 1
      fi
      ;;
    assess-hugepages)
      while [[ "$#" -gt 0 ]]; do
        case "$1" in
          --json)
            OUTPUT_JSON="true"
            shift
            ;;
          --pages-per-node|--pages)
            if [[ "$#" -lt 2 ]]; then
              err "${1} requires a numeric argument."
              exit 1
            fi
            HUGEPAGES_PAGES_PER_NODE="$2"
            shift 2
            ;;
          --size-kb)
            if [[ "$#" -lt 2 ]]; then
              err "--size-kb requires a numeric argument."
              exit 1
            fi
            HUGEPAGES_SIZE_KB="$2"
            shift 2
            ;;
          -h|--help)
            usage
            exit 0
            ;;
          *)
            err "Unknown option for assess-hugepages: $1"
            usage
            exit 1
            ;;
        esac
      done
      ;;
    set-hugepages)
      while [[ "$#" -gt 0 ]]; do
        case "$1" in
          --pages-per-node|--pages)
            if [[ "$#" -lt 2 ]]; then
              err "${1} requires a numeric argument."
              exit 1
            fi
            HUGEPAGES_PAGES_PER_NODE="$2"
            shift 2
            ;;
          --size-kb)
            if [[ "$#" -lt 2 ]]; then
              err "--size-kb requires a numeric argument."
              exit 1
            fi
            HUGEPAGES_SIZE_KB="$2"
            shift 2
            ;;
          -h|--help)
            usage
            exit 0
            ;;
          *)
            err "Unknown option for set-hugepages: $1"
            usage
            exit 1
            ;;
        esac
      done
      ;;
    rollback-hugepages)
      if [[ "$#" -ne 0 ]]; then
        err "The rollback-hugepages command does not accept extra arguments."
        usage
        exit 1
      fi
      ;;
    start-engine-container)
      while [[ "$#" -gt 0 ]]; do
        case "$1" in
          --name)
            if [[ "$#" -lt 2 ]]; then
              err "--name requires an argument."
              exit 1
            fi
            CONTAINER_NAME="$2"
            shift 2
            ;;
          --image)
            if [[ "$#" -lt 2 ]]; then
              err "--image requires an argument."
              exit 1
            fi
            CONTAINER_IMAGE="$2"
            shift 2
            ;;
          --agent-token)
            if [[ "$#" -lt 2 ]]; then
              err "--agent-token requires an argument."
              exit 1
            fi
            CONTAINER_AGENT_TOKEN="$2"
            shift 2
            ;;
          --token)
            if [[ "$#" -lt 2 ]]; then
              err "--token requires an argument."
              exit 1
            fi
            CONTAINER_TOKEN="$2"
            shift 2
            ;;
          -h|--help)
            usage
            exit 0
            ;;
          *)
            err "Unknown option for start-engine-container: $1"
            usage
            exit 1
            ;;
        esac
      done
      ;;
    stop-engine-container|clear-engine-container)
      while [[ "$#" -gt 0 ]]; do
        case "$1" in
          --name)
            if [[ "$#" -lt 2 ]]; then
              err "--name requires an argument."
              exit 1
            fi
            CONTAINER_NAME="$2"
            shift 2
            ;;
          -h|--help)
            usage
            exit 0
            ;;
          *)
            err "Unknown option for ${COMMAND}: $1"
            usage
            exit 1
            ;;
        esac
      done
      ;;
    show)
      if [[ "$#" -ne 1 ]]; then
        err "The show command requires exactly one scope argument."
        err "Supported scopes: igb_uio, nics, hugepages, memory, all"
        usage
        exit 1
      fi
      SHOW_SCOPE="$1"
      case "${SHOW_SCOPE}" in
        igb_uio|nics|hugepages|memory|all)
          ;;
        *)
          err "Unsupported show scope: ${SHOW_SCOPE}"
          err "Supported scopes: igb_uio, nics, hugepages, memory, all"
          exit 1
          ;;
      esac
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      err "Unknown command: ${COMMAND}"
      usage
      exit 1
      ;;
  esac

  if [[ -n "${HUGEPAGES_PAGES_PER_NODE}" && ! "${HUGEPAGES_PAGES_PER_NODE}" =~ ^[0-9]+$ ]]; then
    err "--pages-per-node must be a non-negative integer."
    exit 1
  fi

  if [[ -n "${HUGEPAGES_SIZE_KB}" && ! "${HUGEPAGES_SIZE_KB}" =~ ^[0-9]+$ ]]; then
    err "--size-kb must be a non-negative integer."
    exit 1
  fi
}

cmd_install() {
  require_root
  check_install_requirements
  prepare_workspace
  build_module
  install_module
  log "install-igb-uio command completed successfully"
}

cmd_assess_bind() {
  check_network_requirements

  local t
  local first="true"

  if [[ "${OUTPUT_JSON}" == "true" ]]; then
    printf '['
    for t in "${TARGET_LIST[@]}"; do
      collect_assessment "${t}"
      if [[ "${first}" == "true" ]]; then
        first="false"
      else
        printf ','
      fi
      print_assessment_json
    done
    printf ']\n'
  else
    for t in "${TARGET_LIST[@]}"; do
      collect_assessment "${t}"
      print_assessment_human
      echo
    done
  fi
}

cmd_bind() {
  require_root
  ensure_state_dirs
  check_bind_requirements
  ensure_igb_uio_loaded

  local t
  for t in "${TARGET_LIST[@]}"; do
    bind_one_target "${t}"
  done

  log "bind-nic command completed successfully"
}

cmd_unbind() {
  require_root
  ensure_state_dirs
  check_bind_requirements

  local t
  for t in "${TARGET_LIST[@]}"; do
    unbind_one_target "${t}"
  done

  log "unbind-nic command completed successfully"
}

cmd_rollback_nic_binding() {
  require_root
  ensure_state_dirs
  check_bind_requirements
  rollback_all_bound_nics
  log "rollback-nic-binding command completed successfully"
}

cmd_assess_hugepages() {
  check_hugepage_requirements
  assess_hugepages_collect

  if [[ "${OUTPUT_JSON}" == "true" ]]; then
    print_hugepages_assessment_json
    printf '\n'
  else
    print_hugepages_assessment_human
  fi
}

cmd_set_hugepages() {
  require_root
  ensure_state_dirs
  check_hugepage_requirements
  set_hugepages
}

cmd_rollback_hugepages() {
  require_root
  ensure_state_dirs
  check_hugepage_requirements
  rollback_hugepages
}

cmd_start_engine_container() {
  require_root
  ensure_state_dirs
  check_container_start_requirements
  start_engine_container
}

cmd_stop_engine_container() {
  require_root
  ensure_state_dirs
  check_docker_requirements
  stop_engine_container
}

cmd_clear_engine_container() {
  require_root
  ensure_state_dirs
  check_docker_requirements
  clear_engine_container
}

cmd_show() {
  check_network_requirements
  show_status
}

main() {
  parse_args "$@"

  case "${COMMAND}" in
    install-igb-uio)
      cmd_install
      ;;
    assess-nic-binding)
      cmd_assess_bind
      ;;
    bind-nic)
      cmd_bind
      ;;
    unbind-nic)
      cmd_unbind
      ;;
    rollback-nic-binding)
      cmd_rollback_nic_binding
      ;;
    assess-hugepages)
      cmd_assess_hugepages
      ;;
    set-hugepages)
      cmd_set_hugepages
      ;;
    rollback-hugepages)
      cmd_rollback_hugepages
      ;;
    start-engine-container)
      cmd_start_engine_container
      ;;
    stop-engine-container)
      cmd_stop_engine_container
      ;;
    clear-engine-container)
      cmd_clear_engine_container
      ;;
    show)
      cmd_show
      ;;
    *)
      err "Internal error: unsupported command ${COMMAND}"
      exit 99
      ;;
  esac
}

main "$@"
