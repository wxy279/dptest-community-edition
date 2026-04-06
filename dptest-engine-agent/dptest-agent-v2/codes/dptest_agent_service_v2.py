from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import shlex
import socket
import sqlite3
import subprocess
import signal
import time

import httpx
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

# =========================
# Config
# =========================

BASE_DIR = Path(os.getenv("DPTEST_V2_BASE_DIR", "/opt/dptest-agent"))
DATA_DIR = Path(os.getenv("DPTEST_V2_DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = Path(os.getenv("DPTEST_V2_DB_PATH", str(DATA_DIR / "dptest_agent_v2.db")))
COMPILED_DIR = Path(os.getenv("DPTEST_V2_COMPILED_DIR", str(DATA_DIR / "compiled")))
RUN_LOG_DIR = Path(os.getenv("DPTEST_V2_RUN_LOG_DIR", str(DATA_DIR / "runs")))

SYSTEM_INTERFACE_INVENTORY_FILE = os.getenv("DPTEST_V2_SYSTEM_INTERFACES_FILE", "").strip()
SYSTEM_INTERFACE_INVENTORY_JSON = os.getenv("DPTEST_V2_SYSTEM_INTERFACES_JSON", "").strip()
SYSTEM_NUMA0_CPUS = os.getenv("DPTEST_V2_NUMA0_CPUS", "").strip()
SYSTEM_MEMORY_GB = os.getenv("DPTEST_V2_SYSTEM_MEMORY_GB", "").strip()

TEMPLATE_DIR = Path(os.getenv("DPTEST_TEMPLATE_DIR", str(BASE_DIR / "templates")))
MANIFEST_FILE = TEMPLATE_DIR / os.getenv("DPTEST_MANIFEST_FILENAME", "manifest.json")

DEPLOY_DIR = Path(os.getenv("DPTEST_DEPLOY_DIR", "/etc/dproxy"))
DEPLOY_FILE = DEPLOY_DIR / os.getenv("DPTEST_DEPLOY_FILENAME", "dpdkproxy.conf")
BACKUP_DIR = Path(os.getenv("DPTEST_BACKUP_DIR", "/etc/dproxy/backup"))

APPLY_COMMAND = os.getenv("DPTEST_APPLY_COMMAND", "").strip()
ALLOW_OVERWRITE = os.getenv("DPTEST_ALLOW_OVERWRITE", "true").lower() == "true"
STRICT_PLACEHOLDER_CHECK = os.getenv("DPTEST_STRICT_PLACEHOLDER_CHECK", "true").lower() == "true"

AGENT_TOKEN = os.getenv("DPTEST_AGENT_TOKEN", "").strip()

ENGINE_MONITOR_URL = os.getenv("DPTEST_ENGINE_MONITOR_URL", "http://127.0.0.1:10086/run/monitor").strip()
ENGINE_MONITOR_TIMEOUT = float(os.getenv("DPTEST_ENGINE_MONITOR_TIMEOUT", "5").strip())
STAGE_MAP_RAW = os.getenv(
    "DPTEST_STAGE_MAP",
    "0:delay,1:ramp up,2:stair step,3:steady State,4:ramp down",
).strip()
CANONICAL_LOAD_STAGE_NAMES = {
    "delay": "delay",
    "rampup": "ramp up",
    "ramp_up": "ramp up",
    "ramp up": "ramp up",
    "stairstep": "stair step",
    "stair_step": "stair step",
    "stair step": "stair step",
    "steady": "steady State",
    "steady_state": "steady State",
    "steady state": "steady State",
    "steadystate": "steady State",
    "rampdown": "ramp down",
    "ramp_down": "ramp down",
    "ramp down": "ramp down",
}

RUN_STARTUP_WAIT_SECONDS = float(os.getenv("DPTEST_V2_RUN_STARTUP_WAIT_SECONDS", "1.0").strip())
RUN_STOP_WAIT_SECONDS = float(os.getenv("DPTEST_V2_RUN_STOP_WAIT_SECONDS", "3.0").strip())
RUN_LOG_TAIL_BYTES = int(os.getenv("DPTEST_V2_RUN_LOG_TAIL_BYTES", "8192").strip())
DEFAULT_ENGINE_BINARY_PATH = os.getenv("DPTEST_V2_ENGINE_BINARY_PATH", "/usr/local/dproxy/app/dpdkproxy").strip()
DEFAULT_ENGINE_MEMORY_CHANNELS = int(os.getenv("DPTEST_V2_ENGINE_MEMORY_CHANNELS", "4").strip())
DEFAULT_ENGINE_LOG_LEVEL = int(os.getenv("DPTEST_V2_ENGINE_LOG_LEVEL", "2").strip())
DEFAULT_ENGINE_EXTRA_APP_ARGS_JSON = os.getenv("DPTEST_V2_ENGINE_EXTRA_APP_ARGS_JSON", "").strip()
DEFAULT_ENGINE_EXTRA_EAL_ARGS_JSON = os.getenv("DPTEST_V2_ENGINE_EXTRA_EAL_ARGS_JSON", "").strip()
DEFAULT_ENGINE_ENV_JSON = os.getenv("DPTEST_V2_ENGINE_ENV_JSON", "").strip()

PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")
PCI_ADDR_PATTERN = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$")
ETHTOOL_SPEED_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*([KMG])b/s", re.IGNORECASE)
SUPPORTED_LINK_MODE_PATTERN = re.compile(r"(\d+)\s*base", re.IGNORECASE)
DPDK_BOUND_DRIVER_NAMES = {"vfio-pci", "uio_pci_generic", "igb_uio"}
DEFAULT_MANAGEMENT_CORE = 0
DEFAULT_CRYPTO_WORKER_CORES: List[int] = []
DEFAULT_WORKER_COMMON_CONFIG = {"monitor_malloc": 0, "gdb_debug_enable": True}
ENGINE_SOCKET_SIZE_SPECS = [2, 4, 8, 16, 32]
deploy_lock = Lock()

app = FastAPI(
    title="dptest-agent-service-v2",
    version="2.1.0-mvp2",
    description="Object-model based dptest config compiler and orchestration service",
)


# =========================
# Auth
# =========================

def verify_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not AGENT_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="鏈嶅姟绔湭閰嶇疆 DPTEST_AGENT_TOKEN",
        )

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 鏍煎紡閿欒锛屽簲涓?Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1].strip()
    if not secrets.compare_digest(token, AGENT_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token 鏃犳晥",
        )


def protected(_: None = Depends(verify_bearer_token)) -> None:
    return None


# =========================
# Helpers
# =========================

def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COMPILED_DIR.mkdir(parents=True, exist_ok=True)
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_file_tail(path: Optional[str], max_bytes: int = RUN_LOG_TAIL_BYTES) -> Optional[str]:
    if not path:
        return None
    try:
        p = Path(path)
        if not p.exists():
            return None
        with p.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes), os.SEEK_SET)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return None


def get_pid_state(pid: Optional[int]) -> Optional[str]:
    if not pid:
        return None
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return None
        parts = content.split()
        if len(parts) < 3:
            return None
        return parts[2]
    except FileNotFoundError:
        return None
    except Exception:
        return None


def is_pid_running_non_zombie(pid: Optional[int]) -> bool:
    state = get_pid_state(pid)
    return bool(state and state != "Z")


def waitpid_nonblocking(pid: Optional[int]) -> Optional[int]:
    if not pid:
        return None
    try:
        waited_pid, status = os.waitpid(pid, os.WNOHANG)
        if waited_pid == 0:
            return None
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        if os.WIFSIGNALED(status):
            return 128 + os.WTERMSIG(status)
        return None
    except ChildProcessError:
        return None
    except Exception:
        return None


def finalize_run_status(
    run_obj: Dict[str, Any],
    status_value: str,
    reason: Optional[str] = None,
    exit_code: Optional[int] = None,
) -> Dict[str, Any]:
    run_obj["status"] = status_value
    run_obj["ended_at"] = run_obj.get("ended_at") or now_iso()
    run_obj["updated_at"] = now_iso()
    if reason:
        run_obj["final_reason"] = reason
    if exit_code is not None:
        run_obj["exit_code"] = exit_code
    if not run_obj.get("stderr_tail"):
        run_obj["stderr_tail"] = read_file_tail(run_obj.get("stderr_path"))
    if not run_obj.get("stdout_tail"):
        run_obj["stdout_tail"] = read_file_tail(run_obj.get("stdout_path"))
    save_run(run_obj["project_id"], run_obj["test_case_id"], run_obj["run_id"], run_obj)
    return run_obj


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def render_template(content: str, replacements: Dict[str, Any]) -> Tuple[str, List[str]]:
    missing: List[str] = []

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in replacements:
            missing.append(key)
            return match.group(0)
        value = replacements[key]
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    rendered = PLACEHOLDER_PATTERN.sub(repl, content)
    return rendered, sorted(set(missing))


def find_placeholders(content: str) -> List[str]:
    return sorted(set(PLACEHOLDER_PATTERN.findall(content)))


def backup_current_config() -> Optional[Path]:
    if not DEPLOY_FILE.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{DEPLOY_FILE.name}.{ts}.bak"
    shutil.copy2(DEPLOY_FILE, backup_path)
    return backup_path


def apply_config_command() -> Dict[str, Any]:
    if not APPLY_COMMAND:
        return {"applied": False, "message": "APPLY_COMMAND is not configured; skipping apply step"}
    try:
        completed = subprocess.run(
            APPLY_COMMAND,
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )
        return {
            "applied": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "command": APPLY_COMMAND,
        }
    except Exception as e:
        return {"applied": False, "error": str(e), "command": APPLY_COMMAND}


def validate_deploy_target() -> None:
    if DEPLOY_FILE.exists() and DEPLOY_FILE.is_dir():
        raise HTTPException(status_code=500, detail=f"閮ㄧ讲鐩爣鏄洰褰曪紝涓嶆槸鏂囦欢: {DEPLOY_FILE}")
    if DEPLOY_FILE.exists() and not ALLOW_OVERWRITE:
        raise HTTPException(status_code=409, detail=f"鐩爣鏂囦欢宸插瓨鍦ㄤ笖绂佹瑕嗙洊: {DEPLOY_FILE}")


def indent_block(text: str, level: int = 1, spaces: int = 4) -> str:
    prefix = " " * (level * spaces)
    return "\n".join(prefix + line if line.strip() else line for line in text.splitlines())


def to_libconfig_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    escaped = str(value).replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def extract_named_block(content: str, name: str) -> str:
    # returns e.g. 'application = {...};'
    pattern = re.compile(rf"\b{name}\s*=\s*\{{", re.MULTILINE)
    m = pattern.search(content)
    if not m:
        raise HTTPException(status_code=500, detail=f"妯℃澘涓湭鎵惧埌鍧? {name}")
    start = m.start()
    brace_start = content.find("{", m.start())
    if brace_start == -1:
        raise HTTPException(status_code=500, detail=f"妯℃澘鍧?{name} 璧峰鏃犳晥")
    depth = 0
    end = -1
    for i in range(brace_start, len(content)):
        ch = content[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                # include trailing semicolon if present
                end = i + 1
                while end < len(content) and content[end].isspace():
                    end += 1
                if end < len(content) and content[end] == ";":
                    end += 1
                break
    if end == -1:
        raise HTTPException(status_code=500, detail=f"template block {name} is not properly closed")
    return content[start:end]


# =========================
# SQLite persistence
# =========================

TABLE_DEFS = {
    "projects": """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "thread_policies": """
        CREATE TABLE IF NOT EXISTS thread_policies (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "engine_launch_profiles": """
        CREATE TABLE IF NOT EXISTS engine_launch_profiles (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "interfaces": """
        CREATE TABLE IF NOT EXISTS interfaces (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "subnets": """
        CREATE TABLE IF NOT EXISTS subnets (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "application_instances": """
        CREATE TABLE IF NOT EXISTS application_instances (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            template_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "load_profiles": """
        CREATE TABLE IF NOT EXISTS load_profiles (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "scenario_presets": """
        CREATE TABLE IF NOT EXISTS scenario_presets (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "clients": """
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "servers": """
        CREATE TABLE IF NOT EXISTS servers (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "test_cases": """
        CREATE TABLE IF NOT EXISTS test_cases (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "artifacts": """
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            test_case_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "runs": """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            test_case_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
}


@contextmanager
def db_conn() -> Iterable[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db_conn() as conn:
        for ddl in TABLE_DEFS.values():
            conn.execute(ddl)


def upsert_row(table: str, row_id: str, payload: Dict[str, Any], project_id: Optional[str] = None, name: Optional[str] = None, template_id: Optional[str] = None, test_case_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Compatibility note:
    - Some target environments ship older sqlite3 / libsqlite versions that do not
      support modern UPSERT syntax such as:
        INSERT ... ON CONFLICT(id) DO UPDATE ...
    - To stay compatible, we implement a manual select-then-update/insert path.
    """
    ts = now_iso()
    payload_json = json.dumps(payload, ensure_ascii=False)
    with db_conn() as conn:
        existing = conn.execute(f"SELECT id, created_at FROM {table} WHERE id=?", (row_id,)).fetchone()
        created_at = existing["created_at"] if existing else ts

        row_data: Dict[str, Any] = {"id": row_id}
        if table == "projects":
            row_data["name"] = name or payload.get("name", row_id)
        if table in {"thread_policies", "engine_launch_profiles", "interfaces", "subnets", "application_instances", "load_profiles", "scenario_presets", "clients", "servers", "test_cases", "runs"}:
            row_data["project_id"] = project_id
        if table == "application_instances":
            row_data["template_id"] = template_id
        if table in {"artifacts", "runs"}:
            row_data["test_case_id"] = test_case_id

        row_data["payload_json"] = payload_json
        row_data["created_at"] = created_at
        row_data["updated_at"] = ts

        if existing:
            update_cols = [c for c in row_data.keys() if c not in {"id", "created_at"}]
            set_clause = ", ".join([f"{c}=?" for c in update_cols])
            values = [row_data[c] for c in update_cols] + [row_id]
            conn.execute(f"UPDATE {table} SET {set_clause} WHERE id=?", tuple(values))
        else:
            insert_cols = list(row_data.keys())
            placeholders = ",".join(["?"] * len(insert_cols))
            values = [row_data[c] for c in insert_cols]
            conn.execute(
                f"INSERT INTO {table} ({','.join(insert_cols)}) VALUES ({placeholders})",
                tuple(values),
            )
    return payload


def delete_row(table: str, row_id: str) -> None:
    with db_conn() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))


def list_row_ids_by_column(table: str, column: str, value: str) -> List[str]:
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT id FROM {table} WHERE {column}=? ORDER BY created_at ASC",
            (value,),
        ).fetchall()
    return [str(row["id"]) for row in rows]


def get_row(table: str, row_id: str) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"{table} 涓笉瀛樺湪瀵硅薄: {row_id}")
    payload = json.loads(row["payload_json"])
    return payload


def list_rows(table: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        if project_id is None or table == "projects":
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY created_at ASC").fetchall()
        else:
            rows = conn.execute(f"SELECT * FROM {table} WHERE project_id=? ORDER BY created_at ASC", (project_id,)).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def remove_file_if_exists(path_value: Optional[str]) -> bool:
    if not path_value:
        return False
    try:
        p = Path(path_value)
        if not p.exists() or not p.is_file():
            return False
        p.unlink()
        return True
    except Exception:
        return False


def cascade_delete_project(project_id: str) -> Dict[str, Any]:
    _ = get_row("projects", project_id)

    runs = list_rows("runs", project_id)
    stopped_runs: List[str] = []
    run_stop_failures: List[Dict[str, Any]] = []
    for run_obj in runs:
        if run_obj.get("status") not in {"pending", "running", "stopping"}:
            continue
        refreshed = stop_run_process(run_obj)
        if refreshed.get("status") in {"pending", "running", "stopping"}:
            run_stop_failures.append({
                "run_id": refreshed.get("run_id"),
                "status": refreshed.get("status"),
                "stop_result": refreshed.get("stop_result"),
            })
        else:
            stopped_runs.append(str(refreshed.get("run_id")))

    if run_stop_failures:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "project still has runs that could not be stopped; delete was rejected to avoid orphaned processes",
                "project_id": project_id,
                "run_stop_failures": run_stop_failures,
            },
        )

    test_cases = list_rows("test_cases", project_id)
    test_case_ids = {str(tc["test_case_id"]) for tc in test_cases}
    artifacts = [row for row in list_rows("artifacts") if str(row.get("test_case_id")) in test_case_ids]

    deleted_files = {
        "artifact_output_files": 0,
        "run_stdout_files": 0,
        "run_stderr_files": 0,
    }

    for artifact in artifacts:
        if remove_file_if_exists(artifact.get("output_path")):
            deleted_files["artifact_output_files"] += 1

    for run_obj in runs:
        if remove_file_if_exists(run_obj.get("stdout_path")):
            deleted_files["run_stdout_files"] += 1
        if remove_file_if_exists(run_obj.get("stderr_path")):
            deleted_files["run_stderr_files"] += 1

    project_owned_tables = [
        "thread_policies",
        "engine_launch_profiles",
        "interfaces",
        "subnets",
        "application_instances",
        "load_profiles",
        "scenario_presets",
        "clients",
        "servers",
        "test_cases",
        "runs",
    ]

    deleted_counts: Dict[str, int] = {}
    for table in project_owned_tables:
        row_ids = list_row_ids_by_column(table, "project_id", project_id)
        for row_id in row_ids:
            delete_row(table, row_id)
        deleted_counts[table] = len(row_ids)

    deleted_artifact_count = 0
    for test_case_id in test_case_ids:
        artifact_ids = list_row_ids_by_column("artifacts", "test_case_id", test_case_id)
        for artifact_id in artifact_ids:
            delete_row("artifacts", artifact_id)
        deleted_artifact_count += len(artifact_ids)
    deleted_counts["artifacts"] = deleted_artifact_count

    delete_row("projects", project_id)
    deleted_counts["projects"] = 1

    return {
        "ok": True,
        "deleted": project_id,
        "stopped_runs": stopped_runs,
        "deleted_counts": deleted_counts,
        "deleted_files": deleted_files,
    }


def assert_project_exists(project_id: str) -> Dict[str, Any]:
    return get_row("projects", project_id)


# =========================
# Manifest models
# =========================

class ManifestTemplate(BaseModel):
    id: str
    file: str
    name: str
    description: str = ""
    category: str = ""
    protocol_family: str = ""
    scenario_type: str = ""
    request_method: str = ""
    transport: str = ""
    application_protocol: str = ""
    engine_mode: str = ""
    required_params: List[str] = Field(default_factory=list)
    optional_params: List[str] = Field(default_factory=list)
    defaults: Dict[str, Any] = Field(default_factory=dict)
    template_placeholders: List[str] = Field(default_factory=list)
    focus_metrics: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

    @field_validator("file")
    @classmethod
    def validate_file(cls, v: str) -> str:
        if "/" in v or "\\" in v or ".." in v:
            raise ValueError("manifest 涓?file 闈炴硶")
        return v


class ManifestFile(BaseModel):
    version: str = "1.0"
    templates: List[ManifestTemplate] = Field(default_factory=list)


def load_manifest() -> ManifestFile:
    if not MANIFEST_FILE.exists():
        raise HTTPException(status_code=404, detail=f"manifest 鏂囦欢涓嶅瓨鍦? {MANIFEST_FILE}")
    try:
        raw = json.loads(read_text_file(MANIFEST_FILE))
        return ManifestFile.model_validate(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"manifest 瑙ｆ瀽澶辫触: {e}")


def build_manifest_index(manifest: ManifestFile) -> Dict[str, ManifestTemplate]:
    result: Dict[str, ManifestTemplate] = {}
    for item in manifest.templates:
        if item.id in result:
            raise HTTPException(status_code=500, detail=f"manifest 涓瓨鍦ㄩ噸澶?template id: {item.id}")
        result[item.id] = item
    return result


def get_manifest_template(template_id: str) -> ManifestTemplate:
    manifest = load_manifest()
    index = build_manifest_index(manifest)
    if template_id not in index:
        raise HTTPException(status_code=404, detail=f"manifest 涓笉瀛樺湪妯℃澘: {template_id}")
    return index[template_id]


# =========================
# API models
# =========================

ModeType = Literal["client_only", "server_only", "dual_end"]
StressType = Literal["run_once", "run"]
StressMode = Literal["SimUsers", "connections"]
MetricMode = Literal["tps", "rps", "tput"]
CloseMode = Literal["FIN", "RST"]
CLOSE_MODE_VALUES = {"FIN", "RST"}
DEFAULT_STRESS_MODE: StressMode = "SimUsers"
DEFAULT_MAX_CONNECTION_ATTEMPTS = 9223372036854775807
HTTP3_DEFAULT_KEYFILE_NAME = "http3_server.key"
HTTP3_DEFAULT_CERTFILE_NAME = "http3_server.crt"
DUAL_END_HTTP3_DEFAULT_KEYFILE_NAME = "backend.key"
DUAL_END_HTTP3_DEFAULT_CERTFILE_NAME = "backend.crt"


def normalize_stress_mode_name(value: Any) -> StressMode:
    text = str(value or "").strip()
    lowered = text.lower()
    if lowered == "simusers":
        return "SimUsers"
    if lowered == "connections":
        return "connections"
    raise ValueError("stress_mode must be SimUsers or connections")


def render_stress_mode_name(value: Any) -> str:
    return "Simusers" if normalize_stress_mode_name(value) == "SimUsers" else "connections"


class ProjectCreate(BaseModel):
    project_id: str
    name: str
    description: str = ""


class ThreadPolicyPayload(BaseModel):
    thread_policy_id: str
    management_core: int = 0
    traffic_worker_cores: List[int]
    crypto_worker_cores: List[int]
    worker_common_config: Dict[str, Any] = Field(default_factory=lambda: {"monitor_malloc": 0, "gdb_debug_enable": True})

    @field_validator("traffic_worker_cores")
    @classmethod
    def validate_traffic_workers(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("traffic_worker_cores cannot be empty; it represents the candidate traffic worker lcores on NUMA0")
        return v


class EngineLaunchProfilePayload(BaseModel):
    engine_launch_profile_id: str
    binary_path: str = "/usr/local/dproxy/app/dpdkproxy"
    socket_size_gb: int = 16
    memory_channels: int = 4
    log_level: int = 2
    extra_app_args: List[str] = Field(default_factory=list)
    extra_eal_args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)


class InterfacePayload(BaseModel):
    interface_id: str
    dpdk_port_id: int
    pci_addr: Optional[str] = None
    label: Optional[str] = None


class SubnetPayload(BaseModel):
    subnet_id: str
    name: str
    base_addr: str
    count: int
    network: str
    netmask: int
    default_gw: Optional[str] = None

    @field_validator("count")
    @classmethod
    def validate_count(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("count 蹇呴』澶т簬 0")
        return v


class ApplicationMetricProfilePayload(BaseModel):
    metric_mode: Optional[MetricMode] = None
    request_method: Optional[Literal["GET", "POST", "HEAD"]] = None
    goto_iteration: Optional[int] = None
    request_path: Optional[str] = None
    content_type: Optional[str] = None
    post_content: Optional[str] = None
    post_content_file: Optional[str] = None
    upload_file: Optional[str] = None
    custom_header_name: Optional[str] = None
    custom_header_value: Optional[str] = None
    response_file: Optional[str] = None
    follow_redirects: Optional[bool] = None
    response_latency_mode: Optional[str] = None
    send_close_notify: Optional[bool] = None
    tcp_close_mode: Optional[CloseMode] = None
    persistent: Optional[bool] = None
    server_enable_persistent: Optional[bool] = None
    enable_rename_post_file: Optional[bool] = None

    @field_validator("goto_iteration")
    @classmethod
    def validate_goto_iteration(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("goto_iteration 涓嶈兘灏忎簬 0")
        return v


class ApplicationRecipeRequestPayload(BaseModel):
    request_path: Optional[str] = None
    request_paths: List[str] = Field(default_factory=list)
    content_type: Optional[str] = None
    post_content: Optional[str] = None
    post_content_file: Optional[str] = None
    upload_file: Optional[str] = None
    enable_rename_post_file: Optional[bool] = None
    custom_header_name: Optional[str] = None
    custom_header_value: Optional[str] = None


class ApplicationRecipeResponsePayload(BaseModel):
    response_file: Optional[str] = None
    response_directory: Optional[str] = None
    response_latency_mode: Optional[str] = None
    server_enable_persistent: Optional[bool] = None


class ApplicationRecipeRedirectPayload(BaseModel):
    follow_redirects: Optional[bool] = None


class ApplicationRecipeTLSPayload(BaseModel):
    send_close_notify: Optional[bool] = None


class ApplicationRecipeConnectionPayload(BaseModel):
    client_persistent: Optional[bool] = None
    tcp_close_mode: Optional[CloseMode] = None


class ApplicationRecipePayload(BaseModel):
    protocol_family: Optional[Literal["HTTP", "HTTPS", "HTTP3"]] = None
    request_method: Optional[Literal["GET", "POST", "HEAD"]] = None
    metric_mode: Optional[MetricMode] = None
    goto_iteration: Optional[int] = None
    request: ApplicationRecipeRequestPayload = Field(default_factory=ApplicationRecipeRequestPayload)
    response: ApplicationRecipeResponsePayload = Field(default_factory=ApplicationRecipeResponsePayload)
    redirect: ApplicationRecipeRedirectPayload = Field(default_factory=ApplicationRecipeRedirectPayload)
    tls: ApplicationRecipeTLSPayload = Field(default_factory=ApplicationRecipeTLSPayload)
    connection: ApplicationRecipeConnectionPayload = Field(default_factory=ApplicationRecipeConnectionPayload)

    @field_validator("goto_iteration")
    @classmethod
    def validate_goto_iteration(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("goto_iteration 涓嶈兘灏忎簬 0")
        return v


class ApplicationInstancePayload(BaseModel):
    application_instance_id: str
    template_id: str
    name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    metric_profile: Optional[ApplicationMetricProfilePayload] = None
    recipe: Optional[ApplicationRecipePayload] = None


class ApplicationProtocolSwitchPayload(BaseModel):
    target_protocol_family: Literal["HTTPS", "HTTP3"]
    target_template_id: Optional[str] = None
    param_overrides: Dict[str, Any] = Field(default_factory=dict)
    preserve_runtime_profile: bool = True


class LoadStage(BaseModel):
    stage: str
    repetitions: int = 1
    height: int
    ramp_time: int
    steady_time: int

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, value: str) -> str:
        return normalize_load_stage_name(value)


class LoadProfilePayload(BaseModel):
    load_profile_id: str
    name: str
    stress_type: StressType
    stress_mode: StressMode = DEFAULT_STRESS_MODE
    max_connection_attemps: int = DEFAULT_MAX_CONNECTION_ATTEMPTS
    stages: List[LoadStage]

    @field_validator("stress_mode")
    @classmethod
    def validate_stress_mode(cls, value: str) -> StressMode:
        return normalize_stress_mode_name(value)

    @field_validator("stages")
    @classmethod
    def validate_stages(cls, v: List[LoadStage]) -> List[LoadStage]:
        if not v:
            raise ValueError("stages 涓嶈兘涓虹┖")
        return v




class ScenarioPresetClientSlotPayload(BaseModel):
    slot_id: str
    interface_ref: str
    subnet_ref: str
    application_instance_ref: Optional[str] = None
    load_profile_ref: Optional[str] = None


class ScenarioPresetServerSlotPayload(BaseModel):
    slot_id: str
    interface_ref: str
    subnet_ref: str
    application_instance_ref: Optional[str] = None


class ScenarioPresetPayload(BaseModel):
    scenario_preset_id: str
    name: str
    description: str = ""
    mode: ModeType
    thread_policy_ref: Optional[str] = None
    engine_launch_profile_ref: Optional[str] = None
    client_slots: List[ScenarioPresetClientSlotPayload] = Field(default_factory=list)
    server_slots: List[ScenarioPresetServerSlotPayload] = Field(default_factory=list)
    target_host_strategy: str = ""
    default_load_profile_ref: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class ScenarioPresetComposePayload(BaseModel):
    test_case_id: str
    name: str
    application_template_id: Optional[str] = None
    application_instance_ref: Optional[str] = None
    application_instance_id: Optional[str] = None
    application_instance_name: Optional[str] = None
    application_params: Dict[str, Any] = Field(default_factory=dict)
    client_application_instance_ref: Optional[str] = None
    server_application_instance_ref: Optional[str] = None
    recipe: Optional[ApplicationRecipePayload] = None
    apply_recipe_to: Literal["clients", "servers", "both"] = "clients"
    load_profile_ref: Optional[str] = None
    client_load_profile_ref: Optional[str] = None
    load_profile: Optional[LoadProfilePayload] = None
    output_filename: Optional[str] = None
    run_mode: Optional[StressType] = None


class ClientPayload(BaseModel):
    client_instance_id: str
    interface_ref: str
    subnet_ref: str
    application_instance_ref: str
    load_profile_ref: str


class ServerPayload(BaseModel):
    server_instance_id: str
    interface_ref: str
    subnet_ref: str
    application_instance_ref: str


class TestCasePayload(BaseModel):
    test_case_id: str
    name: str
    mode: ModeType
    thread_policy_ref: Optional[str] = None
    engine_launch_profile_ref: Optional[str] = None
    client_instance_ids: List[str] = Field(default_factory=list)
    server_instance_ids: List[str] = Field(default_factory=list)


class TestCaseBindingsPayload(BaseModel):
    thread_policy_ref: Optional[str] = None
    engine_launch_profile_ref: Optional[str] = None
    client_instance_ids: Optional[List[str]] = None
    server_instance_ids: Optional[List[str]] = None


class CompileRequest(BaseModel):
    deploy: bool = False
    apply_after_deploy: bool = False
    output_filename: Optional[str] = None


class RunRequest(BaseModel):
    run_mode: StressType
    output_filename: Optional[str] = None
    apply_after_deploy: bool = True


# =========================
# Persistence wrappers
# =========================

def save_project(payload: ProjectCreate) -> Dict[str, Any]:
    data = {
        "project_id": payload.project_id,
        "name": payload.name,
        "description": payload.description,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    return upsert_row("projects", payload.project_id, data, name=payload.name)


def save_thread_policy(project_id: str, payload: ThreadPolicyPayload) -> Dict[str, Any]:
    assert_project_exists(project_id)
    data = payload.model_dump()
    data["project_id"] = project_id
    data["updated_at"] = now_iso()
    return upsert_row("thread_policies", payload.thread_policy_id, data, project_id=project_id)


def save_engine_launch_profile(project_id: str, payload: EngineLaunchProfilePayload) -> Dict[str, Any]:
    assert_project_exists(project_id)
    data = payload.model_dump()
    data["project_id"] = project_id
    data["updated_at"] = now_iso()
    return upsert_row("engine_launch_profiles", payload.engine_launch_profile_id, data, project_id=project_id)


def save_interface(project_id: str, payload: InterfacePayload) -> Dict[str, Any]:
    assert_project_exists(project_id)
    data = payload.model_dump()
    data["project_id"] = project_id
    data["updated_at"] = now_iso()
    return upsert_row("interfaces", payload.interface_id, data, project_id=project_id)


def save_subnet(project_id: str, payload: SubnetPayload) -> Dict[str, Any]:
    assert_project_exists(project_id)
    data = payload.model_dump()
    data["project_id"] = project_id
    data["updated_at"] = now_iso()
    return upsert_row("subnets", payload.subnet_id, data, project_id=project_id)


def extract_single_target_host(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        for key in ("base_addr", "ip", "address", "host", "target_host", "TARGET_HOST"):
            candidate = value.get(key)
            if candidate is None:
                continue
            text = str(candidate).strip()
            if text:
                return text
        raise HTTPException(
            status_code=400,
            detail="params.target_hosts must be a single IP string or an object containing base_addr/ip/address/host",
        )
    if isinstance(value, list):
        if not value:
            return None
        if len(value) != 1:
            raise HTTPException(
                status_code=400,
                detail="params.target_hosts supports exactly one target host; count is fixed to 1 internally",
            )
        return extract_single_target_host(value[0])
    raise HTTPException(
        status_code=400,
        detail="params.target_hosts must be a string, a single-item list, or an object describing one target host",
    )


def normalize_close_mode_param(value: Any, label: str = "TCP_CLOSE_MODE") -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if text not in CLOSE_MODE_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be one of {sorted(CLOSE_MODE_VALUES)}",
        )
    return text


def normalize_application_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    normalized = dict(params or {})

    resolved_target_host: Optional[str] = None
    for alias in ("target_hosts", "target_host", "TARGET_HOST"):
        if alias not in normalized:
            continue
        alias_value = normalized.pop(alias)
        candidate = extract_single_target_host(alias_value)
        if candidate is None:
            continue
        if resolved_target_host is not None and resolved_target_host != candidate:
            raise HTTPException(
                status_code=400,
                detail="conflicting target host values were provided; use one target_hosts/target_host/TARGET_HOST value only",
            )
        resolved_target_host = candidate

    normalized.pop("target_host_count", None)
    normalized.pop("TARGET_HOST_COUNT", None)
    if resolved_target_host is not None:
        normalized["target_hosts"] = resolved_target_host

    resolved_close_mode: Optional[str] = None
    for alias in ("tcp_close_mode", "TCP_CLOSE_MODE"):
        if alias not in normalized:
            continue
        alias_value = normalized.pop(alias)
        candidate = normalize_close_mode_param(alias_value, label=f"params.{alias}")
        if candidate is None:
            continue
        if resolved_close_mode is not None and resolved_close_mode != candidate:
            raise HTTPException(
                status_code=400,
                detail="conflicting tcp close mode values were provided; use one tcp_close_mode/TCP_CLOSE_MODE value only",
            )
        resolved_close_mode = candidate
    if resolved_close_mode is not None:
        normalized["TCP_CLOSE_MODE"] = resolved_close_mode
    return normalized


def build_render_application_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    normalized = normalize_application_params(params)
    render_params = dict(normalized)
    target_host = render_params.get("target_hosts")
    if target_host not in (None, ""):
        render_params["TARGET_HOST"] = target_host
    return render_params


def apply_protocol_runtime_defaults(
    tpl: "ManifestTemplate",
    params: Dict[str, Any],
    explicit_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    merged = dict(params)
    explicit = normalize_application_params(explicit_params or {})
    protocol_family = str(getattr(tpl, "protocol_family", "") or "").upper()
    if protocol_family not in {"HTTPS", "HTTP3"}:
        return merged

    server_http_version = str(merged.get("SERVER_HTTP_VERSION", "") or "").strip()
    default_access_port = 443
    if protocol_family == "HTTP3" and server_http_version == "3.0":
        default_listen_port = 443
    else:
        default_listen_port = 80

    if explicit.get("ACCESS_PORT") in (None, ""):
        merged["ACCESS_PORT"] = default_access_port
    if explicit.get("LISTEN_PORT") in (None, ""):
        merged["LISTEN_PORT"] = default_listen_port

    if protocol_family == "HTTP3" and server_http_version == "3.0":
        if str(getattr(tpl, "id", "") or "") == "dual_end_http3_midbox_rps":
            default_keyfile_name = DUAL_END_HTTP3_DEFAULT_KEYFILE_NAME
            default_certfile_name = DUAL_END_HTTP3_DEFAULT_CERTFILE_NAME
        else:
            default_keyfile_name = HTTP3_DEFAULT_KEYFILE_NAME
            default_certfile_name = HTTP3_DEFAULT_CERTFILE_NAME
        if explicit.get("KEYFILE_NAME") in (None, ""):
            merged["KEYFILE_NAME"] = default_keyfile_name
        if explicit.get("CERTFILE_NAME") in (None, ""):
            merged["CERTFILE_NAME"] = default_certfile_name
    return merged


def protocol_switch_nonportable_param_names(current_tpl: "ManifestTemplate", target_tpl: "ManifestTemplate") -> set[str]:
    current_family = str(getattr(current_tpl, "protocol_family", "") or "").upper()
    target_family = str(getattr(target_tpl, "protocol_family", "") or "").upper()
    if current_family == target_family:
        return set()
    if {current_family, target_family} == {"HTTPS", "HTTP3"}:
        return {"KEYFILE_NAME", "CERTFILE_NAME"}
    return set()


def present_application_instance(obj: Dict[str, Any]) -> Dict[str, Any]:
    presented = dict(obj)
    presented["params"] = normalize_application_params(obj.get("params") or {})
    return presented


def present_manifest_template_data(data: Dict[str, Any]) -> Dict[str, Any]:
    presented = dict(data)
    for field in ("required_params", "optional_params", "template_placeholders", "actual_placeholders_in_file"):
        if field not in presented or not isinstance(presented[field], list):
            continue
        presented[field] = ["target_hosts" if item == "TARGET_HOST" else item for item in presented[field]]
    return presented


PROTOCOL_SWITCH_TEMPLATE_DEFAULTS: Dict[Tuple[str, str], str] = {
    ("dual_end_https_midbox_sm2_gcm_rps", "HTTP3"): "dual_end_http3_midbox_rps",
    ("dual_end_http3_midbox_rps", "HTTPS"): "dual_end_https_midbox_sm2_gcm_rps",
}


def user_visible_manifest_param_name(name: str) -> str:
    return "target_hosts" if name == "TARGET_HOST" else name


def collect_manifest_user_param_names(tpl: ManifestTemplate) -> set[str]:
    names: set[str] = set()
    for field in ("required_params", "optional_params", "template_placeholders"):
        for item in getattr(tpl, field, []) or []:
            names.add(user_visible_manifest_param_name(item))
    return names


def extract_effective_user_visible_params(app_instance: Dict[str, Any]) -> Dict[str, Any]:
    _, params = resolve_application_template_params(app_instance)
    user_params: Dict[str, Any] = {}
    for key, value in params.items():
        if key == "TARGET_HOST":
            user_params["target_hosts"] = value
            continue
        user_params[key] = value
    return normalize_application_params(user_params)


def extract_host_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("[") and "]" in text:
        return text[1:].split("]", 1)[0].strip()
    if ":" in text:
        return text.split(":", 1)[0].strip()
    return text


def derive_effective_application_recipe(app_instance: Dict[str, Any]) -> Optional[ApplicationRecipePayload]:
    if app_instance.get("recipe"):
        return ApplicationRecipePayload.model_validate(app_instance["recipe"])
    if app_instance.get("metric_profile"):
        metric = ApplicationMetricProfilePayload.model_validate(app_instance["metric_profile"])
        return recipe_from_metric_profile(metric)
    return None


def _get_first_action_block_text(application_block: str, action_name: str) -> Optional[str]:
    ranges = _find_action_block_ranges(application_block, action_name)
    if not ranges:
        return None
    start, end = ranges[0]
    return application_block[start:end]


def infer_metric_mode_from_application_block(application_block: str, tpl: ManifestTemplate) -> MetricMode:
    method = _infer_application_method(application_block, tpl)
    if not _find_action_block_ranges(application_block, "Goto"):
        return "tps"
    if method == "POST":
        post_block = _get_first_action_block_text(application_block, "POST")
        if post_block is not None:
            post_content = _get_block_property_value(post_block, "post_content", None)
            post_content_file = _get_block_property_value(post_block, "post_content_file", None)
            if str(post_content or "") == "" and str(post_content_file or "").strip():
                return "tput"
        return "rps"
    response_block = _get_first_action_block_text(application_block, "Response 200 (OK)")
    if response_block is not None:
        response_file = _get_block_property_value(response_block, "file_response_data", None)
        response_directory = _get_block_property_value(response_block, "directory_for_response", None)
        if str(response_file or "").strip() or str(response_directory or "").strip():
            return "tput"
    return "rps"


def infer_effective_application_recipe_from_rendered_block(
    app_instance: Dict[str, Any],
    tpl: ManifestTemplate,
    application_block: str,
) -> ApplicationRecipePayload:
    goto_block = _get_first_action_block_text(application_block, "Goto")
    goto_iteration = _get_block_property_value(goto_block, "iteration", 64) if goto_block is not None else 64
    return ApplicationRecipePayload(
        protocol_family=_infer_protocol_family(application_block, tpl),
        request_method=_infer_application_method(application_block, tpl),
        metric_mode=infer_metric_mode_from_application_block(application_block, tpl),
        goto_iteration=goto_iteration,
    )


def merge_recipe_request_payload(
    base: ApplicationRecipeRequestPayload,
    override: ApplicationRecipeRequestPayload,
) -> ApplicationRecipeRequestPayload:
    return ApplicationRecipeRequestPayload(
        request_path=override.request_path if override.request_path is not None else base.request_path,
        request_paths=list(override.request_paths) if override.request_paths else list(base.request_paths),
        content_type=override.content_type if override.content_type is not None else base.content_type,
        post_content=override.post_content if override.post_content is not None else base.post_content,
        post_content_file=override.post_content_file if override.post_content_file is not None else base.post_content_file,
        upload_file=override.upload_file if override.upload_file is not None else base.upload_file,
        enable_rename_post_file=override.enable_rename_post_file if override.enable_rename_post_file is not None else base.enable_rename_post_file,
        custom_header_name=override.custom_header_name if override.custom_header_name is not None else base.custom_header_name,
        custom_header_value=override.custom_header_value if override.custom_header_value is not None else base.custom_header_value,
    )


def merge_recipe_response_payload(
    base: ApplicationRecipeResponsePayload,
    override: ApplicationRecipeResponsePayload,
) -> ApplicationRecipeResponsePayload:
    return ApplicationRecipeResponsePayload(
        response_file=override.response_file if override.response_file is not None else base.response_file,
        response_directory=override.response_directory if override.response_directory is not None else base.response_directory,
        response_latency_mode=override.response_latency_mode if override.response_latency_mode is not None else base.response_latency_mode,
        server_enable_persistent=override.server_enable_persistent if override.server_enable_persistent is not None else base.server_enable_persistent,
    )


def merge_recipe_redirect_payload(
    base: ApplicationRecipeRedirectPayload,
    override: ApplicationRecipeRedirectPayload,
) -> ApplicationRecipeRedirectPayload:
    return ApplicationRecipeRedirectPayload(
        follow_redirects=override.follow_redirects if override.follow_redirects is not None else base.follow_redirects,
    )


def merge_recipe_tls_payload(
    base: ApplicationRecipeTLSPayload,
    override: ApplicationRecipeTLSPayload,
) -> ApplicationRecipeTLSPayload:
    return ApplicationRecipeTLSPayload(
        send_close_notify=override.send_close_notify if override.send_close_notify is not None else base.send_close_notify,
    )


def merge_recipe_connection_payload(
    base: ApplicationRecipeConnectionPayload,
    override: ApplicationRecipeConnectionPayload,
) -> ApplicationRecipeConnectionPayload:
    return ApplicationRecipeConnectionPayload(
        client_persistent=override.client_persistent if override.client_persistent is not None else base.client_persistent,
        tcp_close_mode=override.tcp_close_mode if override.tcp_close_mode is not None else base.tcp_close_mode,
    )


def normalize_merged_application_recipe(
    previous_recipe: ApplicationRecipePayload,
    merged_recipe: ApplicationRecipePayload,
) -> ApplicationRecipePayload:
    method = str(merged_recipe.request_method or "").upper()
    previous_metric = str(previous_recipe.metric_mode or "").lower()
    metric_mode = str(merged_recipe.metric_mode or "").lower()

    if method != "POST":
        merged_recipe.request.upload_file = None
        merged_recipe.request.enable_rename_post_file = None

    if metric_mode == "tput":
        if method == "POST":
            merged_recipe.response.response_file = ""
            merged_recipe.response.response_directory = ""
        else:
            if str(merged_recipe.response.response_file or "").strip() == "":
                merged_recipe.response.response_file = None
            if str(merged_recipe.response.response_directory or "").strip() == "":
                merged_recipe.response.response_directory = None
            merged_recipe.request.upload_file = None
            merged_recipe.request.enable_rename_post_file = None
    elif previous_metric == "tput":
        previous_response_file = str(previous_recipe.response.response_file or "").strip()
        previous_response_directory = str(previous_recipe.response.response_directory or "").strip()
        if previous_response_file and (
            merged_recipe.response.response_file is None
            or str(merged_recipe.response.response_file or "").strip() == previous_response_file
        ):
            merged_recipe.response.response_file = ""
        if previous_response_directory and (
            merged_recipe.response.response_directory is None
            or str(merged_recipe.response.response_directory or "").strip() == previous_response_directory
        ):
            merged_recipe.response.response_directory = ""

    return merged_recipe


def merge_application_recipe_override(
    base_recipe: ApplicationRecipePayload,
    override_recipe: ApplicationRecipePayload,
) -> ApplicationRecipePayload:
    merged_recipe = ApplicationRecipePayload(
        protocol_family=override_recipe.protocol_family if override_recipe.protocol_family is not None else base_recipe.protocol_family,
        request_method=override_recipe.request_method if override_recipe.request_method is not None else base_recipe.request_method,
        metric_mode=override_recipe.metric_mode if override_recipe.metric_mode is not None else base_recipe.metric_mode,
        goto_iteration=override_recipe.goto_iteration if override_recipe.goto_iteration is not None else base_recipe.goto_iteration,
        request=merge_recipe_request_payload(base_recipe.request, override_recipe.request),
        response=merge_recipe_response_payload(base_recipe.response, override_recipe.response),
        redirect=merge_recipe_redirect_payload(base_recipe.redirect, override_recipe.redirect),
        tls=merge_recipe_tls_payload(base_recipe.tls, override_recipe.tls),
        connection=merge_recipe_connection_payload(base_recipe.connection, override_recipe.connection),
    )
    if merged_recipe.metric_mode is None:
        raise HTTPException(status_code=400, detail="metric_mode is required when the current application does not have an effective metric to inherit")
    if merged_recipe.goto_iteration is None:
        merged_recipe.goto_iteration = 64
    return normalize_merged_application_recipe(base_recipe, merged_recipe)


def resolve_protocol_switch_target_template(current_tpl: ManifestTemplate, payload: ApplicationProtocolSwitchPayload) -> ManifestTemplate:
    target_family = payload.target_protocol_family.upper()
    current_family = str(current_tpl.protocol_family or "").upper()
    if current_family == target_family:
        raise HTTPException(status_code=400, detail=f"application is already using protocol_family={target_family}")

    if payload.target_template_id:
        target_tpl = get_manifest_template(payload.target_template_id)
        actual_family = str(target_tpl.protocol_family or "").upper()
        if actual_family != target_family:
            raise HTTPException(
                status_code=400,
                detail=f"target_template_id={payload.target_template_id} has protocol_family={actual_family}, not {target_family}",
            )
        if str(current_tpl.engine_mode or "").lower() == "dual_end" and str(target_tpl.engine_mode or "").lower() != "dual_end":
            raise HTTPException(status_code=400, detail="dual_end application can only switch to another dual_end template")
        return target_tpl

    mapped_template_id = PROTOCOL_SWITCH_TEMPLATE_DEFAULTS.get((current_tpl.id, target_family))
    if not mapped_template_id:
        raise HTTPException(
            status_code=400,
            detail=f"no default protocol switch target is defined for template_id={current_tpl.id} -> {target_family}; provide target_template_id explicitly",
        )
    return get_manifest_template(mapped_template_id)


def infer_application_bound_role_usage(project_id: str, app_instance_id: str, current_tpl: ManifestTemplate, target_tpl: ManifestTemplate) -> Tuple[bool, bool, List[str]]:
    warnings: List[str] = []
    needs_client = any(item.get("application_instance_ref") == app_instance_id for item in list_rows("clients", project_id))
    needs_server = any(item.get("application_instance_ref") == app_instance_id for item in list_rows("servers", project_id))

    if not needs_client and not needs_server:
        if "dual_end" in {str(current_tpl.engine_mode or "").lower(), str(target_tpl.engine_mode or "").lower()}:
            needs_client = True
            needs_server = True
            warnings.append("application is not currently bound to clients/servers; protocol switch preview assumes dual_end usage for validation")
    return needs_client, needs_server, warnings


def adapt_recipe_for_protocol_switch(recipe: Optional[ApplicationRecipePayload], target_tpl: ManifestTemplate) -> Optional[ApplicationRecipePayload]:
    if not recipe:
        return None
    adapted = recipe.model_copy(deep=True)
    target_family = str(target_tpl.protocol_family or "").upper()
    target_method = str(target_tpl.request_method or "").upper()

    adapted.protocol_family = target_family if target_family in {"HTTP", "HTTPS", "HTTP3"} else None
    current_method = str(adapted.request_method or "").upper()
    if current_method in {"GET", "POST", "HEAD"}:
        adapted.request_method = current_method
    else:
        adapted.request_method = target_method if target_method in {"GET", "POST", "HEAD"} else None

    if target_family != "HTTPS":
        adapted.tls.send_close_notify = None

    if adapted.request_method != "POST":
        adapted.request.upload_file = None
        adapted.request.enable_rename_post_file = None

    return adapted


def build_protocol_switched_application_instance(
    project_id: str,
    app_instance: Dict[str, Any],
    payload: ApplicationProtocolSwitchPayload,
) -> Dict[str, Any]:
    current_tpl = get_manifest_template(app_instance["template_id"])
    target_tpl = resolve_protocol_switch_target_template(current_tpl, payload)
    source_params = extract_effective_user_visible_params(app_instance)
    source_explicit_params = normalize_application_params(app_instance.get("params") or {})
    target_defaults = normalize_application_params(getattr(target_tpl, "defaults", {}) or {})
    target_param_names = collect_manifest_user_param_names(target_tpl)
    overrides = normalize_application_params(payload.param_overrides)
    nonportable_param_names = protocol_switch_nonportable_param_names(current_tpl, target_tpl)

    carried_params = {key: value for key, value in source_params.items() if key in target_param_names and key not in nonportable_param_names}
    carried_explicit_params = {key: value for key, value in source_explicit_params.items() if key in target_param_names and key not in nonportable_param_names}
    dropped_params = sorted(key for key in source_params.keys() if key not in target_param_names or key in nonportable_param_names)

    switched_params = dict(target_defaults)
    switched_params.update(carried_params)
    switched_params.update(overrides)
    switched_params = normalize_application_params({key: value for key, value in switched_params.items() if key in target_param_names})
    explicit_switched_params = dict(carried_explicit_params)
    explicit_switched_params.update(overrides)
    switched_params = apply_protocol_runtime_defaults(target_tpl, switched_params, explicit_switched_params)
    target_family = str(target_tpl.protocol_family or "").upper()

    # HTTPS templates require SNI_HOST, but HTTP3 templates do not carry it.
    # When switching back from HTTP3, derive a stable host value from HOST_HEADER
    # or target_hosts so a protocol switch can succeed without redundant input.
    if target_family == "HTTPS":
        sni_host = str(switched_params.get("SNI_HOST") or "").strip()
        if not sni_host:
            derived_sni_host = extract_host_name(switched_params.get("HOST_HEADER")) or str(switched_params.get("target_hosts") or "").strip()
            if derived_sni_host:
                switched_params["SNI_HOST"] = derived_sni_host

    current_recipe = derive_effective_application_recipe(app_instance)
    switched_recipe = adapt_recipe_for_protocol_switch(current_recipe, target_tpl) if payload.preserve_runtime_profile else None
    switched_metric_profile = metric_profile_from_recipe(switched_recipe) if switched_recipe else None

    switched_app = dict(app_instance)
    switched_app["template_id"] = target_tpl.id
    switched_app["params"] = switched_params
    switched_app["recipe"] = switched_recipe.model_dump() if switched_recipe else None
    switched_app["metric_profile"] = switched_metric_profile.model_dump() if switched_metric_profile else None
    switched_app["updated_at"] = now_iso()

    needs_client, needs_server, usage_warnings = infer_application_bound_role_usage(project_id, app_instance["application_instance_id"], current_tpl, target_tpl)
    validation_errors = validate_application_runtime_requirements(switched_app, needs_client=needs_client, needs_server=needs_server)
    preview = preview_application_instance_render(switched_app)

    return {
        "source_template": present_manifest_template_data(current_tpl.model_dump()),
        "target_template": present_manifest_template_data(target_tpl.model_dump()),
        "source_effective_params": source_params,
        "target_effective_params": extract_effective_user_visible_params(switched_app),
        "switched_application_instance": present_application_instance(switched_app),
        "effective_recipe": preview["effective_recipe"],
        "effective_metric_profile": preview["effective_metric_profile"],
        "switch_summary": {
            "from_template_id": current_tpl.id,
            "to_template_id": target_tpl.id,
            "from_protocol_family": str(current_tpl.protocol_family or "").upper(),
            "to_protocol_family": str(target_tpl.protocol_family or "").upper(),
            "needs_client": needs_client,
            "needs_server": needs_server,
            "carried_param_keys": sorted(carried_params.keys()),
            "dropped_param_keys": dropped_params,
            "override_param_keys": sorted(overrides.keys()),
            "preserve_runtime_profile": payload.preserve_runtime_profile,
        },
        "warnings": usage_warnings,
        "errors": validation_errors,
        "application_block": preview["application_block"],
    }


def resolve_application_template_params(app_instance: Dict[str, Any]) -> Tuple[ManifestTemplate, Dict[str, Any]]:
    tpl = get_manifest_template(app_instance["template_id"])
    raw_params = normalize_application_params(app_instance.get("params") or {})
    params = dict(tpl.defaults or {})
    params.update(build_render_application_params(raw_params))
    params = apply_protocol_runtime_defaults(tpl, params, raw_params)
    return tpl, params


def coerce_port_param(value: Any, label: str) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{label} must be an integer")


def coerce_int_param(value: Any, label: str, default: Optional[int] = None) -> Optional[int]:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{label} must be an integer")


def validate_application_runtime_requirements(app_instance: Dict[str, Any], needs_client: bool, needs_server: bool) -> List[str]:
    tpl, params = resolve_application_template_params(app_instance)
    errors: List[str] = []
    protocol_family = str(getattr(tpl, "protocol_family", "") or "").upper()

    if protocol_family in {"HTTPS", "HTTP3"}:
        access_port = coerce_port_param(params.get("ACCESS_PORT"), "ACCESS_PORT")
        listen_port = coerce_port_param(params.get("LISTEN_PORT"), "LISTEN_PORT")
        if needs_client and access_port <= 0:
            errors.append(
                f"application_instance {app_instance['application_instance_id']} requires ACCESS_PORT > 0 when used by a client-side test path"
            )
        if needs_server and listen_port <= 0:
            errors.append(
                f"application_instance {app_instance['application_instance_id']} requires LISTEN_PORT > 0 when used by a server-side test path"
            )

        client_persistent = str(params.get("CLIENT_PERSISTENT", "on") or "on").strip().lower()
        if client_persistent not in {"on", "off"}:
            errors.append(
                f"application_instance {app_instance['application_instance_id']} has unsupported CLIENT_PERSISTENT={client_persistent}; only on and off are supported"
            )

        server_enable_persistent = str(params.get("SERVER_ENABLE_PERSISTENT", "on") or "on").strip().lower()
        if server_enable_persistent not in {"on", "off"}:
            errors.append(
                f"application_instance {app_instance['application_instance_id']} has unsupported SERVER_ENABLE_PERSISTENT={server_enable_persistent}; only on and off are supported"
            )

        if protocol_family == "HTTPS":
            normalize_close_mode_param(
                params.get("TCP_CLOSE_MODE", "FIN"),
                label=f"application_instance {app_instance['application_instance_id']} TCP_CLOSE_MODE",
            )

        max_redirects = coerce_int_param(params.get("MAX_REDIRECTS"), "MAX_REDIRECTS", default=10)
        if max_redirects is not None and not (0 <= max_redirects <= 10):
            errors.append(
                f"application_instance {app_instance['application_instance_id']} requires MAX_REDIRECTS within [0, 10]"
            )

        response_latency_mode = str(params.get("RESPONSE_LATENCY_MODE", "None") or "None").strip()
        if response_latency_mode not in {"Random", "Fixed", "None"}:
            errors.append(
                f"application_instance {app_instance['application_instance_id']} has unsupported RESPONSE_LATENCY_MODE={response_latency_mode}; only Random, Fixed, and None are supported"
            )
        elif response_latency_mode == "Fixed":
            response_latency = coerce_int_param(params.get("RESPONSE_LATENCY"), "RESPONSE_LATENCY", default=1000)
            if response_latency is None or not (0 <= response_latency <= 1000000):
                errors.append(
                    f"application_instance {app_instance['application_instance_id']} requires RESPONSE_LATENCY within [0, 1000000] milliseconds when RESPONSE_LATENCY_MODE=Fixed"
                )
        elif response_latency_mode == "Random":
            response_latency_mean = coerce_int_param(params.get("RESPONSE_LATENCY_MEAN"), "RESPONSE_LATENCY_MEAN", default=100)
            response_latency_stddev = coerce_int_param(
                params.get("RESPONSE_LATENCY_STANDARD_DEVIATION"),
                "RESPONSE_LATENCY_STANDARD_DEVIATION",
                default=1000,
            )
            if response_latency_mean is None or response_latency_mean < 0:
                errors.append(
                    f"application_instance {app_instance['application_instance_id']} requires RESPONSE_LATENCY_MEAN >= 0 when RESPONSE_LATENCY_MODE=Random"
                )
            if response_latency_stddev is None or response_latency_stddev < 0:
                errors.append(
                    f"application_instance {app_instance['application_instance_id']} requires RESPONSE_LATENCY_STANDARD_DEVIATION >= 0 when RESPONSE_LATENCY_MODE=Random"
                )

    if protocol_family == "HTTPS":
        tls_min_version = str(params.get("TLS_MIN_VERSION", "TLSv1.2") or "TLSv1.2").strip()
        tls_max_version = str(params.get("TLS_MAX_VERSION", "TLSv1.2") or "TLSv1.2").strip()
        tls_cipher = str(params.get("TLS_CIPHER", "AES128-SHA256") or "AES128-SHA256").strip()
        tls_ec_group = str(params.get("TLS_EC_GROUP", "secp256r1") or "secp256r1").strip()
        allowed_tls_versions = {"TLSv1.2", "TLSv1.3"}
        tls12_ec_groups = {"secp256r1", "secp384r1", "secp512r1"}
        tls13_ec_groups = {"secp256r1", "secp384r1", "X25519", "SecP256r1MLKEM768", "X25519MLKEM768"}

        if tls_min_version not in allowed_tls_versions:
            errors.append(
                f"application_instance {app_instance['application_instance_id']} has unsupported TLS_MIN_VERSION={tls_min_version}; only TLSv1.2 and TLSv1.3 are supported"
            )
        if tls_max_version not in allowed_tls_versions:
            errors.append(
                f"application_instance {app_instance['application_instance_id']} has unsupported TLS_MAX_VERSION={tls_max_version}; only TLSv1.2 and TLSv1.3 are supported"
            )

        if tls_max_version == "TLSv1.3":
            if tls_cipher != "TLS-AES-128-GCM-SHA256":
                errors.append(
                    f"application_instance {app_instance['application_instance_id']} requires TLS_CIPHER=TLS-AES-128-GCM-SHA256 when TLS_MAX_VERSION=TLSv1.3"
                )
            if tls_ec_group not in tls13_ec_groups:
                allowed_display = ", ".join(sorted(tls13_ec_groups))
                errors.append(
                    f"application_instance {app_instance['application_instance_id']} has unsupported TLS_EC_GROUP={tls_ec_group} for TLSv1.3; supported values are {allowed_display}"
                )
        elif tls_ec_group not in tls12_ec_groups:
            allowed_display = ", ".join(sorted(tls12_ec_groups))
            errors.append(
                f"application_instance {app_instance['application_instance_id']} has unsupported TLS_EC_GROUP={tls_ec_group} for TLSv1.2; supported values are {allowed_display}"
            )

    if protocol_family == "HTTP3":
        server_http_version = str(params.get("SERVER_HTTP_VERSION", "")).strip()
        if server_http_version and server_http_version not in {"1.1", "3.0"}:
            errors.append(
                f"application_instance {app_instance['application_instance_id']} has unsupported SERVER_HTTP_VERSION={server_http_version}; only 1.1 and 3.0 are supported"
            )
        if needs_server and server_http_version == "3.0":
            keyfile_name = str(params.get("KEYFILE_NAME", "") or "").strip()
            certfile_name = str(params.get("CERTFILE_NAME", "") or "").strip()
            if not keyfile_name:
                errors.append(
                    f"application_instance {app_instance['application_instance_id']} requires KEYFILE_NAME when SERVER_HTTP_VERSION=3.0 and the test case includes a server path"
                )
            if not certfile_name:
                errors.append(
                    f"application_instance {app_instance['application_instance_id']} requires CERTFILE_NAME when SERVER_HTTP_VERSION=3.0 and the test case includes a server path"
                )

    return errors


def save_application_instance(project_id: str, payload: ApplicationInstancePayload) -> Dict[str, Any]:
    assert_project_exists(project_id)
    _ = get_manifest_template(payload.template_id)
    data = payload.model_dump()
    data["params"] = normalize_application_params(data.get("params"))
    if data.get("recipe") is None and data.get("metric_profile") is not None:
        recipe = recipe_from_metric_profile(ApplicationMetricProfilePayload.model_validate(data["metric_profile"]))
        data["recipe"] = recipe.model_dump() if recipe else None
    elif data.get("recipe") is not None and data.get("metric_profile") is None:
        metric_profile = metric_profile_from_recipe(ApplicationRecipePayload.model_validate(data["recipe"]))
        data["metric_profile"] = metric_profile.model_dump() if metric_profile else None
    data["project_id"] = project_id
    data["updated_at"] = now_iso()
    return upsert_row("application_instances", payload.application_instance_id, data, project_id=project_id, template_id=payload.template_id)


def save_load_profile(project_id: str, payload: LoadProfilePayload) -> Dict[str, Any]:
    assert_project_exists(project_id)
    data = payload.model_dump()
    data["project_id"] = project_id
    data["updated_at"] = now_iso()
    return upsert_row("load_profiles", payload.load_profile_id, data, project_id=project_id)




def save_scenario_preset(project_id: str, payload: ScenarioPresetPayload) -> Dict[str, Any]:
    assert_project_exists(project_id)
    data = payload.model_dump()
    data["thread_policy_ref"] = None
    data["engine_launch_profile_ref"] = None
    data["project_id"] = project_id
    data["updated_at"] = now_iso()
    return upsert_row("scenario_presets", payload.scenario_preset_id, data, project_id=project_id)


def save_client(project_id: str, payload: ClientPayload) -> Dict[str, Any]:
    assert_project_exists(project_id)
    data = payload.model_dump()
    data["project_id"] = project_id
    data["updated_at"] = now_iso()
    return upsert_row("clients", payload.client_instance_id, data, project_id=project_id)


def save_server(project_id: str, payload: ServerPayload) -> Dict[str, Any]:
    assert_project_exists(project_id)
    data = payload.model_dump()
    data["project_id"] = project_id
    data["updated_at"] = now_iso()
    return upsert_row("servers", payload.server_instance_id, data, project_id=project_id)


def save_test_case(project_id: str, payload: TestCasePayload) -> Dict[str, Any]:
    assert_project_exists(project_id)
    data = payload.model_dump()
    data["thread_policy_ref"] = None
    data["engine_launch_profile_ref"] = None
    data["project_id"] = project_id
    data.setdefault("compiled_config_path", None)
    data.setdefault("last_compile_status", None)
    data.setdefault("last_run_id", None)
    data["updated_at"] = now_iso()
    return upsert_row("test_cases", payload.test_case_id, data, project_id=project_id)


def save_run(project_id: str, test_case_id: str, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    payload["project_id"] = project_id
    payload["test_case_id"] = test_case_id
    payload["updated_at"] = now_iso()
    return upsert_row("runs", run_id, payload, project_id=project_id, test_case_id=test_case_id)


def list_running_runs() -> List[Dict[str, Any]]:
    rows = list_rows("runs")
    active: List[Dict[str, Any]] = []
    for row in rows:
        row = refresh_run_process_state(row)
        if row.get("status") in {"pending", "running"}:
            active.append(row)
    return active


# =========================
# Compilation
# =========================

def build_interface_block(interface_obj: Dict[str, Any], local_interface_id: int) -> str:
    return f'''interface = {{
    interface_id = {local_interface_id};
    gratuitous_arp = true;
    vr_enabled = 0;
    vr_addrs = (
    );
}};'''


def build_subnet_block(subnet_obj: Dict[str, Any]) -> str:
    default_gw_line = ""
    if subnet_obj.get("default_gw"):
        default_gw_line = f'    default_gw = {to_libconfig_scalar(subnet_obj["default_gw"])};\n'
    return f'''subnet = {{
    name = {to_libconfig_scalar(subnet_obj["name"])};
    base_addr = {to_libconfig_scalar(subnet_obj["base_addr"])};
    count = {subnet_obj["count"]};
    network = {to_libconfig_scalar(subnet_obj["network"])};
    netmask = {subnet_obj["netmask"]};
{default_gw_line}    static_routes = (
    );
}};'''


def build_load_block(load_obj: Dict[str, Any], stress_type_override: Optional[str] = None) -> str:
    stages_text = []
    for st in load_obj["stages"]:
        stages_text.append(
            f'{{ stage = {to_libconfig_scalar(st["stage"])}; repetitions = {st["repetitions"]}; height = {st["height"]}; ramp_time = {st["ramp_time"]}; steady_time = {st["steady_time"]};}}'
        )
    stages_joined = ",\n                ".join(stages_text)
    stress_mode = render_stress_mode_name(load_obj.get("stress_mode", DEFAULT_STRESS_MODE))
    max_connection_attemps = load_obj.get("max_connection_attemps", DEFAULT_MAX_CONNECTION_ATTEMPTS)
    return f'''load = {{
    stress_type = {to_libconfig_scalar(stress_type_override or load_obj["stress_type"])};
    stress_mode = {to_libconfig_scalar(stress_mode)};
    percentage = 33.3;
    load_constraints = {{
        max_incoming_bandwidth = -1;
        max_simusers_born = -1;
        max_simusers_born_rate = -1;
        max_living_simusers = -1;
        max_connection_attemps = {max_connection_attemps};
        max_connection_rate = -1;
        max_open_connections = -1;
        max_connection_errors_percent = -1;
        max_transaction_attaemps = -1;
        max_transaction_rate = -1;
        max_transaction_errors_percet = -1;
    }};
    stress_stages = (
                {stages_joined}
    );
}};'''


def parse_cpu_id_sequence(raw: str) -> List[int]:
    cpus: List[int] = []
    for token in (raw or "").split(","):
        item = token.strip()
        if not item:
            continue
        if "-" in item:
            start_str, end_str = item.split("-", 1)
            start = int(start_str.strip())
            end = int(end_str.strip())
            if end < start:
                raise ValueError(f"闈炴硶 CPU 鑼冨洿: {item}")
            cpus.extend(range(start, end + 1))
        else:
            cpus.append(int(item))
    deduped: List[int] = []
    seen = set()
    for cpu in cpus:
        if cpu not in seen:
            deduped.append(cpu)
            seen.add(cpu)
    return deduped


def unique_in_order(values: Iterable[int]) -> List[int]:
    result: List[int] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def detect_numa0_cpu_sequence() -> Tuple[List[int], str, List[str], List[str]]:
    warnings: List[str] = []
    errors: List[str] = []

    if SYSTEM_NUMA0_CPUS:
        try:
            cpus = parse_cpu_id_sequence(SYSTEM_NUMA0_CPUS)
        except Exception as e:
            return [], "env_invalid", warnings, [f"failed to parse DPTEST_V2_NUMA0_CPUS: {e}"]
        return cpus, "env_override", warnings, errors

    if os.name != "posix":
        return [], f"unsupported_os:{os.name}", warnings, ["automatic NUMA0 CPU detection is only supported on Linux; set DPTEST_V2_NUMA0_CPUS explicitly"]

    node0_path = Path("/sys/devices/system/node/node0/cpulist")
    if node0_path.exists():
        raw = read_optional_text(node0_path)
        if not raw:
            return [], "linux_node0_empty", warnings, [f"{node0_path} is empty; cannot derive traffic worker cores"]
        try:
            return parse_cpu_id_sequence(raw), "linux_node0_cpulist", warnings, errors
        except Exception as e:
            return [], "linux_node0_invalid", warnings, [f"failed to parse {node0_path}: {e}"]

    online_path = Path("/sys/devices/system/cpu/online")
    if online_path.exists():
        raw = read_optional_text(online_path)
        if not raw:
            return [], "linux_online_empty", warnings, [f"{online_path} is empty; cannot derive traffic worker cores"]
        warnings.append("node0 cpulist is unavailable; falling back to /sys/devices/system/cpu/online as a single-NUMA CPU sequence")
        try:
            return parse_cpu_id_sequence(raw), "linux_cpu_online_fallback", warnings, errors
        except Exception as e:
            return [], "linux_online_invalid", warnings, [f"failed to parse {online_path}: {e}"]

    return [], "linux_missing_topology", warnings, ["missing NUMA/CPU topology information; set DPTEST_V2_NUMA0_CPUS"]


def derive_effective_thread_policy(client_count: int) -> Tuple[Dict[str, Any], List[str], List[str]]:
    warnings: List[str] = []
    errors: List[str] = []
    numa0_cpus, topology_source, topology_warnings, topology_errors = detect_numa0_cpu_sequence()
    warnings.extend(topology_warnings)
    errors.extend(topology_errors)

    management_core = DEFAULT_MANAGEMENT_CORE
    if not errors and not numa0_cpus:
        errors.append("NUMA0 CPU sequence is empty; cannot derive traffic worker cores")

    if numa0_cpus and management_core not in numa0_cpus:
        warnings.append(f"management_core={management_core} is not present in the NUMA0 CPU sequence; the default management core will still be used")

    traffic_pool = [cpu for cpu in numa0_cpus if cpu != management_core]
    if client_count < 0:
        errors.append("client_count is invalid")
    if client_count > len(traffic_pool):
        errors.append(
            f"client count ({client_count}) exceeds available NUMA0 traffic workers ({len(traffic_pool)}); "
            f"NUMA0 CPU sequence={numa0_cpus}"
        )

    selected_traffic_cores = traffic_pool[:client_count] if client_count > 0 else []
    policy = {
        "source": "derived_numa0",
        "topology_source": topology_source,
        "numa_node": 0,
        "numa0_cpu_sequence": numa0_cpus,
        "management_core": management_core,
        "traffic_worker_candidate_cores": traffic_pool,
        "traffic_worker_cores": selected_traffic_cores,
        "traffic_worker_requested_count": client_count,
        "crypto_worker_cores": list(DEFAULT_CRYPTO_WORKER_CORES),
        "worker_common_config": dict(DEFAULT_WORKER_COMMON_CONFIG),
    }
    return policy, warnings, errors


def resolve_effective_thread_policy(test_case: Dict[str, Any], client_count: int) -> Tuple[Dict[str, Any], List[str], List[str]]:
    policy, warnings, errors = derive_effective_thread_policy(client_count)
    legacy_ref = test_case.get("thread_policy_ref")
    if legacy_ref:
        warnings.append(f"thread_policy_ref={legacy_ref} is deprecated and ignored; thread settings are derived from NUMA0 and client count")
    return policy, warnings, errors


def build_thread_block(thread_policy: Dict[str, Any]) -> str:
    traffic_cores = thread_policy.get("traffic_worker_cores", []) or []
    crypto_cores = thread_policy.get("crypto_worker_cores", []) or []
    worker_common_config = thread_policy.get("worker_common_config", dict(DEFAULT_WORKER_COMMON_CONFIG)) or dict(DEFAULT_WORKER_COMMON_CONFIG)

    traffic_str = ", ".join(str(x) for x in traffic_cores)
    crypto_str = ", ".join(str(x) for x in crypto_cores)
    return f"""dptest_thread_config = {{
    triffic_worker_config = [{traffic_str}];
    crypto_worker_config = [{crypto_str}];
    worker_common_config = {{
        monitor_malloc = {to_libconfig_scalar(worker_common_config.get("monitor_malloc", DEFAULT_WORKER_COMMON_CONFIG["monitor_malloc"]))};
        gdb_debug_enable = {to_libconfig_scalar(worker_common_config.get("gdb_debug_enable", DEFAULT_WORKER_COMMON_CONFIG["gdb_debug_enable"]))};
    }};
}};"""


def parse_json_list_config(raw: str, label: str) -> List[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to parse {label}: {e}")
    if not isinstance(value, list):
        raise HTTPException(status_code=500, detail=f"{label} must be a JSON list")
    return [str(x) for x in value]


def parse_json_dict_config(raw: str, label: str) -> Dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to parse {label}: {e}")
    if not isinstance(value, dict):
        raise HTTPException(status_code=500, detail=f"{label} must be a JSON object")
    return {str(k): str(v) for k, v in value.items()}


def detect_total_memory_bytes() -> Tuple[Optional[int], str, List[str], List[str]]:
    warnings: List[str] = []
    errors: List[str] = []

    if SYSTEM_MEMORY_GB:
        try:
            value_gb = float(SYSTEM_MEMORY_GB)
        except Exception as e:
            return None, "env_invalid", warnings, [f"failed to parse DPTEST_V2_SYSTEM_MEMORY_GB: {e}"]
        if value_gb <= 0:
            return None, "env_invalid", warnings, ["DPTEST_V2_SYSTEM_MEMORY_GB must be greater than 0"]
        return int(value_gb * (1024 ** 3)), "env_override", warnings, errors

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        raw = read_optional_text(meminfo) or ""
        match = re.search(r"^MemTotal:\s+(\d+)\s+kB$", raw, re.MULTILINE)
        if not match:
            return None, "linux_meminfo_invalid", warnings, [f"failed to parse {meminfo}"]
        return int(match.group(1)) * 1024, "linux_meminfo", warnings, errors

    if os.name == "posix" and hasattr(os, "sysconf"):
        try:
            pages = int(os.sysconf("SC_PHYS_PAGES"))
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            if pages > 0 and page_size > 0:
                warnings.append("falling back to os.sysconf for total memory detection")
                return pages * page_size, "posix_sysconf", warnings, errors
        except Exception as e:
            warnings.append(f"os.sysconf memory detection failed: {e}")

    return None, f"unsupported_os:{os.name}", warnings, ["unable to detect total system memory; set DPTEST_V2_SYSTEM_MEMORY_GB"]


def derive_effective_engine_launch_profile() -> Tuple[Dict[str, Any], List[str], List[str]]:
    warnings: List[str] = []
    errors: List[str] = []

    total_memory_bytes, memory_source, mem_warnings, mem_errors = detect_total_memory_bytes()
    warnings.extend(mem_warnings)
    errors.extend(mem_errors)

    if total_memory_bytes is None:
        total_memory_bytes = 0

    usable_memory_bytes = int(total_memory_bytes * 0.75)
    usable_memory_gb = usable_memory_bytes / float(1024 ** 3) if usable_memory_bytes else 0.0
    socket_size_gb = next((spec for spec in reversed(ENGINE_SOCKET_SIZE_SPECS) if spec <= usable_memory_gb), None)
    if socket_size_gb is None:
        errors.append(
            f"usable engine memory ({usable_memory_gb:.2f} GiB) is below the minimum supported socket_size_gb={ENGINE_SOCKET_SIZE_SPECS[0]}"
        )
        socket_size_gb = ENGINE_SOCKET_SIZE_SPECS[0]

    profile = {
        "source": "derived_system_memory",
        "memory_source": memory_source,
        "total_memory_bytes": total_memory_bytes,
        "usable_memory_bytes": usable_memory_bytes,
        "usable_memory_gb": round(usable_memory_gb, 2),
        "socket_size_candidates_gb": list(ENGINE_SOCKET_SIZE_SPECS),
        "binary_path": DEFAULT_ENGINE_BINARY_PATH,
        "socket_size_gb": socket_size_gb,
        "memory_channels": DEFAULT_ENGINE_MEMORY_CHANNELS,
        "log_level": DEFAULT_ENGINE_LOG_LEVEL,
        "extra_app_args": parse_json_list_config(DEFAULT_ENGINE_EXTRA_APP_ARGS_JSON, "DPTEST_V2_ENGINE_EXTRA_APP_ARGS_JSON"),
        "extra_eal_args": parse_json_list_config(DEFAULT_ENGINE_EXTRA_EAL_ARGS_JSON, "DPTEST_V2_ENGINE_EXTRA_EAL_ARGS_JSON"),
        "env": parse_json_dict_config(DEFAULT_ENGINE_ENV_JSON, "DPTEST_V2_ENGINE_ENV_JSON"),
    }
    return profile, warnings, errors


def resolve_effective_engine_launch_profile(test_case: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str], List[str]]:
    profile, warnings, errors = derive_effective_engine_launch_profile()
    legacy_ref = test_case.get("engine_launch_profile_ref")
    if legacy_ref:
        warnings.append(f"engine_launch_profile_ref={legacy_ref} is deprecated and ignored; engine launch settings are derived from system memory and service defaults")
    return profile, warnings, errors


def _line_indent_at(text: str, idx: int) -> str:
    line_start = text.rfind("\n", 0, idx)
    line_start = 0 if line_start == -1 else line_start + 1
    j = line_start
    while j < len(text) and text[j] in " \t":
        j += 1
    return text[line_start:j]


def _line_start_at(text: str, idx: int) -> int:
    line_start = text.rfind("\n", 0, idx)
    return 0 if line_start == -1 else line_start + 1


def _extract_brace_block(text: str, brace_start: int) -> Tuple[int, int]:
    if brace_start < 0 or brace_start >= len(text) or text[brace_start] != "{":
        raise HTTPException(status_code=500, detail="鍐呴儴鍧楄В鏋愬け璐ワ細brace_start 闈炴硶")
    depth = 0
    end = -1
    for i in range(brace_start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise HTTPException(status_code=500, detail="internal block parse failed: block is not properly closed")
    return brace_start, end


def _find_action_block_ranges(text: str, action_name: str) -> List[Tuple[int, int]]:
    pattern = re.compile(rf'action_name\s*=\s*"{re.escape(action_name)}"', re.IGNORECASE)
    ranges: List[Tuple[int, int]] = []
    for m in pattern.finditer(text):
        brace_start = text.rfind("{", 0, m.start())
        if brace_start == -1:
            continue
        start, end = _extract_brace_block(text, brace_start)
        ranges.append((start, end))
    return ranges


def _find_named_block_ranges(text: str, name: str) -> List[Tuple[int, int]]:
    pattern = re.compile(rf'\b{re.escape(name)}\s*=\s*\{{', re.IGNORECASE)
    ranges: List[Tuple[int, int]] = []
    for m in pattern.finditer(text):
        brace_start = text.find("{", m.start())
        if brace_start == -1:
            continue
        start, end = _extract_brace_block(text, brace_start)
        ranges.append((start, end))
    return ranges


def _set_property_in_block(block_text: str, key: str, value: Any) -> str:
    scalar = to_libconfig_scalar(value)
    pattern = re.compile(rf'(\b{re.escape(key)}\s*=\s*)([^;]+)(;)', re.IGNORECASE)
    if pattern.search(block_text):
        return pattern.sub(rf'\g<1>{scalar}\g<3>', block_text, count=1)
    brace_pos = block_text.find("{")
    if brace_pos == -1:
        return block_text
    insert_indent = "    "
    after = block_text[brace_pos + 1 :]
    for line in after.splitlines():
        if line.strip():
            m = re.match(r'^[ \t]*', line)
            insert_indent = m.group(0) if m else "    "
            break
    insertion = f"\n{insert_indent}{key} = {scalar};"
    return block_text[: brace_pos + 1] + insertion + block_text[brace_pos + 1 :]


def _update_first_action_block(text: str, action_name: str, updater):
    ranges = _find_action_block_ranges(text, action_name)
    if not ranges:
        return text
    start, end = ranges[0]
    block = text[start:end]
    new_block = updater(block)
    return text[:start] + new_block + text[end:]


def _update_first_named_block(text: str, name: str, updater):
    ranges = _find_named_block_ranges(text, name)
    if not ranges:
        return text
    start, end = ranges[0]
    block = text[start:end]
    new_block = updater(block)
    return text[:start] + new_block + text[end:]


def _remove_action_blocks(text: str, action_name: str) -> str:
    ranges = _find_action_block_ranges(text, action_name)
    if not ranges:
        return text
    for start, end in reversed(ranges):
        rm_start, rm_end = start, end
        while rm_start > 0 and text[rm_start - 1].isspace():
            rm_start -= 1
        if rm_start > 0 and text[rm_start - 1] == ',':
            rm_start -= 1
            while rm_start > 0 and text[rm_start - 1].isspace():
                rm_start -= 1
        else:
            while rm_end < len(text) and text[rm_end].isspace():
                rm_end += 1
            if rm_end < len(text) and text[rm_end] == ',':
                rm_end += 1
        text = text[:rm_start] + text[rm_end:]
    return text


def _infer_application_method(application_block: str, tpl: ManifestTemplate) -> str:
    candidates = [tpl.request_method.upper().strip()] if tpl.request_method else []
    for item in ("GET", "POST", "HEAD"):
        if re.search(rf'action_name\s*=\s*"{item}"', application_block, re.IGNORECASE):
            candidates.append(item)
    for cand in candidates:
        if cand:
            return cand
    return "GET"


def _infer_protocol_family(application_block: str, tpl: ManifestTemplate) -> str:
    if tpl.protocol_family:
        return tpl.protocol_family.upper().strip()
    if re.search(r'action_name\s*=\s*"QUICClose"', application_block, re.IGNORECASE):
        return "HTTP3"
    if re.search(r'action_name\s*=\s*"StartTLS"', application_block, re.IGNORECASE):
        return "HTTPS"
    return "HTTP"


def _is_recipe_protocol_family_compatible(recipe_protocol_family: Optional[str], actual_protocol_family: str) -> bool:
    if not recipe_protocol_family:
        return True
    recipe_family = recipe_protocol_family.upper().strip()
    actual_family = actual_protocol_family.upper().strip()
    if recipe_family == actual_family:
        return True
    if recipe_family == "HTTP" and actual_family == "HTTPS":
        return True
    return False


def _ordered_action_blocks(text: str) -> List[Tuple[int, int, str]]:
    pattern = re.compile(r'action_name\s*=\s*"([^"]+)"', re.IGNORECASE)
    blocks: List[Tuple[int, int, str]] = []
    seen: set[int] = set()
    for m in pattern.finditer(text):
        brace_start = text.rfind("{", 0, m.start())
        if brace_start == -1:
            continue
        start, end = _extract_brace_block(text, brace_start)
        if start in seen:
            continue
        seen.add(start)
        blocks.append((start, end, m.group(1)))
    blocks.sort(key=lambda item: item[0])
    return blocks


def _find_request_action_index(application_block: str, request_action_name: Optional[str] = None) -> int:
    ordered = _ordered_action_blocks(application_block)
    if request_action_name:
        target = request_action_name.upper()
        for idx, (_, _, action_name) in enumerate(ordered):
            if action_name.upper() == target:
                return idx
    for idx, (_, _, action_name) in enumerate(ordered):
        if action_name.upper() in {"GET", "POST", "HEAD"}:
            return idx
    return 0


def _update_all_action_blocks(text: str, action_name: str, updater):
    ranges = _find_action_block_ranges(text, action_name)
    if not ranges:
        return text
    for start, end in reversed(ranges):
        block = text[start:end]
        new_block = updater(block)
        text = text[:start] + new_block + text[end:]
    return text


def _update_action_paths_in_order(text: str, action_name: str, request_paths: List[str]) -> str:
    if not request_paths:
        return text
    ordered = [item for item in _ordered_action_blocks(text) if item[2].upper() == action_name.upper()]
    if not ordered:
        return text
    for idx, (start, end, _) in reversed(list(enumerate(ordered))):
        if idx >= len(request_paths):
            continue
        block = text[start:end]
        new_block = _set_property_in_block(block, "request_path", request_paths[idx])
        text = text[:start] + new_block + text[end:]
    return text


POST_ACTION_DEFAULTS: Dict[str, Any] = {
    "source": "Client",
    "transaction_flag": "Continue",
    "content_md5_header": "off",
    "keep_alive": "on",
    "enable_chunked_encoding": "off",
    "default_size_for_http_chunked_responses": 64,
    "request_path": "/post-page",
    "content_type": "application/json",
    "post_content": "{a=1, b=2, c=3}",
    "post_content_file": "",
    "enable_rename_post_file": False,
    "import_post_content": "",
    "url_for_post_content": "",
    "min_amount_of_random_data": 0,
    "max_amount_of_random_data": 65535,
    "custom_host_header": "hi-myhttp.com",
    "custom_accept_header": "",
    "custom_encoding_header": "",
    "custom_language_header": "",
    "custom_user_agent": "",
    "name_of_cookie_to_save": "",
    "value_of_cookie_to_save": "",
    "custom_header_name": "x-custom-header",
    "custom_header_value": "customvalue",
}

GET_ACTION_DEFAULTS: Dict[str, Any] = {
    "source": "client",
    "transaction_flag": "start",
    "proxy_mode": "off",
    "request_path": "/index.html",
    "url_escape": False,
    "enable_persistent_http_sessions": "on",
    "custom_host_header": "",
    "custom_accept_header": "",
    "custom_encoding_header": "",
    "custom_language_header": "",
    "custom_user_agent": "",
    "custom_header_name": "x-custom-header",
    "custom_header_value": "customvalue",
}

POST_TPUT_DEFAULT_FILE = "post_128k.json"


def _parse_libconfig_scalar_text(raw: str) -> Any:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return text[1:-1]
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(text)
    except ValueError:
        return text


def _get_block_property_value(block_text: str, key: str, default: Any = None) -> Any:
    pattern = re.compile(rf'\b{re.escape(key)}\s*=\s*([^;]+);', re.IGNORECASE)
    match = pattern.search(block_text)
    if not match:
        return default
    return _parse_libconfig_scalar_text(match.group(1))


def _get_block_inner_indent(block_text: str) -> str:
    after = block_text[block_text.find("{") + 1 :] if "{" in block_text else block_text
    for line in after.splitlines():
        if line.strip():
            match = re.match(r'^[ \t]*', line)
            return match.group(0) if match else "    "
    return "    "


def _get_block_outer_indent(block_text: str) -> str:
    for line in block_text.splitlines():
        if line.strip():
            match = re.match(r'^[ \t]*', line)
            return match.group(0) if match else ""
    return ""


def _get_block_render_indents(block_text: str) -> Tuple[str, str]:
    outer_indent = _get_block_outer_indent(block_text)
    inner_indent = _get_block_inner_indent(block_text)
    if inner_indent.startswith(outer_indent) and len(inner_indent) > len(outer_indent):
        return outer_indent, inner_indent
    return outer_indent, outer_indent + "    "


def _render_request_action_block(
    flow_id: Any,
    action_name: str,
    source: str,
    outer_indent: str,
    inner_indent: str,
    params: List[Tuple[str, Any]],
) -> str:
    action_param_indent = inner_indent + "    "
    lines = [
        f"{outer_indent}{{",
        f"{inner_indent}flow_id = {to_libconfig_scalar(flow_id)};",
        f'{inner_indent}action_name = "{action_name}";',
        f'{inner_indent}source = "{source}";',
        f"{inner_indent}action_parameters = {{",
    ]
    for key, value in params:
        lines.append(f"{action_param_indent}{key} = {to_libconfig_scalar(value)};")
    lines.extend([
        f"{inner_indent}}};",
        f"{outer_indent}}}",
    ])
    return "\n".join(lines)


def _render_get_request_action_block(
    block_text: str,
    recipe: ApplicationRecipePayload,
) -> str:
    flow_id = _get_block_property_value(block_text, "flow_id", 0)
    outer_indent, inner_indent = _get_block_render_indents(block_text)
    source = str(_get_block_property_value(block_text, "source", GET_ACTION_DEFAULTS["source"]) or GET_ACTION_DEFAULTS["source"])
    current_persistent = _get_block_property_value(
        block_text,
        "enable_persistent_http_sessions",
        _get_block_property_value(block_text, "keep_alive", GET_ACTION_DEFAULTS["enable_persistent_http_sessions"]),
    )
    if recipe.connection.client_persistent is not None:
        persistent = "on" if recipe.connection.client_persistent else "off"
    else:
        persistent = str(current_persistent or GET_ACTION_DEFAULTS["enable_persistent_http_sessions"])

    request_path = recipe.request.request_path
    if request_path is None:
        request_path = _get_block_property_value(block_text, "request_path", GET_ACTION_DEFAULTS["request_path"])

    custom_header_name = recipe.request.custom_header_name
    if custom_header_name is None:
        custom_header_name = _get_block_property_value(block_text, "custom_header_name", GET_ACTION_DEFAULTS["custom_header_name"])

    custom_header_value = recipe.request.custom_header_value
    if custom_header_value is None:
        custom_header_value = _get_block_property_value(block_text, "custom_header_value", GET_ACTION_DEFAULTS["custom_header_value"])

    params = [
        ("transaction_flag", GET_ACTION_DEFAULTS["transaction_flag"]),
        ("proxy_mode", GET_ACTION_DEFAULTS["proxy_mode"]),
        ("request_path", request_path),
        ("url_escape", GET_ACTION_DEFAULTS["url_escape"]),
        ("enable_persistent_http_sessions", persistent),
        ("custom_host_header", _get_block_property_value(block_text, "custom_host_header", GET_ACTION_DEFAULTS["custom_host_header"])),
        ("custom_accept_header", _get_block_property_value(block_text, "custom_accept_header", GET_ACTION_DEFAULTS["custom_accept_header"])),
        ("custom_encoding_header", _get_block_property_value(block_text, "custom_encoding_header", GET_ACTION_DEFAULTS["custom_encoding_header"])),
        ("custom_language_header", _get_block_property_value(block_text, "custom_language_header", GET_ACTION_DEFAULTS["custom_language_header"])),
        ("custom_user_agent", _get_block_property_value(block_text, "custom_user_agent", GET_ACTION_DEFAULTS["custom_user_agent"])),
        ("custom_header_name", custom_header_name),
        ("custom_header_value", custom_header_value),
    ]
    return _render_request_action_block(flow_id, "GET", source, outer_indent, inner_indent, params)


def _render_post_request_action_block(
    block_text: str,
    recipe: ApplicationRecipePayload,
    metric_mode: str,
    preserve_existing: bool,
) -> str:
    flow_id = _get_block_property_value(block_text, "flow_id", 0)
    outer_indent, inner_indent = _get_block_render_indents(block_text)
    source = POST_ACTION_DEFAULTS["source"]

    current_keep_alive = _get_block_property_value(block_text, "keep_alive", POST_ACTION_DEFAULTS["keep_alive"])
    if recipe.connection.client_persistent is not None:
        keep_alive = "on" if recipe.connection.client_persistent else "off"
    elif preserve_existing:
        keep_alive = str(current_keep_alive or POST_ACTION_DEFAULTS["keep_alive"])
    else:
        keep_alive = POST_ACTION_DEFAULTS["keep_alive"]

    request_path = recipe.request.request_path
    if request_path is None:
        request_path = _get_block_property_value(block_text, "request_path", None) if preserve_existing else POST_ACTION_DEFAULTS["request_path"]

    content_type = recipe.request.content_type
    if content_type is None:
        content_type = _get_block_property_value(block_text, "content_type", None) if preserve_existing else POST_ACTION_DEFAULTS["content_type"]

    if metric_mode == "tput":
        post_content = ""
    else:
        post_content = recipe.request.post_content
        if post_content is None:
            post_content = _get_block_property_value(block_text, "post_content", None) if preserve_existing else POST_ACTION_DEFAULTS["post_content"]
        if post_content in (None, ""):
            post_content = POST_ACTION_DEFAULTS["post_content"]

    post_content_file = recipe.request.post_content_file
    if post_content_file is None and recipe.request.upload_file is not None:
        post_content_file = recipe.request.upload_file
    if post_content_file is None:
        current_post_content_file = _get_block_property_value(block_text, "post_content_file", None) if preserve_existing else POST_ACTION_DEFAULTS["post_content_file"]
        if metric_mode == "tput":
            post_content_file = current_post_content_file if str(current_post_content_file or "").strip() else POST_TPUT_DEFAULT_FILE
        else:
            post_content_file = current_post_content_file if current_post_content_file is not None else POST_ACTION_DEFAULTS["post_content_file"]

    enable_rename_post_file = recipe.request.enable_rename_post_file
    if enable_rename_post_file is None:
        enable_rename_post_file = _get_block_property_value(block_text, "enable_rename_post_file", None) if preserve_existing else POST_ACTION_DEFAULTS["enable_rename_post_file"]
    if enable_rename_post_file is None:
        enable_rename_post_file = POST_ACTION_DEFAULTS["enable_rename_post_file"]

    custom_header_name = recipe.request.custom_header_name
    if custom_header_name is None:
        custom_header_name = _get_block_property_value(block_text, "custom_header_name", None) if preserve_existing else POST_ACTION_DEFAULTS["custom_header_name"]
    if custom_header_name is None:
        custom_header_name = POST_ACTION_DEFAULTS["custom_header_name"]

    custom_header_value = recipe.request.custom_header_value
    if custom_header_value is None:
        custom_header_value = _get_block_property_value(block_text, "custom_header_value", None) if preserve_existing else POST_ACTION_DEFAULTS["custom_header_value"]
    if custom_header_value is None:
        custom_header_value = POST_ACTION_DEFAULTS["custom_header_value"]

    params = [
        ("transaction_flag", POST_ACTION_DEFAULTS["transaction_flag"]),
        ("content_md5_header", POST_ACTION_DEFAULTS["content_md5_header"]),
        ("keep_alive", keep_alive),
        ("enable_chunked_encoding", POST_ACTION_DEFAULTS["enable_chunked_encoding"]),
        ("default_size_for_http_chunked_responses", POST_ACTION_DEFAULTS["default_size_for_http_chunked_responses"]),
        ("request_path", request_path),
        ("content_type", content_type),
        ("post_content", post_content),
        ("post_content_file", post_content_file),
        ("enable_rename_post_file", enable_rename_post_file),
        ("import_post_content", POST_ACTION_DEFAULTS["import_post_content"]),
        ("url_for_post_content", POST_ACTION_DEFAULTS["url_for_post_content"]),
        ("min_amount_of_random_data", POST_ACTION_DEFAULTS["min_amount_of_random_data"]),
        ("max_amount_of_random_data", POST_ACTION_DEFAULTS["max_amount_of_random_data"]),
        ("custom_host_header", _get_block_property_value(block_text, "custom_host_header", POST_ACTION_DEFAULTS["custom_host_header"])),
        ("custom_accept_header", _get_block_property_value(block_text, "custom_accept_header", POST_ACTION_DEFAULTS["custom_accept_header"])),
        ("custom_encoding_header", _get_block_property_value(block_text, "custom_encoding_header", POST_ACTION_DEFAULTS["custom_encoding_header"])),
        ("custom_language_header", _get_block_property_value(block_text, "custom_language_header", POST_ACTION_DEFAULTS["custom_language_header"])),
        ("custom_user_agent", _get_block_property_value(block_text, "custom_user_agent", POST_ACTION_DEFAULTS["custom_user_agent"])),
        ("name_of_cookie_to_save", _get_block_property_value(block_text, "name_of_cookie_to_save", POST_ACTION_DEFAULTS["name_of_cookie_to_save"])),
        ("value_of_cookie_to_save", _get_block_property_value(block_text, "value_of_cookie_to_save", POST_ACTION_DEFAULTS["value_of_cookie_to_save"])),
        ("custom_header_name", custom_header_name),
        ("custom_header_value", custom_header_value),
    ]
    return _render_request_action_block(flow_id, "POST", source, outer_indent, inner_indent, params)


def _ensure_goto_before_terminal_close(
    application_block: str,
    goto_iteration: int,
    close_action_name: str,
    request_action_name: Optional[str] = None,
) -> str:
    request_action_index = _find_request_action_index(application_block, request_action_name)
    goto_ranges = _find_action_block_ranges(application_block, "Goto")
    if goto_ranges:
        return _update_first_action_block(
            application_block,
            "Goto",
            lambda block: _set_property_in_block(
                _set_property_in_block(block, "iteration", goto_iteration),
                "jumpto_action",
                request_action_index,
            ),
        )

    close_ranges = _find_action_block_ranges(application_block, close_action_name)
    lines = [
        "{",
        "    flow_id = 0;",
        '    action_name = "Goto";',
        '    source = "client";',
        '    action_parameters = {',
        '        transaction_flag = "continue";',
        f'        iteration = {goto_iteration};',
        f'        jumpto_action = {request_action_index};',
        '    };',
        "}",
    ]
    if close_ranges:
        start, _ = close_ranges[0]
        insert_at = _line_start_at(application_block, start)
        indent = _line_indent_at(application_block, start)
        rendered = "\n".join(indent + ln for ln in lines) + ",\n"
        if application_block[insert_at:start].strip():
            return application_block[:start] + "\n" + rendered + application_block[start:]
        return application_block[:insert_at] + rendered + application_block[insert_at:]

    actions_end = application_block.rfind(");")
    if actions_end == -1:
        return application_block
    indent = "                "
    rendered = "\n".join(indent + ln for ln in lines) + "\n"
    return application_block[:actions_end] + rendered + application_block[actions_end:]


def recipe_from_metric_profile(metric_profile: Optional[ApplicationMetricProfilePayload]) -> Optional[ApplicationRecipePayload]:
    if not metric_profile:
        return None
    return ApplicationRecipePayload(
        request_method=metric_profile.request_method,
        metric_mode=metric_profile.metric_mode,
        goto_iteration=metric_profile.goto_iteration,
        request=ApplicationRecipeRequestPayload(
            request_path=metric_profile.request_path,
            content_type=metric_profile.content_type,
            post_content=metric_profile.post_content,
            post_content_file=metric_profile.post_content_file,
            upload_file=metric_profile.upload_file,
            enable_rename_post_file=metric_profile.enable_rename_post_file,
            custom_header_name=metric_profile.custom_header_name,
            custom_header_value=metric_profile.custom_header_value,
        ),
        response=ApplicationRecipeResponsePayload(
            response_file=metric_profile.response_file,
            response_latency_mode=metric_profile.response_latency_mode,
            server_enable_persistent=metric_profile.server_enable_persistent,
        ),
        redirect=ApplicationRecipeRedirectPayload(follow_redirects=metric_profile.follow_redirects),
        tls=ApplicationRecipeTLSPayload(send_close_notify=metric_profile.send_close_notify),
        connection=ApplicationRecipeConnectionPayload(
            client_persistent=metric_profile.persistent,
            tcp_close_mode=metric_profile.tcp_close_mode,
        ),
    )


def metric_profile_from_recipe(recipe: Optional[ApplicationRecipePayload]) -> Optional[ApplicationMetricProfilePayload]:
    if not recipe:
        return None
    request_paths = recipe.request.request_paths or []
    request_path = recipe.request.request_path if recipe.request.request_path is not None else (request_paths[0] if request_paths else None)
    return ApplicationMetricProfilePayload(
        request_method=recipe.request_method,
        metric_mode=recipe.metric_mode,
        goto_iteration=recipe.goto_iteration,
        request_path=request_path,
        content_type=recipe.request.content_type,
        post_content=recipe.request.post_content,
        post_content_file=recipe.request.post_content_file,
        upload_file=recipe.request.upload_file,
        custom_header_name=recipe.request.custom_header_name,
        custom_header_value=recipe.request.custom_header_value,
        response_file=recipe.response.response_file,
        follow_redirects=recipe.redirect.follow_redirects,
        response_latency_mode=recipe.response.response_latency_mode,
        send_close_notify=recipe.tls.send_close_notify,
        tcp_close_mode=recipe.connection.tcp_close_mode,
        persistent=recipe.connection.client_persistent,
        server_enable_persistent=recipe.response.server_enable_persistent,
        enable_rename_post_file=recipe.request.enable_rename_post_file,
    )


def apply_application_recipe_to_application(
    application_block: str,
    tpl: ManifestTemplate,
    recipe: Optional[ApplicationRecipePayload],
) -> Tuple[str, Dict[str, Any]]:
    method = _infer_application_method(application_block, tpl)
    protocol_family = _infer_protocol_family(application_block, tpl)
    if not recipe:
        return application_block, {
            "request_method": method,
            "protocol_family": protocol_family,
            "metric_mode": None,
        }

    if not _is_recipe_protocol_family_compatible(recipe.protocol_family, protocol_family):
        raise HTTPException(status_code=400, detail=f"recipe.protocol_family={recipe.protocol_family} is not compatible with template protocol family {protocol_family}")

    target_method = str(recipe.request_method or method).upper().strip() or method
    if target_method != method and {target_method, method} != {"GET", "POST"}:
        raise HTTPException(status_code=400, detail=f"recipe.request_method={recipe.request_method} does not match template method {method}")

    metric_mode = recipe.metric_mode
    close_action_name = "QUICClose" if protocol_family == "HTTP3" else "Close"
    mutated = application_block
    effective_response_file = recipe.response.response_file
    effective_response_directory = recipe.response.response_directory

    if (
        tpl.id in {"dual_end_https_midbox_sm2_gcm_rps", "dual_end_http3_midbox_rps"}
        and target_method == "GET"
        and metric_mode == "tput"
        and effective_response_file is None
        and effective_response_directory is None
    ):
        effective_response_file = "response_128k.json"

    if target_method != method:
        mutated = _update_first_action_block(
            mutated,
            method,
            lambda block: _render_post_request_action_block(block, recipe, metric_mode, preserve_existing=False)
            if target_method == "POST"
            else _render_get_request_action_block(block, recipe),
        )
        method = target_method
    elif method == "POST":
        mutated = _update_first_action_block(
            mutated,
            "POST",
            lambda block: _render_post_request_action_block(block, recipe, metric_mode, preserve_existing=True),
        )

    if metric_mode == "tps":
        mutated = _remove_action_blocks(mutated, "Goto")
        effective_response_file = ""
        effective_response_directory = ""
    else:
        mutated = _ensure_goto_before_terminal_close(mutated, recipe.goto_iteration, close_action_name, request_action_name=method)

    if recipe.request.request_paths:
        mutated = _update_action_paths_in_order(mutated, method, recipe.request.request_paths)
    elif recipe.request.request_path is not None:
        mutated = _update_first_action_block(
            mutated,
            method,
            lambda block: _set_property_in_block(block, "request_path", recipe.request.request_path),
        )

    if recipe.redirect.follow_redirects is not None:
        mutated = _update_first_named_block(
            mutated,
            "protocol_parameters",
            lambda block: _set_property_in_block(block, "follow_redirects", recipe.redirect.follow_redirects),
        )

    if recipe.response.response_latency_mode is not None:
        mutated = _update_first_named_block(
            mutated,
            "protocol_parameters",
            lambda block: _set_property_in_block(block, "response_latency_mode", recipe.response.response_latency_mode),
        )

    if recipe.tls.send_close_notify is not None:
        mutated = _update_first_action_block(
            mutated,
            "StartTLS",
            lambda block: _set_property_in_block(block, "send_close_notify", 1 if recipe.tls.send_close_notify else 0),
        )

    if recipe.connection.tcp_close_mode is not None and close_action_name == "Close":
        mutated = _update_first_action_block(
            mutated,
            "Close",
            lambda block: _set_property_in_block(block, "fin_or_rst", recipe.connection.tcp_close_mode),
        )

    if recipe.connection.client_persistent is not None:
        if method in {"GET", "HEAD"}:
            mutated = _update_all_action_blocks(
                mutated,
                method,
                lambda block: _set_property_in_block(block, "enable_persistent_http_sessions", "on" if recipe.connection.client_persistent else "off"),
            )
        elif method == "POST":
            mutated = _update_all_action_blocks(
                mutated,
                "POST",
                lambda block: _set_property_in_block(block, "keep_alive", "on" if recipe.connection.client_persistent else "off"),
            )

    if recipe.response.server_enable_persistent is not None:
        mutated = _update_first_action_block(
            mutated,
            "Response 200 (OK)",
            lambda block: _set_property_in_block(block, "enable_persistent", "on" if recipe.response.server_enable_persistent else "off"),
        )

    if method == "HEAD" and metric_mode == "tput":
        raise HTTPException(status_code=400, detail="HEAD 鍦烘櫙涓嶆敮鎸佸垏鎹㈠埌鍚炲悙(tput)妯″紡")

    if effective_response_file is not None:
        mutated = _update_first_action_block(
            mutated,
            "Response 200 (OK)",
            lambda block: _set_property_in_block(block, "file_response_data", effective_response_file),
        )

    if effective_response_directory is not None:
        mutated = _update_first_action_block(
            mutated,
            "Response 200 (OK)",
            lambda block: _set_property_in_block(block, "directory_for_response", effective_response_directory),
        )

    summary = {
        "request_method": method,
        "protocol_family": protocol_family,
        "metric_mode": metric_mode,
        "close_action": close_action_name,
        "goto_iteration": recipe.goto_iteration if metric_mode in {"rps", "tput"} else None,
        "request_action_index": _find_request_action_index(mutated, method),
        "request_path": recipe.request.request_path,
        "request_paths": recipe.request.request_paths,
        "upload_file": recipe.request.upload_file,
        "response_file": effective_response_file,
        "response_directory": effective_response_directory,
        "follow_redirects": recipe.redirect.follow_redirects,
        "response_latency_mode": recipe.response.response_latency_mode,
        "send_close_notify": recipe.tls.send_close_notify,
        "tcp_close_mode": recipe.connection.tcp_close_mode,
        "client_persistent": recipe.connection.client_persistent,
        "server_enable_persistent": recipe.response.server_enable_persistent,
        "enable_rename_post_file": recipe.request.enable_rename_post_file,
    }
    return mutated, summary


def apply_metric_profile_to_application(
    application_block: str,
    tpl: ManifestTemplate,
    metric_profile: Optional[ApplicationMetricProfilePayload],
) -> Tuple[str, Dict[str, Any]]:
    return apply_application_recipe_to_application(application_block, tpl, recipe_from_metric_profile(metric_profile))


def preview_application_instance_render(app_instance: Dict[str, Any], override_metric_profile: Optional[ApplicationMetricProfilePayload] = None, override_recipe: Optional[ApplicationRecipePayload] = None) -> Dict[str, Any]:
    tpl, params = resolve_application_template_params(app_instance)

    missing_required = [k for k in tpl.required_params if k not in params or params[k] in (None, "")]
    if missing_required:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "application_instance 缂哄皯妯℃澘蹇呭～鍙傛暟",
                "application_instance_id": app_instance["application_instance_id"],
                "template_id": tpl.id,
                "missing_required": missing_required,
            },
        )

    template_path = TEMPLATE_DIR / tpl.file
    if not template_path.exists():
        raise HTTPException(status_code=404, detail=f"妯℃澘鏂囦欢涓嶅瓨鍦? {template_path}")

    raw = read_text_file(template_path)
    rendered, missing_placeholders = render_template(raw, params)
    if STRICT_PLACEHOLDER_CHECK and missing_placeholders:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "template still has unresolved placeholders after rendering",
                "application_instance_id": app_instance["application_instance_id"],
                "template_id": tpl.id,
                "missing_placeholders": missing_placeholders,
            },
        )

    application_block = extract_named_block(rendered, "application")
    current_effective_recipe = derive_effective_application_recipe(app_instance)
    if current_effective_recipe is None and (override_recipe is not None or override_metric_profile is not None):
        current_effective_recipe = infer_effective_application_recipe_from_rendered_block(app_instance, tpl, application_block)

    effective_recipe = override_recipe
    if effective_recipe is None and override_metric_profile is not None:
        effective_recipe = recipe_from_metric_profile(override_metric_profile)
    if effective_recipe is not None:
        if current_effective_recipe is None:
            current_effective_recipe = infer_effective_application_recipe_from_rendered_block(app_instance, tpl, application_block)
        effective_recipe = merge_application_recipe_override(current_effective_recipe, effective_recipe)
    else:
        effective_recipe = current_effective_recipe

    application_block, switch_summary = apply_application_recipe_to_application(application_block, tpl, effective_recipe)
    effective_metric_profile = metric_profile_from_recipe(effective_recipe)
    return {
        "application_block": application_block,
        "params": params,
        "template_placeholders": find_placeholders(raw),
        "missing_placeholders": missing_placeholders,
        "template": tpl,
        "switch_summary": switch_summary,
        "effective_recipe": effective_recipe.model_dump() if effective_recipe else None,
        "effective_metric_profile": effective_metric_profile.model_dump() if effective_metric_profile else None,
    }


def render_application_instance(app_instance: Dict[str, Any]) -> Tuple[str, Dict[str, Any], List[str], List[str]]:
    preview = preview_application_instance_render(app_instance)
    return (
        preview["application_block"],
        preview["params"],
        preview["template_placeholders"],
        preview["missing_placeholders"],
    )

def build_client_entry(project_id: str, client_obj: Dict[str, Any], interface_mapping: Dict[str, int], stress_type_override: Optional[str] = None) -> Dict[str, Any]:
    interface_obj = get_row("interfaces", client_obj["interface_ref"])
    subnet_obj = get_row("subnets", client_obj["subnet_ref"])
    app_instance = get_row("application_instances", client_obj["application_instance_ref"])
    load_obj = get_row("load_profiles", client_obj["load_profile_ref"])

    application_block, _, _, _ = render_application_instance(app_instance)
    local_interface_id = interface_mapping[client_obj["interface_ref"]]
    interface_block = build_interface_block(interface_obj, local_interface_id)
    subnet_block = build_subnet_block(subnet_obj)
    load_block = build_load_block(load_obj, stress_type_override=stress_type_override)

    entry = f'''{{
{indent_block(application_block, 1)}

{indent_block(subnet_block, 1)}

{indent_block(interface_block, 1)}

{indent_block(load_block, 1)}
}}'''
    return {
        "entry": entry,
        "subnet_ref": client_obj["subnet_ref"],
        "interface_ref": client_obj["interface_ref"],
    }


def build_server_entry(project_id: str, server_obj: Dict[str, Any], interface_mapping: Dict[str, int]) -> Dict[str, Any]:
    interface_obj = get_row("interfaces", server_obj["interface_ref"])
    subnet_obj = get_row("subnets", server_obj["subnet_ref"])
    app_instance = get_row("application_instances", server_obj["application_instance_ref"])

    application_block, _, _, _ = render_application_instance(app_instance)
    local_interface_id = interface_mapping[server_obj["interface_ref"]]
    interface_block = build_interface_block(interface_obj, local_interface_id)
    subnet_block = build_subnet_block(subnet_obj)

    entry = f'''{{
{indent_block(application_block, 1)}

{indent_block(subnet_block, 1)}

{indent_block(interface_block, 1)}
}}'''
    return {
        "entry": entry,
        "subnet_ref": server_obj["subnet_ref"],
        "interface_ref": server_obj["interface_ref"],
    }


def collect_used_interface_objects(project_id: str, client_ids: List[str], server_ids: List[str]) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[str]]:
    used_refs: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []

    for cid in client_ids:
        client_obj = get_row("clients", cid)
        iface = get_row("interfaces", client_obj["interface_ref"])
        if iface["project_id"] != project_id:
            errors.append(f"interface {iface['interface_id']} 涓嶅睘浜庤 project")
            continue
        used_refs[iface["interface_id"]] = iface

    for sid in server_ids:
        server_obj = get_row("servers", sid)
        iface = get_row("interfaces", server_obj["interface_ref"])
        if iface["project_id"] != project_id:
            errors.append(f"interface {iface['interface_id']} 涓嶅睘浜庤 project")
            continue
        used_refs[iface["interface_id"]] = iface

    ordered = sorted(
        used_refs.values(),
        key=lambda x: (x.get("dpdk_port_id", 10**9), x.get("pci_addr") or "", x.get("interface_id")),
    )
    mapping = {iface["interface_id"]: idx for idx, iface in enumerate(ordered)}
    return ordered, mapping, errors


def load_system_interface_inventory() -> Dict[str, Any]:
    source = "empty"
    interfaces: List[Dict[str, Any]] = []

    if SYSTEM_INTERFACE_INVENTORY_JSON:
        try:
            interfaces = json.loads(SYSTEM_INTERFACE_INVENTORY_JSON)
            source = "env_json"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"绯荤粺缃戝彛娓呭崟 JSON 瑙ｆ瀽澶辫触: {e}")
    elif SYSTEM_INTERFACE_INVENTORY_FILE:
        p = Path(SYSTEM_INTERFACE_INVENTORY_FILE)
        if not p.exists():
            raise HTTPException(status_code=500, detail=f"绯荤粺缃戝彛娓呭崟鏂囦欢涓嶅瓨鍦? {p}")
        try:
            interfaces = json.loads(read_text_file(p))
            source = "file"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"绯荤粺缃戝彛娓呭崟鏂囦欢瑙ｆ瀽澶辫触: {e}")
    else:
        configured = list_rows("interfaces")
        dedup: Dict[str, Dict[str, Any]] = {}
        for row in configured:
            key = row.get("interface_id")
            dedup[key] = {
                "device_id": key,
                "pci_addr": row.get("pci_addr"),
                "dpdk_port_id": row.get("dpdk_port_id"),
                "label": row.get("label") or row.get("interface_id"),
                "usable": bool(row.get("pci_addr")),
                "source_project_id": row.get("project_id"),
            }
        interfaces = sorted(
            dedup.values(),
            key=lambda x: (x.get("dpdk_port_id", 10**9), x.get("pci_addr") or "", x.get("device_id") or ""),
        )
        source = "configured_projects"

    return {"source": source, "interfaces": interfaces}


def read_optional_text(path: Path) -> Optional[str]:
    try:
        return read_text_file(path).strip()
    except Exception:
        return None


def read_optional_int(path: Path) -> Optional[int]:
    raw = read_optional_text(path)
    if raw in (None, "", "unknown"):
        return None
    try:
        value = int(raw)
    except Exception:
        return None
    return value if value >= 0 else None


def parse_speed_mbps(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    text = raw.strip()
    if not text or text.lower() in {"unknown", "unknown!", "n/a"}:
        return None
    match = ETHTOOL_SPEED_PATTERN.search(text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).upper()
    factor = {"K": 0.001, "M": 1, "G": 1000}.get(unit)
    if factor is None:
        return None
    return int(value * factor)


def parse_supported_link_modes_max_mbps(ethtool_output: str) -> Optional[int]:
    modes: List[int] = []
    capture = False
    for raw_line in ethtool_output.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if line.startswith("Supported link modes:"):
            capture = True
            stripped = line.split(":", 1)[1].strip()
        elif capture and line and not line.startswith((" ", "\t")) and ":" in line:
            break
        elif not capture:
            continue
        if not stripped:
            continue
        for match in SUPPORTED_LINK_MODE_PATTERN.finditer(stripped):
            try:
                modes.append(int(match.group(1)))
            except Exception:
                continue
    return max(modes) if modes else None


def run_optional_command(argv: List[str]) -> Tuple[int, str, str]:
    try:
        completed = subprocess.run(argv, text=True, capture_output=True, check=False)
        return completed.returncode, completed.stdout, completed.stderr
    except Exception as e:
        return -1, "", str(e)


def extract_pci_addr_from_path(path: Optional[Path]) -> Optional[str]:
    if not path:
        return None
    for candidate in [path, *path.parents]:
        name = candidate.name
        if PCI_ADDR_PATTERN.match(name):
            return name.lower()
    return None


def read_optional_hex_text(path: Path) -> Optional[str]:
    raw = read_optional_text(path)
    if raw in (None, ""):
        return None
    return raw.lower()


def resolve_optional_symlink_name(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return path.resolve().name
    except Exception:
        return None


def list_optional_dir_names(path: Path) -> List[str]:
    if not path.exists() or not path.is_dir():
        return []
    try:
        return sorted(entry.name for entry in path.iterdir() if entry.is_dir())
    except Exception:
        return []


def is_network_pci_class(class_code: Optional[str]) -> bool:
    return bool(class_code and class_code.startswith("0x02"))


def compute_live_binding_state(driver_name: Optional[str]) -> str:
    if driver_name in DPDK_BOUND_DRIVER_NAMES:
        return "DPDK-bound"
    if driver_name:
        return "kernel-bound"
    return "unbound"


def finalize_live_interface_record(record: Dict[str, Any]) -> Dict[str, Any]:
    finalized = dict(record)
    bound_driver = finalized.get("bound_driver") or finalized.get("driver")
    binding_state = compute_live_binding_state(bound_driver)
    base_label = finalized.get("base_label") or finalized.get("label") or finalized.get("interface_name") or finalized.get("pci_addr")

    finalized["bound_driver"] = bound_driver
    finalized["binding_state"] = binding_state
    finalized["is_dpdk_bound"] = binding_state == "DPDK-bound"
    finalized["base_label"] = base_label
    finalized["label"] = f"{base_label} (DPDK-bound)" if binding_state == "DPDK-bound" and base_label else base_label
    finalized["display_label"] = finalized.get("label")
    return finalized


def build_live_pci_device_record(device_path: Path) -> Optional[Dict[str, Any]]:
    pci_addr = extract_pci_addr_from_path(device_path)
    if not pci_addr:
        return None

    pci_class = read_optional_hex_text(device_path / "class")
    if not is_network_pci_class(pci_class):
        return None

    driver_name = resolve_optional_symlink_name(device_path / "driver")
    netdev_names = list_optional_dir_names(device_path / "net")
    primary_name = netdev_names[0] if netdev_names else None
    return finalize_live_interface_record({
        "interface_name": primary_name,
        "device_id": primary_name or pci_addr,
        "label": primary_name or pci_addr,
        "pci_addr": pci_addr,
        "pcie_addr": pci_addr,
        "driver": driver_name,
        "mac_addr": None,
        "operstate": None,
        "duplex": None,
        "mtu": None,
        "link_detected": None,
        "current_speed_mbps": None,
        "link_speed_mbps": None,
        "current_speed_source": None,
        "bandwidth_mbps": None,
        "bandwidth_source": None,
        "device_path": str(device_path),
        "usable": True,
        "discovery_source": "pci",
        "netdev_names": netdev_names,
        "kernel_netdev_present": bool(netdev_names),
        "bound_driver": driver_name,
        "pci_class": pci_class,
        "pci_vendor_id": read_optional_hex_text(device_path / "vendor"),
        "pci_device_id": read_optional_hex_text(device_path / "device"),
        "pci_subsystem_vendor_id": read_optional_hex_text(device_path / "subsystem_vendor"),
        "pci_subsystem_device_id": read_optional_hex_text(device_path / "subsystem_device"),
    })


def merge_live_interface_details(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(extra)
    merged.update(base)

    for key in ("netdev_names",):
        if not merged.get(key):
            merged[key] = extra.get(key) or base.get(key) or []

    if not merged.get("interface_name"):
        names = merged.get("netdev_names") or []
        if names:
            merged["interface_name"] = names[0]

    if not merged.get("device_id"):
        merged["device_id"] = merged.get("interface_name") or merged.get("pci_addr")
    if not merged.get("label"):
        merged["label"] = merged.get("interface_name") or merged.get("pci_addr")

    merged["kernel_netdev_present"] = bool(merged.get("netdev_names") or merged.get("interface_name"))
    if "discovery_source" not in merged:
        merged["discovery_source"] = "netdev"
    return finalize_live_interface_record(merged)


def collect_linux_pci_network_inventory() -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    base = Path("/sys/bus/pci/devices")
    if not base.exists():
        return {}, [f"{base} 不存在，无法补充采集已绑定到 DPDK 的 PCI 网卡"]

    devices: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    for device_path in sorted(base.iterdir(), key=lambda p: p.name):
        if not device_path.is_dir():
            continue
        try:
            record = build_live_pci_device_record(device_path)
        except Exception as e:
            warnings.append(f"读取 PCI 设备 {device_path.name} 失败: {e}")
            continue
        if not record:
            continue
        devices[record["pci_addr"]] = record
    return devices, warnings


def collect_linux_system_interfaces_live() -> Dict[str, Any]:
    base = Path("/sys/class/net")
    if not base.exists():
        return {
            "source": "linux_sysfs_unavailable",
            "collected_at": now_iso(),
            "interfaces": [],
            "warnings": [f"{base} 涓嶅瓨鍦紝鏃犳硶瀹炴椂閲囬泦绯荤粺缃戝彛"],
        }

    ethtool_path = shutil.which("ethtool")
    interfaces: List[Dict[str, Any]] = []
    warnings: List[str] = []
    pci_devices, pci_warnings = collect_linux_pci_network_inventory()
    warnings.extend(pci_warnings)

    for iface_dir in sorted(base.iterdir(), key=lambda p: p.name):
        if not iface_dir.is_dir():
            continue
        name = iface_dir.name
        if name == "lo":
            continue

        device_link = iface_dir / "device"
        device_path: Optional[Path] = None
        if device_link.exists():
            try:
                device_path = device_link.resolve()
            except Exception:
                device_path = None

        driver_name = None
        driver_link = iface_dir / "device" / "driver"
        if driver_link.exists():
            try:
                driver_name = driver_link.resolve().name
            except Exception:
                driver_name = None

        sysfs_speed = read_optional_int(iface_dir / "speed")
        duplex = read_optional_text(iface_dir / "duplex")
        operstate = read_optional_text(iface_dir / "operstate")
        mtu = read_optional_int(iface_dir / "mtu")
        mac_addr = read_optional_text(iface_dir / "address")
        link_detected: Optional[bool] = None
        current_speed_mbps = sysfs_speed
        current_speed_source = "sysfs" if sysfs_speed is not None else None
        bandwidth_mbps = None
        bandwidth_source = None

        if ethtool_path:
            code, stdout, stderr = run_optional_command([ethtool_path, name])
            if code == 0:
                for line in stdout.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("Speed:") and current_speed_mbps is None:
                        current_speed_mbps = parse_speed_mbps(stripped.split(":", 1)[1])
                        if current_speed_mbps is not None:
                            current_speed_source = "ethtool"
                    elif stripped.startswith("Duplex:") and not duplex:
                        duplex = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("Link detected:"):
                        link_value = stripped.split(":", 1)[1].strip().lower()
                        if link_value in {"yes", "true", "up"}:
                            link_detected = True
                        elif link_value in {"no", "false", "down"}:
                            link_detected = False
                bandwidth_mbps = parse_supported_link_modes_max_mbps(stdout)
                if bandwidth_mbps is not None:
                    bandwidth_source = "ethtool_supported_link_modes"
            elif stderr.strip():
                warnings.append(f"ethtool {name} 鎵ц澶辫触: {stderr.strip()}")

        if bandwidth_mbps is None and current_speed_mbps is not None:
            bandwidth_mbps = current_speed_mbps
            bandwidth_source = current_speed_source or "derived_from_speed"

        pci_addr = extract_pci_addr_from_path(device_path)
        netdev_record = {
            "interface_name": name,
            "device_id": name,
            "label": name,
            "pci_addr": pci_addr,
            "pcie_addr": pci_addr,
            "driver": driver_name,
            "mac_addr": mac_addr,
            "operstate": operstate,
            "duplex": duplex,
            "mtu": mtu,
            "link_detected": link_detected,
            "current_speed_mbps": current_speed_mbps,
            "link_speed_mbps": current_speed_mbps,
            "current_speed_source": current_speed_source,
            "bandwidth_mbps": bandwidth_mbps,
            "bandwidth_source": bandwidth_source,
            "device_path": str(device_path) if device_path else None,
            "usable": bool(pci_addr),
            "discovery_source": "netdev",
            "netdev_names": [name],
            "kernel_netdev_present": True,
            "is_dpdk_bound": bool(driver_name in DPDK_BOUND_DRIVER_NAMES),
            "bound_driver": driver_name,
        }
        if pci_addr and pci_addr in pci_devices:
            netdev_record = merge_live_interface_details(netdev_record, pci_devices.pop(pci_addr))
        interfaces.append(finalize_live_interface_record(netdev_record))

    interfaces.extend(pci_devices.values())
    interfaces.sort(key=lambda x: (x.get("pci_addr") or "zzzz", x.get("interface_name") or x.get("label") or ""))
    result: Dict[str, Any] = {
        "source": "live_linux_sysfs",
        "collected_at": now_iso(),
        "interfaces": interfaces,
    }
    if warnings:
        result["warnings"] = warnings
    return result


def collect_system_interface_inventory_live() -> Dict[str, Any]:
    if os.name != "posix":
        return {
            "source": f"unsupported_os:{os.name}",
            "collected_at": now_iso(),
            "interfaces": [],
            "warnings": ["live system interface collection is only supported on Linux hosts"],
        }
    return collect_linux_system_interfaces_live()


def build_launch_plan(project_id: str, test_case_id: str) -> Dict[str, Any]:
    result = validate_and_compile_test_case(project_id, test_case_id)
    if not result["ok"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "test_case 鏍￠獙澶辫触锛屾棤娉曠敓鎴?launch plan",
                "warnings": result["warnings"],
                "errors": result["errors"],
            },
        )

    test_case = result["test_case"]
    effective_thread_policy = result["effective_thread_policy"]
    effective_engine_launch_profile = result["effective_engine_launch_profile"]

    used_interfaces = result["used_interfaces"]
    interface_mapping = result["interface_mapping"]

    missing_pci = [iface["interface_id"] for iface in used_interfaces if not iface.get("pci_addr")]
    if missing_pci:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "浠ヤ笅 interface 缂哄皯 pci_addr锛屾棤娉曠敓鎴?-w 鍙傛暟",
                "missing_pci_interfaces": missing_pci,
            },
        )

    selected_traffic_cores = list(effective_thread_policy.get("traffic_worker_cores", []) or [])
    cores = unique_in_order([effective_thread_policy.get("management_core", DEFAULT_MANAGEMENT_CORE)] + selected_traffic_cores)
    core_arg = ",".join(str(c) for c in cores)

    binary_path = effective_engine_launch_profile.get("binary_path", DEFAULT_ENGINE_BINARY_PATH)
    app_args: List[str] = ["-s", str(effective_engine_launch_profile.get("socket_size_gb", 16))]
    app_args.extend(effective_engine_launch_profile.get("extra_app_args", []))

    eal_args: List[str] = [f"-n{effective_engine_launch_profile.get('memory_channels', DEFAULT_ENGINE_MEMORY_CHANNELS)}", f"-l{core_arg}", f"--log-level={effective_engine_launch_profile.get('log_level', DEFAULT_ENGINE_LOG_LEVEL)}"]
    for arg in effective_engine_launch_profile.get("extra_eal_args", []):
        eal_args.append(str(arg))
    for iface in used_interfaces:
        eal_args.extend(["-w", iface["pci_addr"]])

    full_argv = [binary_path] + app_args + ["--"] + eal_args
    env_overrides = {str(k): str(v) for k, v in (effective_engine_launch_profile.get("env") or {}).items()}
    return {
        "binary_path": binary_path,
        "app_args": app_args,
        "eal_args": eal_args,
        "full_argv": full_argv,
        "full_command": shlex.join(full_argv),
        "used_interfaces": used_interfaces,
        "interface_mapping": interface_mapping,
        "cores": cores,
        "selected_traffic_worker_cores": selected_traffic_cores,
        "effective_thread_policy": effective_thread_policy,
        "effective_engine_launch_profile": effective_engine_launch_profile,
        "engine_launch_profile_ref": test_case.get("engine_launch_profile_ref"),
        "env_overrides": env_overrides,
    }



def refresh_run_process_state(run_obj: Dict[str, Any]) -> Dict[str, Any]:
    pid = run_obj.get("pid")
    status_value = run_obj.get("status")
    if status_value not in {"pending", "running", "stopping"}:
        return run_obj

    if not pid:
        if status_value in {"pending", "running"}:
            return finalize_run_status(run_obj, "failed", reason="missing_pid")
        return run_obj

    state = get_pid_state(pid)
    if state is None:
        exit_code = waitpid_nonblocking(pid)
        if run_obj.get("stop_requested_at") or status_value == "stopping":
            return finalize_run_status(run_obj, "stopped", reason="process_exited_after_stop", exit_code=exit_code)
        if exit_code is not None and exit_code != 0:
            return finalize_run_status(run_obj, "failed", reason="process_exited", exit_code=exit_code)
        return finalize_run_status(run_obj, "finished", reason="process_exited", exit_code=exit_code)

    if state == "Z":
        exit_code = waitpid_nonblocking(pid)
        if run_obj.get("stop_requested_at") or status_value == "stopping":
            return finalize_run_status(run_obj, "stopped", reason="process_zombie_after_stop", exit_code=exit_code)
        if exit_code is not None and exit_code != 0:
            return finalize_run_status(run_obj, "failed", reason="process_zombie", exit_code=exit_code)
        return finalize_run_status(run_obj, "finished", reason="process_zombie", exit_code=exit_code)

    return run_obj


def launch_engine_process(launch_plan: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    stdout_path = RUN_LOG_DIR / f"{run_id}.stdout.log"
    stderr_path = RUN_LOG_DIR / f"{run_id}.stderr.log"
    stdout_f = open(stdout_path, "ab")
    stderr_f = open(stderr_path, "ab")
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in (launch_plan.get("env_overrides") or {}).items()})

    try:
        proc = subprocess.Popen(
            launch_plan["full_argv"],
            stdout=stdout_f,
            stderr=stderr_f,
            cwd=str(BASE_DIR),
            start_new_session=True,
            env=env,
        )
    except Exception:
        stdout_f.close()
        stderr_f.close()
        raise
    finally:
        stdout_f.close()
        stderr_f.close()

    if RUN_STARTUP_WAIT_SECONDS > 0:
        time.sleep(RUN_STARTUP_WAIT_SECONDS)

    exit_code = proc.poll()
    exited_early = exit_code is not None
    return {
        "pid": proc.pid,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "exited_early": exited_early,
        "exit_code": exit_code,
        "stdout_tail": read_file_tail(str(stdout_path)),
        "stderr_tail": read_file_tail(str(stderr_path)),
        "env_overrides": launch_plan.get("env_overrides") or {},
    }


def stop_run_process(run_obj: Dict[str, Any]) -> Dict[str, Any]:
    run_obj = refresh_run_process_state(run_obj)
    if run_obj.get("status") not in {"pending", "running", "stopping"}:
        return run_obj

    pid = run_obj.get("pid")
    if not pid:
        return finalize_run_status(run_obj, "stopped", reason="stop_without_pid")

    run_obj["status"] = "stopping"
    run_obj["stop_requested_at"] = now_iso()
    save_run(run_obj["project_id"], run_obj["test_case_id"], run_obj["run_id"], run_obj)

    term_sent = False
    kill_sent = False
    term_error = None
    kill_error = None

    try:
        os.killpg(pid, signal.SIGTERM)
        term_sent = True
    except ProcessLookupError:
        term_error = "process_group_not_found"
    except Exception as e:
        term_error = str(e)

    deadline = time.time() + RUN_STOP_WAIT_SECONDS
    while time.time() < deadline:
        refreshed = refresh_run_process_state(get_row("runs", run_obj["run_id"]))
        if refreshed.get("status") not in {"pending", "running", "stopping"}:
            refreshed.setdefault("stop_result", {})
            refreshed["stop_result"].update({
                "term_sent": term_sent,
                "kill_sent": kill_sent,
                "term_error": term_error,
                "kill_error": kill_error,
            })
            save_run(refreshed["project_id"], refreshed["test_case_id"], refreshed["run_id"], refreshed)
            return refreshed
        time.sleep(0.2)

    try:
        os.killpg(pid, signal.SIGKILL)
        kill_sent = True
    except ProcessLookupError:
        kill_error = "process_group_not_found"
    except Exception as e:
        kill_error = str(e)

    deadline = time.time() + 2.0
    while time.time() < deadline:
        refreshed = refresh_run_process_state(get_row("runs", run_obj["run_id"]))
        if refreshed.get("status") not in {"pending", "running", "stopping"}:
            refreshed.setdefault("stop_result", {})
            refreshed["stop_result"].update({
                "term_sent": term_sent,
                "kill_sent": kill_sent,
                "term_error": term_error,
                "kill_error": kill_error,
            })
            save_run(refreshed["project_id"], refreshed["test_case_id"], refreshed["run_id"], refreshed)
            return refreshed
        time.sleep(0.2)

    refreshed = get_row("runs", run_obj["run_id"])
    refreshed.setdefault("stop_result", {})
    refreshed["stop_result"].update({
        "term_sent": term_sent,
        "kill_sent": kill_sent,
        "term_error": term_error,
        "kill_error": kill_error,
        "message": "stop request was sent, but process state has not been fully collected yet",
    })
    save_run(refreshed["project_id"], refreshed["test_case_id"], refreshed["run_id"], refreshed)
    return refreshed


def validate_and_compile_test_case(project_id: str, test_case_id: str, stress_type_override: Optional[str] = None) -> Dict[str, Any]:
    project = assert_project_exists(project_id)
    test_case = get_row("test_cases", test_case_id)
    if test_case["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="test_case 涓嶅睘浜庤 project")

    warnings: List[str] = []
    errors: List[str] = []

    mode = test_case["mode"]
    client_ids = test_case.get("client_instance_ids", []) or []
    server_ids = test_case.get("server_instance_ids", []) or []

    if mode == "client_only" and server_ids:
        errors.append("client_only 妯″紡涓嬩笉鑳界粦瀹?server_instances")
    if mode == "server_only" and client_ids:
        errors.append("server_only 妯″紡涓嬩笉鑳界粦瀹?client_instances")

    if mode in {"client_only", "dual_end"} and not client_ids:
        warnings.append("褰撳墠娴嬭瘯鐢ㄤ緥鏈粦瀹氫换浣?client_instances")
    if mode in {"server_only", "dual_end"} and not server_ids:
        warnings.append("褰撳墠娴嬭瘯鐢ㄤ緥鏈粦瀹氫换浣?server_instances")

    effective_thread_policy, thread_warnings, thread_errors = resolve_effective_thread_policy(test_case, len(client_ids))
    effective_engine_launch_profile, engine_warnings, engine_errors = resolve_effective_engine_launch_profile(test_case)
    thread_block = build_thread_block(effective_thread_policy)
    warnings.extend(thread_warnings)
    errors.extend(thread_errors)
    warnings.extend(engine_warnings)
    errors.extend(engine_errors)

    app_role_usage: Dict[str, Dict[str, bool]] = {}
    for cid in client_ids:
        client_obj = get_row("clients", cid)
        if client_obj["project_id"] != project_id:
            errors.append(f"client {cid} 娑撳秴鐫樻禍搴ゎ嚉 project")
            continue
        app_id = client_obj["application_instance_ref"]
        usage = app_role_usage.setdefault(app_id, {"client": False, "server": False})
        usage["client"] = True

    for sid in server_ids:
        server_obj = get_row("servers", sid)
        if server_obj["project_id"] != project_id:
            errors.append(f"server {sid} 娑撳秴鐫樻禍搴ゎ嚉 project")
            continue
        app_id = server_obj["application_instance_ref"]
        usage = app_role_usage.setdefault(app_id, {"client": False, "server": False})
        usage["server"] = True

    for app_id, usage in app_role_usage.items():
        app_instance = get_row("application_instances", app_id)
        if app_instance["project_id"] != project_id:
            errors.append(f"application_instance {app_id} 娑撳秴鐫樻禍搴ゎ嚉 project")
            continue
        errors.extend(
            validate_application_runtime_requirements(
                app_instance,
                needs_client=bool(usage.get("client")),
                needs_server=bool(usage.get("server")),
            )
        )

    used_interfaces, interface_mapping, interface_errors = collect_used_interface_objects(project_id, client_ids, server_ids)
    errors.extend(interface_errors)

    used_subnets: Dict[str, str] = {}
    used_pci_addrs: Dict[str, str] = {}
    for iface in used_interfaces:
        if iface.get("pci_addr"):
            pci = iface["pci_addr"]
            if pci in used_pci_addrs:
                errors.append(f"pci_addr {pci} 琚噸澶嶇敤浜?{used_pci_addrs[pci]} 鍜?interface:{iface['interface_id']}")
            else:
                used_pci_addrs[pci] = f"interface:{iface['interface_id']}"

    client_entries: List[str] = []
    for cid in client_ids:
        client_obj = get_row("clients", cid)
        if client_obj["project_id"] != project_id:
            errors.append(f"client {cid} 涓嶅睘浜庤 project")
            continue
        subnet_ref = client_obj["subnet_ref"]
        if subnet_ref in used_subnets:
            errors.append(f"subnet {subnet_ref} 琚噸澶嶄娇鐢紝宸茶 {used_subnets[subnet_ref]} 鍗犵敤")
        else:
            used_subnets[subnet_ref] = f"client:{cid}"
        client_entry = build_client_entry(project_id, client_obj, interface_mapping, stress_type_override=stress_type_override)
        client_entries.append(client_entry["entry"])

    server_entries: List[str] = []
    for sid in server_ids:
        server_obj = get_row("servers", sid)
        if server_obj["project_id"] != project_id:
            errors.append(f"server {sid} 涓嶅睘浜庤 project")
            continue
        subnet_ref = server_obj["subnet_ref"]
        if subnet_ref in used_subnets:
            errors.append(f"subnet {subnet_ref} 琚噸澶嶄娇鐢紝宸茶 {used_subnets[subnet_ref]} 鍗犵敤")
        else:
            used_subnets[subnet_ref] = f"server:{sid}"
        server_entry = build_server_entry(project_id, server_obj, interface_mapping)
        server_entries.append(server_entry["entry"])

    clients_block = None
    if mode in {"client_only", "dual_end"}:
        clients_inner = ",\n    ".join(client_entries)
        clients_block = f'''dptest_client_config = {{
    clients = (
    {clients_inner}
    );

    servers = {{
    }};
}};'''

    servers_block = None
    if mode in {"server_only", "dual_end"}:
        servers_inner = ",\n    ".join(server_entries)
        servers_block = f'''dptest_server_config = {{
    servers = (
    {servers_inner}
    );
}};'''

    config_parts = [thread_block]
    if clients_block:
        config_parts.append(clients_block)
    if servers_block:
        config_parts.append(servers_block)
    compiled_text = "\n\n".join(config_parts) + "\n"

    return {
        "project": project,
        "test_case": test_case,
        "warnings": warnings,
        "errors": errors,
        "ok": len(errors) == 0,
        "compiled_text": compiled_text,
        "used_interfaces": used_interfaces,
        "interface_mapping": interface_mapping,
        "effective_thread_policy": effective_thread_policy,
        "effective_engine_launch_profile": effective_engine_launch_profile,
    }


def persist_artifact(test_case_id: str, compiled_text: str, output_filename: Optional[str], deployed: bool, validation: Dict[str, Any]) -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    artifact_id = f"artifact_{test_case_id}_{ts}"
    filename = output_filename or f"{test_case_id}_{ts}.conf"
    output_path = COMPILED_DIR / filename
    write_text_file(output_path, compiled_text)
    payload = {
        "artifact_id": artifact_id,
        "test_case_id": test_case_id,
        "compiled_at": now_iso(),
        "output_path": str(output_path),
        "deployed": deployed,
        "validation": validation,
    }
    upsert_row("artifacts", artifact_id, payload, test_case_id=test_case_id)
    return payload



# =========================
# Engine monitor / summary / diagnosis
# =========================

def parse_hms_to_seconds(value: str) -> int:
    if not value:
        return 0
    parts = value.strip().split(":")
    if len(parts) != 3:
        return 0
    try:
        h, m, s = [int(x) for x in parts]
        return h * 3600 + m * 60 + s
    except Exception:
        return 0


def load_stage_map() -> Dict[int, str]:
    result: Dict[int, str] = {}
    for item in STAGE_MAP_RAW.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        k, v = item.split(":", 1)
        try:
            result[int(k.strip())] = normalize_load_stage_name(v.strip(), allow_unknown=True)
        except Exception:
            continue
    return result


def normalize_load_stage_name(value: Any, allow_unknown: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("stage must be a string")
    normalized = re.sub(r"[\s_]+", " ", value).strip().lower()
    normalized_key = normalized.replace(" ", "")
    canonical = CANONICAL_LOAD_STAGE_NAMES.get(normalized)
    if canonical is None:
        canonical = CANONICAL_LOAD_STAGE_NAMES.get(normalized_key)
    if canonical is not None:
        return canonical
    if allow_unknown:
        return value.strip()
    allowed = ", ".join(sorted(set(CANONICAL_LOAD_STAGE_NAMES.values())))
    raise ValueError(f"unsupported stage '{value}', expected one of: {allowed}")


def safe_get(d: Dict[str, Any], *keys: str, default: Any = 0) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        if k not in cur:
            return default
        cur = cur[k]
    return cur


def fetch_engine_monitor() -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=ENGINE_MONITOR_TIMEOUT, trust_env=False) as client:
            resp = client.get(ENGINE_MONITOR_URL)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "璇诲彇鍘嬫祴寮曟搸 monitor 鎺ュ彛澶辫触",
                "monitor_url": ENGINE_MONITOR_URL,
                "error": str(e),
            },
        )
    except ValueError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "鍘嬫祴寮曟搸 monitor 鎺ュ彛杩斿洖鐨勪笉鏄悎娉?JSON",
                "monitor_url": ENGINE_MONITOR_URL,
                "error": str(e),
            },
        )


def normalize_monitor_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="鍘嬫祴寮曟搸 monitor 鍝嶅簲涓嶆槸瀵硅薄")
    code = raw.get("code")
    msg = raw.get("msg", "")
    data = raw.get("data")
    if code != 200 or not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail={
                "message": "鍘嬫祴寮曟搸 monitor 杩斿洖寮傚父",
                "engine_code": code,
                "engine_msg": msg,
                "engine_data": data,
            },
        )
    return data


def build_summary_from_monitor(raw: Dict[str, Any]) -> Dict[str, Any]:
    data = normalize_monitor_payload(raw)
    stage_map = load_stage_map()

    stage_id = safe_get(data, "stage_id", default=-1)
    stage_name = stage_map.get(stage_id, f"unknown_stage_{stage_id}")

    elapsed_str = safe_get(data, "duration", "elapsed", default="00:00:00")
    remaining_str = safe_get(data, "duration", "remaining", default="00:00:00")
    elapsed_sec = parse_hms_to_seconds(elapsed_str)
    remaining_sec = parse_hms_to_seconds(remaining_str)

    client_l2 = safe_get(data, "client", "l2", default={}) or {}
    client_tcp = safe_get(data, "client", "TCP", default={}) or {}
    client_tls = safe_get(data, "client", "TLS", default={}) or {}
    client_http = safe_get(data, "client", "HTTP", default={}) or {}

    server_l2 = safe_get(data, "server", "l2", default={}) or {}
    server_tcp = safe_get(data, "server", "TCP", default={}) or {}
    server_tls = safe_get(data, "server", "TLS", default={}) or {}
    server_http = safe_get(data, "server", "HTTP", default={}) or {}

    http_attempted = int(client_http.get("transactions_attempted", 0) or 0)
    http_successful = int(client_http.get("transactions_successful", 0) or 0)
    http_rps = float(client_http.get("requests_per_sec", 0) or 0)

    tls_total = int(client_tls.get("total_handshakes", 0) or 0)
    tls_failures = int(client_tls.get("handshake_failures", 0) or 0)
    tls_crypto_failures = int(client_tls.get("crypto_failures", 0) or 0)
    tls_hps = float(client_tls.get("handshakes_per_sec", 0) or 0)

    tcp_cps = float(client_tcp.get("connections_per_sec", 0) or 0)
    tcp_open = int(client_tcp.get("open_connections", 0) or 0)
    tcp_closed_ok = int(client_tcp.get("closed_no_error", 0) or 0)
    tcp_closed_err = int(client_tcp.get("closed_with_error", 0) or 0)

    http_success_rate = round(http_successful / http_attempted, 4) if http_attempted > 0 else None
    tls_failure_rate = round(tls_failures / tls_total, 4) if tls_total > 0 else 0.0

    status_value = "running"
    if remaining_sec <= 0:
        status_value = "finished"
    if elapsed_sec == 0 and remaining_sec == 0 and http_attempted == 0 and tls_total == 0 and tcp_closed_ok == 0 and tcp_closed_err == 0:
        status_value = "idle"

    return {
        "status": status_value,
        "stage": {"id": stage_id, "name": stage_name},
        "duration": {
            "elapsed": elapsed_str,
            "elapsed_seconds": elapsed_sec,
            "remaining": remaining_str,
            "remaining_seconds": remaining_sec,
        },
        "client": {
            "l2": {
                "packets_sent": int(client_l2.get("packets_sent", 0) or 0),
                "packets_received": int(client_l2.get("packets_received", 0) or 0),
                "bytes_sent": int(client_l2.get("bytes_sent", 0) or 0),
                "bytes_received": int(client_l2.get("bytes_received", 0) or 0),
            },
            "tcp": {
                "connections_per_sec": tcp_cps,
                "open_connections": tcp_open,
                "closed_no_error": tcp_closed_ok,
                "closed_with_error": tcp_closed_err,
            },
            "tls": {
                "handshakes_per_sec": tls_hps,
                "total_handshakes": tls_total,
                "session_reuse": int(client_tls.get("session_reuse", 0) or 0),
                "handshake_failures": tls_failures,
                "crypto_failures": tls_crypto_failures,
                "failure_rate": tls_failure_rate,
            },
            "http": {
                "requests_per_sec": http_rps,
                "transactions_attempted": http_attempted,
                "transactions_successful": http_successful,
                "success_rate": http_success_rate,
            },
        },
        "server": {
            "l2": {
                "packets_sent": int(server_l2.get("packets_sent", 0) or 0),
                "packets_received": int(server_l2.get("packets_received", 0) or 0),
                "bytes_sent": int(server_l2.get("bytes_sent", 0) or 0),
                "bytes_received": int(server_l2.get("bytes_received", 0) or 0),
            },
            "tcp": {
                "connections_per_sec": float(server_tcp.get("connections_per_sec", 0) or 0),
                "open_connections": int(server_tcp.get("open_connections", 0) or 0),
                "closed_no_error": int(server_tcp.get("closed_no_error", 0) or 0),
                "closed_with_error": int(server_tcp.get("closed_with_error", 0) or 0),
            },
            "tls": {
                "handshakes_per_sec": float(server_tls.get("handshakes_per_sec", 0) or 0),
                "total_handshakes": int(server_tls.get("total_handshakes", 0) or 0),
                "session_reuse": int(server_tls.get("session_reuse", 0) or 0),
                "handshake_failures": int(server_tls.get("handshake_failures", 0) or 0),
                "crypto_failures": int(server_tls.get("crypto_failures", 0) or 0),
            },
            "http": {
                "responses_per_sec": float(server_http.get("responses_per_sec", 0) or 0),
                "transactions_attempted": int(server_http.get("transactions_attempted", 0) or 0),
                "transactions_successful": int(server_http.get("transactions_successful", 0) or 0),
            },
        },
        "highlights": {
            "client_requests_per_sec": http_rps,
            "client_http_success_rate": http_success_rate,
            "client_tls_failure_rate": tls_failure_rate,
            "client_open_connections": tcp_open,
            "client_total_transactions": http_attempted,
            "client_successful_transactions": http_successful,
        },
        "source": {
            "monitor_url": ENGINE_MONITOR_URL,
            "generated_at": now_iso(),
        },
    }


def build_diagnosis_from_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    status_value = summary.get("status", "unknown")
    stage_name = safe_get(summary, "stage", "name", default="unknown")
    elapsed_sec = int(safe_get(summary, "duration", "elapsed_seconds", default=0) or 0)
    remaining_sec = int(safe_get(summary, "duration", "remaining_seconds", default=0) or 0)

    http_attempted = int(safe_get(summary, "client", "http", "transactions_attempted", default=0) or 0)
    http_successful = int(safe_get(summary, "client", "http", "transactions_successful", default=0) or 0)
    http_rps = float(safe_get(summary, "client", "http", "requests_per_sec", default=0) or 0)
    http_success_rate = safe_get(summary, "client", "http", "success_rate", default=None)

    tls_total = int(safe_get(summary, "client", "tls", "total_handshakes", default=0) or 0)
    tls_failures = int(safe_get(summary, "client", "tls", "handshake_failures", default=0) or 0)
    tls_crypto_failures = int(safe_get(summary, "client", "tls", "crypto_failures", default=0) or 0)
    tls_failure_rate = float(safe_get(summary, "client", "tls", "failure_rate", default=0.0) or 0.0)

    tcp_open = int(safe_get(summary, "client", "tcp", "open_connections", default=0) or 0)
    tcp_closed_err = int(safe_get(summary, "client", "tcp", "closed_with_error", default=0) or 0)
    tcp_cps = float(safe_get(summary, "client", "tcp", "connections_per_sec", default=0) or 0)

    issues: List[Dict[str, Any]] = []
    suggestions: List[str] = []
    overall_status = "pass"
    bottleneck_hint = "unknown"

    if tls_failures > 0 or tls_crypto_failures > 0:
        overall_status = "fail"
        bottleneck_hint = "tls_or_certificate_compatibility"
        issues.append({
            "severity": "high",
            "type": "tls_failures_detected",
            "message": "妫€娴嬪埌 TLS 鎻℃墜澶辫触鎴栧姞瑙ｅ瘑澶辫触",
            "evidence": {
                "handshake_failures": tls_failures,
                "crypto_failures": tls_crypto_failures,
                "failure_rate": tls_failure_rate,
            },
        })
        suggestions.extend([
            "check TLS version, cipher or group, SNI, certificate chain, and peer compatibility",
            "compare results after changing TLS parameters within the same template",
        ])

    if tcp_closed_err > 0:
        if overall_status != "fail":
            overall_status = "warn"
            bottleneck_hint = "network_or_connection_stability"
        issues.append({
            "severity": "medium",
            "type": "tcp_errors_detected",
            "message": "妫€娴嬪埌 TCP 閿欒鍏抽棴",
            "evidence": {
                "closed_with_error": tcp_closed_err,
                "connections_per_sec": tcp_cps,
                "open_connections": tcp_open,
            },
        })
        suggestions.append("妫€鏌ラ摼璺€佺鍙ｅ彲杈炬€с€佽繛鎺ラ檺鍒跺拰涓棿璁惧琛屼负")

    if http_attempted > 0 and http_success_rate is not None and http_success_rate < 1.0:
        if overall_status == "pass":
            overall_status = "warn"
            bottleneck_hint = "http_transaction_failures"
        issues.append({
            "severity": "medium",
            "type": "http_success_rate_drop",
            "message": "HTTP 浜嬪姟鎴愬姛鐜囦綆浜?100%",
            "evidence": {
                "transactions_attempted": http_attempted,
                "transactions_successful": http_successful,
                "success_rate": http_success_rate,
            },
        })
        suggestions.append("check the server application, gateway or proxy, HTTP status metrics, and upstream dependencies")

    if status_value == "running" and elapsed_sec > 10 and remaining_sec > 0:
        low_activity = (
            http_rps == 0
            and tcp_cps == 0
            and safe_get(summary, "client", "tls", "handshakes_per_sec", default=0) == 0
        )
        very_small_total = http_attempted <= 1 and tls_total <= 1 and tcp_closed_err == 0

        if low_activity and very_small_total:
            if overall_status == "pass":
                overall_status = "info"
                bottleneck_hint = "very_low_load_or_not_generating_traffic"
            issues.append({
                "severity": "info",
                "type": "very_low_runtime_activity",
                "message": "the run is active, but there is almost no new traffic within the current time window",
                "evidence": {
                    "stage": stage_name,
                    "elapsed_seconds": elapsed_sec,
                    "requests_per_sec": http_rps,
                    "connections_per_sec": tcp_cps,
                    "transactions_attempted": http_attempted,
                    "total_handshakes": tls_total,
                },
            })
            suggestions.extend([
                "confirm the load parameters match expectations, such as concurrency, connection rate, transaction rate, and stage height",
                "confirm template parameters such as TARGET_HOST, REQUEST_PATH, and HOST_HEADER are correct",
            ])

    if not issues:
        bottleneck_hint = "no_obvious_errors_detected"
        suggestions.append("no obvious errors are detected right now; continue observing behavior during the steady State stage")

    return {
        "overall_status": overall_status,
        "bottleneck_hint": bottleneck_hint,
        "issues": issues,
        "suggestions": suggestions,
        "based_on": {
            "status": status_value,
            "stage": stage_name,
            "generated_at": now_iso(),
        },
    }


def snapshot_run_from_monitor(run_obj: Dict[str, Any]) -> Dict[str, Any]:
    run_obj = refresh_run_process_state(run_obj)

    try:
        raw = fetch_engine_monitor()
        summary = build_summary_from_monitor(raw)
        diagnosis = build_diagnosis_from_summary(summary)
        run_obj["summary_snapshot"] = summary
        run_obj["diagnosis_snapshot"] = diagnosis

        summary_status = summary.get("status")
        if summary_status == "finished":
            run_obj["status"] = "finished"
            run_obj["ended_at"] = run_obj.get("ended_at") or now_iso()
        elif summary_status == "idle":
            if run_obj.get("status") in {"pending", "running"}:
                # 鑻ヨ繘绋嬩粛娲荤潃浣?monitor 涓虹┖锛屼繚瀹堜繚鎸?running锛涘惁鍒欏凡鍦?refresh_run_process_state 鏍囨垚 finished
                if run_obj.get("pid") and is_pid_alive(run_obj.get("pid")):
                    run_obj["status"] = "running"
                else:
                    run_obj["status"] = "finished"
                    run_obj["ended_at"] = run_obj.get("ended_at") or now_iso()
        else:
            if run_obj.get("status") != "finished":
                run_obj["status"] = "running"
    except HTTPException:
        # Fall back to local process-state refresh if monitor data is temporarily unavailable.
        run_obj = refresh_run_process_state(run_obj)

    run_obj["updated_at"] = now_iso()
    save_run(run_obj["project_id"], run_obj["test_case_id"], run_obj["run_id"], run_obj)
    return run_obj


# =========================
# Startup
# =========================

@app.on_event("startup")
def on_startup() -> None:
    ensure_dirs()
    init_db()


# =========================
# Health
# =========================

@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "dptest-agent-service-v2",
        "db_path": str(DB_PATH),
        "data_dir": str(DATA_DIR),
        "template_dir": str(TEMPLATE_DIR),
        "manifest_file": str(MANIFEST_FILE),
        "compiled_dir": str(COMPILED_DIR),
        "run_log_dir": str(RUN_LOG_DIR),
        "deploy_file": str(DEPLOY_FILE),
        "engine_monitor_url": ENGINE_MONITOR_URL,
        "auth_enabled": bool(AGENT_TOKEN),
        "hostname": socket.gethostname(),
        "sqlite_version": sqlite3.sqlite_version,
        "sqlite_module_version": sqlite3.version,
    }


# =========================
# Application templates (system-level)
# =========================

@app.get("/v2/application-templates", dependencies=[Depends(protected)])
def v2_list_application_templates() -> Dict[str, Any]:
    manifest = load_manifest()
    data = manifest.model_dump()
    data["templates"] = [present_manifest_template_data(item) for item in data.get("templates", [])]
    return data


@app.get("/v2/application-templates/{template_id}", dependencies=[Depends(protected)])
def v2_get_application_template(template_id: str) -> Dict[str, Any]:
    tpl = get_manifest_template(template_id)
    template_path = TEMPLATE_DIR / tpl.file
    content = read_text_file(template_path)
    placeholders = find_placeholders(content)
    data = tpl.model_dump()
    data["resolved_template_path"] = str(template_path)
    data["actual_placeholders_in_file"] = placeholders
    return present_manifest_template_data(data)


# =========================
# System discovery
# =========================

@app.get("/v2/system/interfaces/discovery", dependencies=[Depends(protected)])
def v2_system_interfaces_discovery() -> Dict[str, Any]:
    return {
        "ok": True,
        "inventory": load_system_interface_inventory(),
    }


@app.get("/v2/system/interfaces/live", dependencies=[Depends(protected)])
def v2_system_interfaces_live() -> Dict[str, Any]:
    return {
        "ok": True,
        "inventory": collect_system_interface_inventory_live(),
    }


# =========================
# Projects
# =========================

@app.post("/v2/projects", dependencies=[Depends(protected)])
def v2_create_project(payload: ProjectCreate) -> Dict[str, Any]:
    return {"ok": True, "project": save_project(payload)}


@app.get("/v2/projects", dependencies=[Depends(protected)])
def v2_list_projects() -> Dict[str, Any]:
    return {"projects": list_rows("projects")}


@app.get("/v2/projects/{project_id}", dependencies=[Depends(protected)])
def v2_get_project(project_id: str) -> Dict[str, Any]:
    return get_row("projects", project_id)


@app.delete("/v2/projects/{project_id}", dependencies=[Depends(protected)])
def v2_delete_project(project_id: str) -> Dict[str, Any]:
    return cascade_delete_project(project_id)


# =========================
# Resource routes
# =========================

@app.post("/v2/projects/{project_id}/thread-policies", dependencies=[Depends(protected)])
def v2_create_thread_policy(project_id: str, payload: ThreadPolicyPayload) -> Dict[str, Any]:
    return {"ok": True, "thread_policy": save_thread_policy(project_id, payload)}


@app.get("/v2/projects/{project_id}/thread-policies", dependencies=[Depends(protected)])
def v2_list_thread_policies(project_id: str) -> Dict[str, Any]:
    assert_project_exists(project_id)
    return {"thread_policies": list_rows("thread_policies", project_id)}


@app.get("/v2/projects/{project_id}/thread-policies/{thread_policy_id}", dependencies=[Depends(protected)])
def v2_get_thread_policy(project_id: str, thread_policy_id: str) -> Dict[str, Any]:
    obj = get_row("thread_policies", thread_policy_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="thread_policy 涓嶅睘浜庤 project")
    return obj


@app.put("/v2/projects/{project_id}/thread-policies/{thread_policy_id}", dependencies=[Depends(protected)])
def v2_update_thread_policy(project_id: str, thread_policy_id: str, payload: ThreadPolicyPayload) -> Dict[str, Any]:
    if payload.thread_policy_id != thread_policy_id:
        raise HTTPException(status_code=400, detail="thread_policy_id does not match the path parameter")
    return {"ok": True, "thread_policy": save_thread_policy(project_id, payload)}


@app.delete("/v2/projects/{project_id}/thread-policies/{thread_policy_id}", dependencies=[Depends(protected)])
def v2_delete_thread_policy(project_id: str, thread_policy_id: str) -> Dict[str, Any]:
    obj = get_row("thread_policies", thread_policy_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="thread_policy 涓嶅睘浜庤 project")
    delete_row("thread_policies", thread_policy_id)
    return {"ok": True, "deleted": thread_policy_id}


@app.post("/v2/projects/{project_id}/engine-launch-profiles", dependencies=[Depends(protected)])
def v2_create_engine_launch_profile(project_id: str, payload: EngineLaunchProfilePayload) -> Dict[str, Any]:
    return {"ok": True, "engine_launch_profile": save_engine_launch_profile(project_id, payload)}


@app.get("/v2/projects/{project_id}/engine-launch-profiles", dependencies=[Depends(protected)])
def v2_list_engine_launch_profiles(project_id: str) -> Dict[str, Any]:
    assert_project_exists(project_id)
    return {"engine_launch_profiles": list_rows("engine_launch_profiles", project_id)}


@app.get("/v2/projects/{project_id}/engine-launch-profiles/{engine_launch_profile_id}", dependencies=[Depends(protected)])
def v2_get_engine_launch_profile(project_id: str, engine_launch_profile_id: str) -> Dict[str, Any]:
    obj = get_row("engine_launch_profiles", engine_launch_profile_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="engine_launch_profile 涓嶅睘浜庤 project")
    return obj


@app.put("/v2/projects/{project_id}/engine-launch-profiles/{engine_launch_profile_id}", dependencies=[Depends(protected)])
def v2_update_engine_launch_profile(project_id: str, engine_launch_profile_id: str, payload: EngineLaunchProfilePayload) -> Dict[str, Any]:
    if payload.engine_launch_profile_id != engine_launch_profile_id:
        raise HTTPException(status_code=400, detail="engine_launch_profile_id does not match the path parameter")
    return {"ok": True, "engine_launch_profile": save_engine_launch_profile(project_id, payload)}


@app.delete("/v2/projects/{project_id}/engine-launch-profiles/{engine_launch_profile_id}", dependencies=[Depends(protected)])
def v2_delete_engine_launch_profile(project_id: str, engine_launch_profile_id: str) -> Dict[str, Any]:
    obj = get_row("engine_launch_profiles", engine_launch_profile_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="engine_launch_profile 涓嶅睘浜庤 project")
    delete_row("engine_launch_profiles", engine_launch_profile_id)
    return {"ok": True, "deleted": engine_launch_profile_id}


@app.post("/v2/projects/{project_id}/interfaces", dependencies=[Depends(protected)])
def v2_create_interface(project_id: str, payload: InterfacePayload) -> Dict[str, Any]:
    return {"ok": True, "interface": save_interface(project_id, payload)}


@app.get("/v2/projects/{project_id}/interfaces", dependencies=[Depends(protected)])
def v2_list_interfaces(project_id: str) -> Dict[str, Any]:
    assert_project_exists(project_id)
    return {"interfaces": list_rows("interfaces", project_id)}


@app.get("/v2/projects/{project_id}/interfaces/{interface_id}", dependencies=[Depends(protected)])
def v2_get_interface(project_id: str, interface_id: str) -> Dict[str, Any]:
    obj = get_row("interfaces", interface_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="interface 涓嶅睘浜庤 project")
    return obj


@app.put("/v2/projects/{project_id}/interfaces/{interface_id}", dependencies=[Depends(protected)])
def v2_update_interface(project_id: str, interface_id: str, payload: InterfacePayload) -> Dict[str, Any]:
    if payload.interface_id != interface_id:
        raise HTTPException(status_code=400, detail="interface_id does not match the path parameter")
    return {"ok": True, "interface": save_interface(project_id, payload)}


@app.delete("/v2/projects/{project_id}/interfaces/{interface_id}", dependencies=[Depends(protected)])
def v2_delete_interface(project_id: str, interface_id: str) -> Dict[str, Any]:
    obj = get_row("interfaces", interface_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="interface 涓嶅睘浜庤 project")
    delete_row("interfaces", interface_id)
    return {"ok": True, "deleted": interface_id}


@app.post("/v2/projects/{project_id}/subnets", dependencies=[Depends(protected)])
def v2_create_subnet(project_id: str, payload: SubnetPayload) -> Dict[str, Any]:
    return {"ok": True, "subnet": save_subnet(project_id, payload)}


@app.get("/v2/projects/{project_id}/subnets", dependencies=[Depends(protected)])
def v2_list_subnets(project_id: str) -> Dict[str, Any]:
    assert_project_exists(project_id)
    return {"subnets": list_rows("subnets", project_id)}


@app.get("/v2/projects/{project_id}/subnets/{subnet_id}", dependencies=[Depends(protected)])
def v2_get_subnet(project_id: str, subnet_id: str) -> Dict[str, Any]:
    obj = get_row("subnets", subnet_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="subnet 涓嶅睘浜庤 project")
    return obj


@app.put("/v2/projects/{project_id}/subnets/{subnet_id}", dependencies=[Depends(protected)])
def v2_update_subnet(project_id: str, subnet_id: str, payload: SubnetPayload) -> Dict[str, Any]:
    if payload.subnet_id != subnet_id:
        raise HTTPException(status_code=400, detail="subnet_id does not match the path parameter")
    return {"ok": True, "subnet": save_subnet(project_id, payload)}


@app.delete("/v2/projects/{project_id}/subnets/{subnet_id}", dependencies=[Depends(protected)])
def v2_delete_subnet(project_id: str, subnet_id: str) -> Dict[str, Any]:
    obj = get_row("subnets", subnet_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="subnet 涓嶅睘浜庤 project")
    delete_row("subnets", subnet_id)
    return {"ok": True, "deleted": subnet_id}


@app.post("/v2/projects/{project_id}/application-instances", dependencies=[Depends(protected)])
def v2_create_application_instance(project_id: str, payload: ApplicationInstancePayload) -> Dict[str, Any]:
    return {"ok": True, "application_instance": present_application_instance(save_application_instance(project_id, payload))}


@app.get("/v2/projects/{project_id}/application-instances", dependencies=[Depends(protected)])
def v2_list_application_instances(project_id: str) -> Dict[str, Any]:
    assert_project_exists(project_id)
    return {"application_instances": [present_application_instance(item) for item in list_rows("application_instances", project_id)]}


@app.get("/v2/projects/{project_id}/application-instances/{application_instance_id}", dependencies=[Depends(protected)])
def v2_get_application_instance(project_id: str, application_instance_id: str) -> Dict[str, Any]:
    obj = get_row("application_instances", application_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="application_instance 涓嶅睘浜庤 project")
    return obj


@app.put("/v2/projects/{project_id}/application-instances/{application_instance_id}", dependencies=[Depends(protected)])
def v2_update_application_instance(project_id: str, application_instance_id: str, payload: ApplicationInstancePayload) -> Dict[str, Any]:
    if payload.application_instance_id != application_instance_id:
        raise HTTPException(status_code=400, detail="application_instance_id does not match the path parameter")
    return {"ok": True, "application_instance": present_application_instance(save_application_instance(project_id, payload))}


@app.post("/v2/projects/{project_id}/application-instances/{application_instance_id}/recipe-preview", dependencies=[Depends(protected)])
def v2_application_recipe_preview(project_id: str, application_instance_id: str, payload: ApplicationRecipePayload) -> Dict[str, Any]:
    obj = get_row("application_instances", application_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="application_instance 涓嶅睘浜庤 project")
    preview = preview_application_instance_render(obj, override_recipe=payload)
    return {
        "ok": True,
        "application_instance_id": application_instance_id,
        "template_id": obj["template_id"],
        "effective_recipe": preview["effective_recipe"],
        "effective_metric_profile": preview["effective_metric_profile"],
        "switch_summary": preview["switch_summary"],
        "application_block": preview["application_block"],
    }


@app.post("/v2/projects/{project_id}/application-instances/{application_instance_id}/recipe-apply", dependencies=[Depends(protected)])
def v2_application_recipe_apply(project_id: str, application_instance_id: str, payload: ApplicationRecipePayload) -> Dict[str, Any]:
    obj = get_row("application_instances", application_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="application_instance 涓嶅睘浜庤 project")
    preview = preview_application_instance_render(obj, override_recipe=payload)
    merged_recipe = ApplicationRecipePayload.model_validate(preview["effective_recipe"]) if preview["effective_recipe"] is not None else None
    obj["recipe"] = merged_recipe.model_dump() if merged_recipe else None
    compat_metric_profile = metric_profile_from_recipe(merged_recipe)
    obj["metric_profile"] = compat_metric_profile.model_dump() if compat_metric_profile else None
    obj["updated_at"] = now_iso()
    upsert_row("application_instances", application_instance_id, obj, project_id=project_id, template_id=obj.get("template_id"))
    return {
        "ok": True,
        "application_instance": obj,
        "effective_recipe": preview["effective_recipe"],
        "effective_metric_profile": preview["effective_metric_profile"],
        "switch_summary": preview["switch_summary"],
        "application_block": preview["application_block"],
    }


@app.delete("/v2/projects/{project_id}/application-instances/{application_instance_id}/recipe", dependencies=[Depends(protected)])
def v2_application_recipe_reset(project_id: str, application_instance_id: str) -> Dict[str, Any]:
    obj = get_row("application_instances", application_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="application_instance 涓嶅睘浜庤 project")
    obj["recipe"] = None
    obj["metric_profile"] = None
    obj["updated_at"] = now_iso()
    upsert_row("application_instances", application_instance_id, obj, project_id=project_id, template_id=obj.get("template_id"))
    preview = preview_application_instance_render(obj)
    return {
        "ok": True,
        "application_instance": obj,
        "switch_summary": preview["switch_summary"],
        "application_block": preview["application_block"],
    }


@app.post("/v2/projects/{project_id}/application-instances/{application_instance_id}/metric-preview", dependencies=[Depends(protected)])
def v2_application_metric_preview(project_id: str, application_instance_id: str, payload: ApplicationMetricProfilePayload) -> Dict[str, Any]:
    obj = get_row("application_instances", application_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="application_instance 涓嶅睘浜庤 project")
    preview = preview_application_instance_render(obj, override_metric_profile=payload)
    return {
        "ok": True,
        "application_instance_id": application_instance_id,
        "template_id": obj["template_id"],
        "effective_recipe": preview["effective_recipe"],
        "effective_metric_profile": preview["effective_metric_profile"],
        "switch_summary": preview["switch_summary"],
        "application_block": preview["application_block"],
    }


@app.post("/v2/projects/{project_id}/application-instances/{application_instance_id}/metric-switch", dependencies=[Depends(protected)])
def v2_application_metric_switch(project_id: str, application_instance_id: str, payload: ApplicationMetricProfilePayload) -> Dict[str, Any]:
    obj = get_row("application_instances", application_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="application_instance 涓嶅睘浜庤 project")
    preview = preview_application_instance_render(obj, override_metric_profile=payload)
    merged_recipe = ApplicationRecipePayload.model_validate(preview["effective_recipe"]) if preview["effective_recipe"] is not None else None
    merged_metric_profile = ApplicationMetricProfilePayload.model_validate(preview["effective_metric_profile"]) if preview["effective_metric_profile"] is not None else None
    obj["metric_profile"] = merged_metric_profile.model_dump() if merged_metric_profile else None
    obj["recipe"] = merged_recipe.model_dump() if merged_recipe else None
    obj["updated_at"] = now_iso()
    upsert_row("application_instances", application_instance_id, obj, project_id=project_id, template_id=obj.get("template_id"))
    return {
        "ok": True,
        "application_instance": obj,
        "effective_recipe": preview["effective_recipe"],
        "effective_metric_profile": preview["effective_metric_profile"],
        "switch_summary": preview["switch_summary"],
        "application_block": preview["application_block"],
    }


@app.delete("/v2/projects/{project_id}/application-instances/{application_instance_id}/metric-switch", dependencies=[Depends(protected)])
def v2_application_metric_switch_reset(project_id: str, application_instance_id: str) -> Dict[str, Any]:
    obj = get_row("application_instances", application_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="application_instance 涓嶅睘浜庤 project")
    obj["metric_profile"] = None
    obj["recipe"] = None
    obj["updated_at"] = now_iso()
    upsert_row("application_instances", application_instance_id, obj, project_id=project_id, template_id=obj.get("template_id"))
    preview = preview_application_instance_render(obj)
    return {
        "ok": True,
        "application_instance": obj,
        "switch_summary": preview["switch_summary"],
        "application_block": preview["application_block"],
    }


@app.post("/v2/projects/{project_id}/application-instances/{application_instance_id}/protocol-switch-preview", dependencies=[Depends(protected)])
def v2_application_protocol_switch_preview(project_id: str, application_instance_id: str, payload: ApplicationProtocolSwitchPayload) -> Dict[str, Any]:
    obj = get_row("application_instances", application_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="application_instance 娑撳秴鐫樻禍搴ゎ嚉 project")
    result = build_protocol_switched_application_instance(project_id, obj, payload)
    return {
        "ok": len(result["errors"]) == 0,
        "application_instance_id": application_instance_id,
        **result,
    }


@app.post("/v2/projects/{project_id}/application-instances/{application_instance_id}/protocol-switch-apply", dependencies=[Depends(protected)])
def v2_application_protocol_switch_apply(project_id: str, application_instance_id: str, payload: ApplicationProtocolSwitchPayload) -> Dict[str, Any]:
    obj = get_row("application_instances", application_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="application_instance 娑撳秴鐫樻禍搴ゎ嚉 project")
    result = build_protocol_switched_application_instance(project_id, obj, payload)
    switched_obj = dict(result["switched_application_instance"])
    switched_obj["project_id"] = project_id
    switched_obj["updated_at"] = now_iso()
    switched_obj["params"] = normalize_application_params(switched_obj.get("params") or {})
    saved = upsert_row(
        "application_instances",
        application_instance_id,
        switched_obj,
        project_id=project_id,
        template_id=switched_obj.get("template_id"),
    )
    preview = preview_application_instance_render(saved)
    return {
        "ok": len(result["errors"]) == 0,
        "application_instance": present_application_instance(saved),
        "source_template": result["source_template"],
        "target_template": result["target_template"],
        "source_effective_params": result["source_effective_params"],
        "target_effective_params": extract_effective_user_visible_params(saved),
        "effective_recipe": preview["effective_recipe"],
        "effective_metric_profile": preview["effective_metric_profile"],
        "switch_summary": result["switch_summary"],
        "warnings": result["warnings"],
        "errors": result["errors"],
        "application_block": preview["application_block"],
    }

@app.delete("/v2/projects/{project_id}/application-instances/{application_instance_id}", dependencies=[Depends(protected)])
def v2_delete_application_instance(project_id: str, application_instance_id: str) -> Dict[str, Any]:
    obj = get_row("application_instances", application_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="application_instance 涓嶅睘浜庤 project")
    delete_row("application_instances", application_instance_id)
    return {"ok": True, "deleted": application_instance_id}


@app.post("/v2/projects/{project_id}/load-profiles", dependencies=[Depends(protected)])
def v2_create_load_profile(project_id: str, payload: LoadProfilePayload) -> Dict[str, Any]:
    return {"ok": True, "load_profile": save_load_profile(project_id, payload)}


@app.get("/v2/projects/{project_id}/load-profiles", dependencies=[Depends(protected)])
def v2_list_load_profiles(project_id: str) -> Dict[str, Any]:
    assert_project_exists(project_id)
    return {"load_profiles": list_rows("load_profiles", project_id)}


@app.get("/v2/projects/{project_id}/load-profiles/{load_profile_id}", dependencies=[Depends(protected)])
def v2_get_load_profile(project_id: str, load_profile_id: str) -> Dict[str, Any]:
    obj = get_row("load_profiles", load_profile_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="load_profile 涓嶅睘浜庤 project")
    return obj


@app.put("/v2/projects/{project_id}/load-profiles/{load_profile_id}", dependencies=[Depends(protected)])
def v2_update_load_profile(project_id: str, load_profile_id: str, payload: LoadProfilePayload) -> Dict[str, Any]:
    if payload.load_profile_id != load_profile_id:
        raise HTTPException(status_code=400, detail="load_profile_id does not match the path parameter")
    return {"ok": True, "load_profile": save_load_profile(project_id, payload)}


@app.delete("/v2/projects/{project_id}/load-profiles/{load_profile_id}", dependencies=[Depends(protected)])
def v2_delete_load_profile(project_id: str, load_profile_id: str) -> Dict[str, Any]:
    obj = get_row("load_profiles", load_profile_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="load_profile 涓嶅睘浜庤 project")
    delete_row("load_profiles", load_profile_id)
    return {"ok": True, "deleted": load_profile_id}


@app.post("/v2/projects/{project_id}/clients", dependencies=[Depends(protected)])
def v2_create_client(project_id: str, payload: ClientPayload) -> Dict[str, Any]:
    return {"ok": True, "client": save_client(project_id, payload)}


@app.get("/v2/projects/{project_id}/clients", dependencies=[Depends(protected)])
def v2_list_clients(project_id: str) -> Dict[str, Any]:
    assert_project_exists(project_id)
    return {"clients": list_rows("clients", project_id)}


@app.get("/v2/projects/{project_id}/clients/{client_instance_id}", dependencies=[Depends(protected)])
def v2_get_client(project_id: str, client_instance_id: str) -> Dict[str, Any]:
    obj = get_row("clients", client_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="client 涓嶅睘浜庤 project")
    return obj


@app.put("/v2/projects/{project_id}/clients/{client_instance_id}", dependencies=[Depends(protected)])
def v2_update_client(project_id: str, client_instance_id: str, payload: ClientPayload) -> Dict[str, Any]:
    if payload.client_instance_id != client_instance_id:
        raise HTTPException(status_code=400, detail="client_instance_id does not match the path parameter")
    return {"ok": True, "client": save_client(project_id, payload)}


@app.delete("/v2/projects/{project_id}/clients/{client_instance_id}", dependencies=[Depends(protected)])
def v2_delete_client(project_id: str, client_instance_id: str) -> Dict[str, Any]:
    obj = get_row("clients", client_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="client 涓嶅睘浜庤 project")
    delete_row("clients", client_instance_id)
    return {"ok": True, "deleted": client_instance_id}


@app.post("/v2/projects/{project_id}/servers", dependencies=[Depends(protected)])
def v2_create_server(project_id: str, payload: ServerPayload) -> Dict[str, Any]:
    return {"ok": True, "server": save_server(project_id, payload)}


@app.get("/v2/projects/{project_id}/servers", dependencies=[Depends(protected)])
def v2_list_servers(project_id: str) -> Dict[str, Any]:
    assert_project_exists(project_id)
    return {"servers": list_rows("servers", project_id)}


@app.get("/v2/projects/{project_id}/servers/{server_instance_id}", dependencies=[Depends(protected)])
def v2_get_server(project_id: str, server_instance_id: str) -> Dict[str, Any]:
    obj = get_row("servers", server_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="server 涓嶅睘浜庤 project")
    return obj


@app.put("/v2/projects/{project_id}/servers/{server_instance_id}", dependencies=[Depends(protected)])
def v2_update_server(project_id: str, server_instance_id: str, payload: ServerPayload) -> Dict[str, Any]:
    if payload.server_instance_id != server_instance_id:
        raise HTTPException(status_code=400, detail="server_instance_id does not match the path parameter")
    return {"ok": True, "server": save_server(project_id, payload)}


@app.delete("/v2/projects/{project_id}/servers/{server_instance_id}", dependencies=[Depends(protected)])
def v2_delete_server(project_id: str, server_instance_id: str) -> Dict[str, Any]:
    obj = get_row("servers", server_instance_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="server 涓嶅睘浜庤 project")
    delete_row("servers", server_instance_id)
    return {"ok": True, "deleted": server_instance_id}


# =========================
# Test cases / bindings / validation / compile
# =========================

@app.post("/v2/projects/{project_id}/test-cases", dependencies=[Depends(protected)])
def v2_create_test_case(project_id: str, payload: TestCasePayload) -> Dict[str, Any]:
    return {"ok": True, "test_case": save_test_case(project_id, payload)}


@app.get("/v2/projects/{project_id}/test-cases", dependencies=[Depends(protected)])
def v2_list_test_cases(project_id: str) -> Dict[str, Any]:
    assert_project_exists(project_id)
    return {"test_cases": list_rows("test_cases", project_id)}


@app.get("/v2/projects/{project_id}/test-cases/{test_case_id}", dependencies=[Depends(protected)])
def v2_get_test_case(project_id: str, test_case_id: str) -> Dict[str, Any]:
    obj = get_row("test_cases", test_case_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="test_case 涓嶅睘浜庤 project")
    return obj


@app.put("/v2/projects/{project_id}/test-cases/{test_case_id}", dependencies=[Depends(protected)])
def v2_update_test_case(project_id: str, test_case_id: str, payload: TestCasePayload) -> Dict[str, Any]:
    if payload.test_case_id != test_case_id:
        raise HTTPException(status_code=400, detail="test_case_id does not match the path parameter")
    return {"ok": True, "test_case": save_test_case(project_id, payload)}


@app.delete("/v2/projects/{project_id}/test-cases/{test_case_id}", dependencies=[Depends(protected)])
def v2_delete_test_case(project_id: str, test_case_id: str) -> Dict[str, Any]:
    obj = get_row("test_cases", test_case_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="test_case 涓嶅睘浜庤 project")
    delete_row("test_cases", test_case_id)
    return {"ok": True, "deleted": test_case_id}


@app.post("/v2/projects/{project_id}/test-cases/{test_case_id}/bindings", dependencies=[Depends(protected)])
def v2_update_test_case_bindings(project_id: str, test_case_id: str, payload: TestCaseBindingsPayload) -> Dict[str, Any]:
    obj = get_row("test_cases", test_case_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="test_case 涓嶅睘浜庤 project")
    obj["thread_policy_ref"] = None
    obj["engine_launch_profile_ref"] = None
    if payload.client_instance_ids is not None:
        obj["client_instance_ids"] = payload.client_instance_ids
    if payload.server_instance_ids is not None:
        obj["server_instance_ids"] = payload.server_instance_ids
    obj["updated_at"] = now_iso()
    upsert_row("test_cases", test_case_id, obj, project_id=project_id)
    return {"ok": True, "test_case": obj}


@app.post("/v2/projects/{project_id}/test-cases/{test_case_id}/validate", dependencies=[Depends(protected)])
def v2_validate_test_case(project_id: str, test_case_id: str) -> Dict[str, Any]:
    result = validate_and_compile_test_case(project_id, test_case_id)
    return {
        "ok": result["ok"],
        "warnings": result["warnings"],
        "errors": result["errors"],
        "effective_thread_policy": result["effective_thread_policy"],
        "effective_engine_launch_profile": result["effective_engine_launch_profile"],
    }


@app.post("/v2/projects/{project_id}/test-cases/{test_case_id}/launch-preview", dependencies=[Depends(protected)])
def v2_launch_preview(project_id: str, test_case_id: str) -> Dict[str, Any]:
    plan = build_launch_plan(project_id, test_case_id)
    return {
        "ok": True,
        "launch_plan": plan,
    }


@app.post("/v2/projects/{project_id}/test-cases/{test_case_id}/compile-preview", dependencies=[Depends(protected)])
def v2_compile_preview(project_id: str, test_case_id: str) -> Dict[str, Any]:
    result = validate_and_compile_test_case(project_id, test_case_id)
    return {
        "ok": result["ok"],
        "warnings": result["warnings"],
        "errors": result["errors"],
        "effective_thread_policy": result["effective_thread_policy"],
        "effective_engine_launch_profile": result["effective_engine_launch_profile"],
        "compiled_text": result["compiled_text"],
    }


@app.post("/v2/projects/{project_id}/test-cases/{test_case_id}/compile", dependencies=[Depends(protected)])
def v2_compile(project_id: str, test_case_id: str, payload: CompileRequest) -> Dict[str, Any]:
    result = validate_and_compile_test_case(project_id, test_case_id)
    if not result["ok"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "test_case validation failed; compile was aborted",
                "warnings": result["warnings"],
                "errors": result["errors"],
            },
        )

    artifact = persist_artifact(
        test_case_id=test_case_id,
        compiled_text=result["compiled_text"],
        output_filename=payload.output_filename,
        deployed=False,
        validation={"ok": True, "warnings": result["warnings"], "errors": []},
    )

    deploy_result = None
    if payload.deploy:
        with deploy_lock:
            validate_deploy_target()
            backup_path = backup_current_config()
            tmp_target = DEPLOY_FILE.with_suffix(".conf.tmp")
            write_text_file(tmp_target, result["compiled_text"])
            os.replace(tmp_target, DEPLOY_FILE)
            deploy_result = {
                "deployed_to": str(DEPLOY_FILE),
                "backup_path": str(backup_path) if backup_path else None,
                "note": "compile/deploy 鍙儴缃查厤缃紝涓嶈礋璐ｅ惎鍔ㄥ紩鎿庯紱璇蜂娇鐢?launch-preview 鎴?runs 鎺ュ彛鎵ц鍘嬫祴",
            }
            artifact["deployed"] = True
            upsert_row("artifacts", artifact["artifact_id"], artifact, test_case_id=test_case_id)

    test_case = get_row("test_cases", test_case_id)
    test_case["compiled_config_path"] = artifact["output_path"]
    test_case["last_compile_status"] = "success"
    test_case["updated_at"] = now_iso()
    upsert_row("test_cases", test_case_id, test_case, project_id=project_id)

    return {
        "ok": True,
        "artifact": artifact,
        "warnings": result["warnings"],
        "deploy_result": deploy_result,
        "effective_thread_policy": result["effective_thread_policy"],
        "effective_engine_launch_profile": result["effective_engine_launch_profile"],
        "interface_mapping": result["interface_mapping"],
        "used_interfaces": result["used_interfaces"],
    }


# =========================
# V2 current monitor / summary / diagnosis
# =========================

@app.get("/v2/engine/monitor/raw", dependencies=[Depends(protected)])
def v2_engine_monitor_raw() -> Dict[str, Any]:
    raw = fetch_engine_monitor()
    return {
        "source": {
            "monitor_url": ENGINE_MONITOR_URL,
            "fetched_at": now_iso(),
        },
        "engine_payload": raw,
    }


@app.get("/v2/summary/current", dependencies=[Depends(protected)])
def v2_summary_current() -> Dict[str, Any]:
    raw = fetch_engine_monitor()
    return build_summary_from_monitor(raw)


@app.get("/v2/diagnosis/current", dependencies=[Depends(protected)])
def v2_diagnosis_current() -> Dict[str, Any]:
    raw = fetch_engine_monitor()
    summary = build_summary_from_monitor(raw)
    diagnosis = build_diagnosis_from_summary(summary)
    return {"summary": summary, "diagnosis": diagnosis}


# =========================
# Runs / run record
# =========================

@app.post("/v2/projects/{project_id}/test-cases/{test_case_id}/runs", dependencies=[Depends(protected)])
def v2_create_run(project_id: str, test_case_id: str, payload: RunRequest) -> Dict[str, Any]:
    running_runs = list_running_runs()
    if running_runs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "褰撳墠宸叉湁杩愯涓殑 run锛屽崟寮曟搸妯″紡涓嬩笉鍏佽骞跺彂鍚姩",
                "running_runs": [r["run_id"] for r in running_runs],
            },
        )

    result = validate_and_compile_test_case(project_id, test_case_id, stress_type_override=payload.run_mode)
    if not result["ok"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "test_case 鏍￠獙澶辫触锛屾棤娉曞惎鍔?run",
                "warnings": result["warnings"],
                "errors": result["errors"],
            },
        )

    artifact = persist_artifact(
        test_case_id=test_case_id,
        compiled_text=result["compiled_text"],
        output_filename=payload.output_filename,
        deployed=False,
        validation={"ok": True, "warnings": result["warnings"], "errors": []},
    )

    with deploy_lock:
        validate_deploy_target()
        backup_path = backup_current_config()
        tmp_target = DEPLOY_FILE.with_suffix(".conf.tmp")
        write_text_file(tmp_target, result["compiled_text"])
        os.replace(tmp_target, DEPLOY_FILE)
        deploy_result = {
            "deployed_to": str(DEPLOY_FILE),
            "backup_path": str(backup_path) if backup_path else None,
        }
        artifact["deployed"] = True
        upsert_row("artifacts", artifact["artifact_id"], artifact, test_case_id=test_case_id)

    launch_plan = build_launch_plan(project_id, test_case_id)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"run_{test_case_id}_{ts}"
    try:
        proc_info = launch_engine_process(launch_plan, run_id)
        if proc_info.get("exited_early"):
            status_value = "failed"
            launch_error = "engine_exited_during_startup_wait"
        else:
            status_value = "running"
            launch_error = None
    except Exception as e:
        proc_info = {
            "pid": None,
            "stdout_path": None,
            "stderr_path": None,
            "exited_early": False,
            "exit_code": None,
            "stdout_tail": None,
            "stderr_tail": None,
            "env_overrides": launch_plan.get("env_overrides") or {},
        }
        status_value = "failed"
        launch_error = str(e)

    run_payload = {
        "run_id": run_id,
        "project_id": project_id,
        "test_case_id": test_case_id,
        "artifact_id": artifact["artifact_id"],
        "run_mode": payload.run_mode,
        "status": status_value,
        "started_at": now_iso(),
        "ended_at": now_iso() if status_value == "failed" else None,
        "compiled_config_path": artifact["output_path"],
        "deployed_config_path": str(DEPLOY_FILE),
        "summary_snapshot": None,
        "diagnosis_snapshot": None,
        "deploy_result": deploy_result,
        "warnings": result["warnings"],
        "pid": proc_info.get("pid"),
        "stdout_path": proc_info.get("stdout_path"),
        "stderr_path": proc_info.get("stderr_path"),
        "stdout_tail": proc_info.get("stdout_tail"),
        "stderr_tail": proc_info.get("stderr_tail"),
        "launch_plan": launch_plan,
        "command_line": launch_plan["full_command"],
        "launch_env": proc_info.get("env_overrides") or launch_plan.get("env_overrides") or {},
        "launch_error": launch_error,
        "exit_code": proc_info.get("exit_code"),
    }
    run_payload = save_run(project_id, test_case_id, run_id, run_payload)

    test_case = get_row("test_cases", test_case_id)
    test_case["compiled_config_path"] = artifact["output_path"]
    test_case["last_compile_status"] = "success"
    test_case["last_run_id"] = run_id
    test_case["updated_at"] = now_iso()
    upsert_row("test_cases", test_case_id, test_case, project_id=project_id)

    return {
        "ok": status_value != "failed",
        "run": run_payload,
        "artifact": artifact,
        "deploy_result": deploy_result,
        "warnings": result["warnings"],
        "launch_plan": launch_plan,
    }


@app.get("/v2/runs", dependencies=[Depends(protected)])
def v2_list_runs() -> Dict[str, Any]:
    return {"runs": list_rows("runs")}


@app.post("/v2/runs/{run_id}/stop", dependencies=[Depends(protected)])
def v2_stop_run(run_id: str) -> Dict[str, Any]:
    run_obj = get_row("runs", run_id)
    run_obj = stop_run_process(run_obj)
    return {
        "ok": run_obj.get("status") == "stopped",
        "run": run_obj,
    }

@app.get("/v2/runs/{run_id}", dependencies=[Depends(protected)])
def v2_get_run(run_id: str) -> Dict[str, Any]:
    run_obj = get_row("runs", run_id)
    run_obj = refresh_run_process_state(run_obj)
    if run_obj.get("status") in {"pending", "running"}:
        run_obj = snapshot_run_from_monitor(run_obj)
    return run_obj


@app.get("/v2/runs/{run_id}/summary", dependencies=[Depends(protected)])
def v2_get_run_summary(run_id: str) -> Dict[str, Any]:
    run_obj = get_row("runs", run_id)
    run_obj = refresh_run_process_state(run_obj)
    if run_obj.get("status") in {"pending", "running"} or not run_obj.get("summary_snapshot"):
        run_obj = snapshot_run_from_monitor(run_obj)
    return {
        "run_id": run_id,
        "test_case_id": run_obj["test_case_id"],
        "status": run_obj["status"],
        "summary": run_obj.get("summary_snapshot"),
    }


@app.get("/v2/runs/{run_id}/diagnosis", dependencies=[Depends(protected)])
def v2_get_run_diagnosis(run_id: str) -> Dict[str, Any]:
    run_obj = get_row("runs", run_id)
    run_obj = refresh_run_process_state(run_obj)
    if run_obj.get("status") in {"pending", "running"} or not run_obj.get("diagnosis_snapshot"):
        run_obj = snapshot_run_from_monitor(run_obj)
    return {
        "run_id": run_id,
        "test_case_id": run_obj["test_case_id"],
        "status": run_obj["status"],
        "summary": run_obj.get("summary_snapshot"),
        "diagnosis": run_obj.get("diagnosis_snapshot"),
    }


@app.get("/v2/projects/{project_id}/test-cases/{test_case_id}/summary/latest", dependencies=[Depends(protected)])
def v2_get_test_case_latest_summary(project_id: str, test_case_id: str) -> Dict[str, Any]:
    tc = get_row("test_cases", test_case_id)
    if tc["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="test_case 涓嶅睘浜庤 project")
    run_id = tc.get("last_run_id")
    if not run_id:
        raise HTTPException(status_code=404, detail="test_case 灏氭棤 run 璁板綍")
    return v2_get_run_summary(run_id)


@app.get("/v2/projects/{project_id}/test-cases/{test_case_id}/diagnosis/latest", dependencies=[Depends(protected)])
def v2_get_test_case_latest_diagnosis(project_id: str, test_case_id: str) -> Dict[str, Any]:
    tc = get_row("test_cases", test_case_id)
    if tc["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="test_case 涓嶅睘浜庤 project")
    run_id = tc.get("last_run_id")
    if not run_id:
        raise HTTPException(status_code=404, detail="test_case 灏氭棤 run 璁板綍")
    return v2_get_run_diagnosis(run_id)


# =========================
# ScenarioPreset formalization (pre-OpenClaw 2.0)
# =========================

def _assert_project_owned_row(table: str, row_id: str, project_id: str, label: str) -> Dict[str, Any]:
    obj = get_row(table, row_id)
    if obj.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=f"{label} 涓嶅睘浜庤 project")
    return obj


def _role_is_targeted(apply_recipe_to: str, role: str) -> bool:
    return apply_recipe_to == "both" or apply_recipe_to == role


def _generic_recipe_inputs_present(payload: ScenarioPresetComposePayload) -> bool:
    return any([
        payload.application_template_id,
        payload.application_instance_ref,
        payload.application_instance_id,
        payload.application_instance_name,
        payload.application_params,
        payload.recipe is not None,
    ])


def _build_role_application_instance(project_id: str, payload: ScenarioPresetComposePayload, role: Literal["clients", "servers"], default_ref: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    explicit_ref = payload.client_application_instance_ref if role == "clients" else payload.server_application_instance_ref
    if explicit_ref:
        existing = _assert_project_owned_row("application_instances", explicit_ref, project_id, f"{role} application_instance")
        return existing, explicit_ref, False
    if _role_is_targeted(payload.apply_recipe_to, role) and (_generic_recipe_inputs_present(payload) or (payload.recipe is not None and default_ref)):
        app_id = payload.application_instance_id or f"{payload.test_case_id}_{role[:-1]}_app"
        app_name = payload.application_instance_name or f"{payload.name} {role[:-1]} app"
        if payload.application_template_id:
            _ = get_manifest_template(payload.application_template_id)
            obj = {
                "application_instance_id": app_id,
                "template_id": payload.application_template_id,
                "name": app_name,
                "params": normalize_application_params(payload.application_params or {}),
                "metric_profile": None,
                "recipe": None,
                "project_id": project_id,
                "updated_at": now_iso(),
            }
            if payload.recipe is not None:
                preview = preview_application_instance_render(obj, override_recipe=payload.recipe)
                merged_recipe = ApplicationRecipePayload.model_validate(preview["effective_recipe"]) if preview["effective_recipe"] is not None else None
                merged_metric_profile = ApplicationMetricProfilePayload.model_validate(preview["effective_metric_profile"]) if preview["effective_metric_profile"] is not None else None
                obj["recipe"] = merged_recipe.model_dump() if merged_recipe else None
                obj["metric_profile"] = merged_metric_profile.model_dump() if merged_metric_profile else None
            return obj, app_id, True
        base_ref = payload.application_instance_ref or default_ref
        if not base_ref:
            raise HTTPException(status_code=400, detail=f"{role} 缂哄皯榛樿 application_instance_ref锛屾棤娉曞簲鐢?recipe")
        base_obj = _assert_project_owned_row("application_instances", base_ref, project_id, f"{role} application_instance")
        obj = dict(base_obj)
        merged_params = normalize_application_params(base_obj.get("params") or {})
        merged_params.update(normalize_application_params(payload.application_params or {}))
        obj.update({
            "application_instance_id": app_id,
            "name": app_name,
            "params": merged_params,
            "project_id": project_id,
            "updated_at": now_iso(),
        })
        if payload.recipe is not None:
            preview = preview_application_instance_render(obj, override_recipe=payload.recipe)
            merged_recipe = ApplicationRecipePayload.model_validate(preview["effective_recipe"]) if preview["effective_recipe"] is not None else None
            merged_metric_profile = ApplicationMetricProfilePayload.model_validate(preview["effective_metric_profile"]) if preview["effective_metric_profile"] is not None else None
            obj["recipe"] = merged_recipe.model_dump() if merged_recipe else None
            obj["metric_profile"] = merged_metric_profile.model_dump() if merged_metric_profile else None
        return obj, app_id, True
    if default_ref:
        existing = _assert_project_owned_row("application_instances", default_ref, project_id, f"{role} application_instance")
        return existing, default_ref, False
    return None, None, False


def _resolve_load_profile_for_slot(project_id: str, payload: ScenarioPresetComposePayload, preset: Dict[str, Any], slot: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    if payload.load_profile is not None:
        obj = payload.load_profile.model_dump()
        obj["project_id"] = project_id
        obj["updated_at"] = now_iso()
        return obj, payload.load_profile.load_profile_id, True
    ref = payload.client_load_profile_ref or payload.load_profile_ref or slot.get("load_profile_ref") or preset.get("default_load_profile_ref")
    if not ref:
        return None, None, False
    existing = _assert_project_owned_row("load_profiles", ref, project_id, "load_profile")
    return existing, ref, False


def synthesize_scenario_preset_materialization(project_id: str, preset: Dict[str, Any], payload: ScenarioPresetComposePayload) -> Dict[str, Any]:
    for slot in preset.get("client_slots") or []:
        _assert_project_owned_row("interfaces", slot["interface_ref"], project_id, "interface")
        _assert_project_owned_row("subnets", slot["subnet_ref"], project_id, "subnet")
    for slot in preset.get("server_slots") or []:
        _assert_project_owned_row("interfaces", slot["interface_ref"], project_id, "interface")
        _assert_project_owned_row("subnets", slot["subnet_ref"], project_id, "subnet")

    client_default_ref = next((s.get("application_instance_ref") for s in (preset.get("client_slots") or []) if s.get("application_instance_ref")), None)
    server_default_ref = next((s.get("application_instance_ref") for s in (preset.get("server_slots") or []) if s.get("application_instance_ref")), None)
    client_app_obj, client_app_ref, client_app_created = _build_role_application_instance(project_id, payload, "clients", client_default_ref)
    server_app_obj, server_app_ref, server_app_created = _build_role_application_instance(project_id, payload, "servers", server_default_ref)
    client_app_preview = preview_application_instance_render(client_app_obj) if client_app_obj else None
    server_app_preview = preview_application_instance_render(server_app_obj) if server_app_obj else None

    clients, client_ids = [], []
    servers, server_ids = [], []
    effective_load_obj, effective_load_ref, load_created = None, None, False
    for slot in preset.get("client_slots") or []:
        load_obj, load_ref, create_load = _resolve_load_profile_for_slot(project_id, payload, preset, slot)
        if not load_ref:
            raise HTTPException(status_code=400, detail=f"client slot {slot['slot_id']} 缂哄皯 load_profile_ref")
        app_ref = client_app_ref or slot.get("application_instance_ref")
        if not app_ref:
            raise HTTPException(status_code=400, detail=f"client slot {slot['slot_id']} 缂哄皯 application_instance_ref")
        client_id = f"{payload.test_case_id}_{slot['slot_id']}"
        clients.append(ClientPayload(client_instance_id=client_id, interface_ref=slot["interface_ref"], subnet_ref=slot["subnet_ref"], application_instance_ref=app_ref, load_profile_ref=load_ref).model_dump())
        client_ids.append(client_id)
        effective_load_obj, effective_load_ref, load_created = load_obj, load_ref, create_load
    for slot in preset.get("server_slots") or []:
        app_ref = server_app_ref or slot.get("application_instance_ref")
        if not app_ref:
            raise HTTPException(status_code=400, detail=f"server slot {slot['slot_id']} 缂哄皯 application_instance_ref")
        server_id = f"{payload.test_case_id}_{slot['slot_id']}"
        servers.append(ServerPayload(server_instance_id=server_id, interface_ref=slot["interface_ref"], subnet_ref=slot["subnet_ref"], application_instance_ref=app_ref).model_dump())
        server_ids.append(server_id)
    effective_thread_policy, thread_policy_warnings, thread_policy_errors = derive_effective_thread_policy(len(client_ids))
    test_case = TestCasePayload(
        test_case_id=payload.test_case_id,
        name=payload.name,
        mode=preset["mode"],
        thread_policy_ref=None,
        engine_launch_profile_ref=None,
        client_instance_ids=client_ids,
        server_instance_ids=server_ids,
    ).model_dump()
    run_mode = payload.run_mode or (payload.load_profile.stress_type if payload.load_profile else None) or (effective_load_obj or {}).get("stress_type")
    effective_engine_launch_profile, engine_profile_warnings, engine_profile_errors = derive_effective_engine_launch_profile()
    return {
        "client_application": client_app_obj,
        "client_application_ref": client_app_ref,
        "client_application_created": client_app_created,
        "client_application_preview": client_app_preview,
        "server_application": server_app_obj,
        "server_application_ref": server_app_ref,
        "server_application_created": server_app_created,
        "server_application_preview": server_app_preview,
        "load_profile": effective_load_obj,
        "load_profile_ref": effective_load_ref,
        "load_profile_created": load_created,
        "clients": clients,
        "servers": servers,
        "test_case": test_case,
        "run_mode": run_mode,
        "effective_thread_policy": effective_thread_policy,
        "effective_thread_policy_warnings": thread_policy_warnings,
        "effective_thread_policy_errors": thread_policy_errors,
        "effective_engine_launch_profile": effective_engine_launch_profile,
        "effective_engine_launch_profile_warnings": engine_profile_warnings,
        "effective_engine_launch_profile_errors": engine_profile_errors,
    }


def materialize_scenario_preset_compose(project_id: str, preset: Dict[str, Any], payload: ScenarioPresetComposePayload) -> Dict[str, Any]:
    synthesized = synthesize_scenario_preset_materialization(project_id, preset, payload)
    if synthesized.get("load_profile_created") and synthesized.get("load_profile"):
        save_load_profile(project_id, LoadProfilePayload.model_validate(synthesized["load_profile"]))
    if synthesized.get("client_application_created") and synthesized.get("client_application"):
        save_application_instance(project_id, ApplicationInstancePayload.model_validate(synthesized["client_application"]))
    if synthesized.get("server_application_created") and synthesized.get("server_application"):
        save_application_instance(project_id, ApplicationInstancePayload.model_validate(synthesized["server_application"]))
    for client_obj in synthesized["clients"]:
        save_client(project_id, ClientPayload.model_validate(client_obj))
    for server_obj in synthesized["servers"]:
        save_server(project_id, ServerPayload.model_validate(server_obj))
    save_test_case(project_id, TestCasePayload.model_validate(synthesized["test_case"]))
    preview = validate_and_compile_test_case(project_id, payload.test_case_id)
    launch_preview = build_launch_plan(project_id, payload.test_case_id)
    return {"preset": preset, "synthesized": synthesized, "compile_preview": {"ok": preview["ok"], "warnings": preview["warnings"], "errors": preview["errors"], "compiled_text": preview["compiled_text"]}, "launch_preview": launch_preview}


@app.post("/v2/projects/{project_id}/scenario-presets", dependencies=[Depends(protected)])
def v2_create_scenario_preset(project_id: str, payload: ScenarioPresetPayload) -> Dict[str, Any]:
    return {"ok": True, "scenario_preset": save_scenario_preset(project_id, payload)}


@app.get("/v2/projects/{project_id}/scenario-presets", dependencies=[Depends(protected)])
def v2_list_scenario_presets(project_id: str) -> Dict[str, Any]:
    assert_project_exists(project_id)
    return {"scenario_presets": list_rows("scenario_presets", project_id)}


@app.get("/v2/projects/{project_id}/scenario-presets/{scenario_preset_id}", dependencies=[Depends(protected)])
def v2_get_scenario_preset(project_id: str, scenario_preset_id: str) -> Dict[str, Any]:
    obj = get_row("scenario_presets", scenario_preset_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="scenario_preset 涓嶅睘浜庤 project")
    return obj


@app.put("/v2/projects/{project_id}/scenario-presets/{scenario_preset_id}", dependencies=[Depends(protected)])
def v2_update_scenario_preset(project_id: str, scenario_preset_id: str, payload: ScenarioPresetPayload) -> Dict[str, Any]:
    if payload.scenario_preset_id != scenario_preset_id:
        raise HTTPException(status_code=400, detail="scenario_preset_id does not match the path parameter")
    return {"ok": True, "scenario_preset": save_scenario_preset(project_id, payload)}


@app.delete("/v2/projects/{project_id}/scenario-presets/{scenario_preset_id}", dependencies=[Depends(protected)])
def v2_delete_scenario_preset(project_id: str, scenario_preset_id: str) -> Dict[str, Any]:
    obj = get_row("scenario_presets", scenario_preset_id)
    if obj["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="scenario_preset 涓嶅睘浜庤 project")
    delete_row("scenario_presets", scenario_preset_id)
    return {"ok": True, "deleted": scenario_preset_id}


@app.post("/v2/projects/{project_id}/scenario-presets/{scenario_preset_id}/compose-preview", dependencies=[Depends(protected)])
def v2_scenario_preset_compose_preview(project_id: str, scenario_preset_id: str, payload: ScenarioPresetComposePayload) -> Dict[str, Any]:
    preset = v2_get_scenario_preset(project_id, scenario_preset_id)
    return {"ok": True, "scenario_preset_id": scenario_preset_id, "preset": preset, "synthesized": synthesize_scenario_preset_materialization(project_id, preset, payload)}


@app.post("/v2/projects/{project_id}/scenario-presets/{scenario_preset_id}/compose-apply", dependencies=[Depends(protected)])
def v2_scenario_preset_compose_apply(project_id: str, scenario_preset_id: str, payload: ScenarioPresetComposePayload) -> Dict[str, Any]:
    preset = v2_get_scenario_preset(project_id, scenario_preset_id)
    return {"ok": True, "scenario_preset_id": scenario_preset_id, **materialize_scenario_preset_compose(project_id, preset, payload)}


@app.post("/v2/projects/{project_id}/scenario-presets/{scenario_preset_id}/compose-run", dependencies=[Depends(protected)])
def v2_scenario_preset_compose_run(project_id: str, scenario_preset_id: str, payload: ScenarioPresetComposePayload) -> Dict[str, Any]:
    preset = v2_get_scenario_preset(project_id, scenario_preset_id)
    materialized = materialize_scenario_preset_compose(project_id, preset, payload)
    run_mode = materialized["synthesized"].get("run_mode") or "run"
    run_result = v2_create_run(project_id, payload.test_case_id, RunRequest(run_mode=run_mode, output_filename=payload.output_filename, apply_after_deploy=True))
    return {"ok": True, "scenario_preset_id": scenario_preset_id, "materialized": materialized, "run_result": run_result}

