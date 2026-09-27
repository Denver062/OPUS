"""Local-only OPUS API. Do not expose this server to a network without auth."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
CATALOG = ROOT / "catalog" / "apps"
SOURCES = ROOT / "catalog" / "sources.json"
CACHE = ROOT / ".opus-catalog-cache"
STATE = ROOT / ".opus-state.json"

DEFAULT = {
    "installed": [],
    "automations": [{"id": "morning-focus", "name": "아침 집중 모드", "enabled": True,
                       "actions": [{"type": "set_setting", "label": "방해 금지 켜기"}, {"type": "launch_app", "label": "Quick Notes 열기"}]}],
    "workspace": {"name": "내 OPUS 워크스페이스", "role": "admin", "devices": [
        {"id": "this-pc", "name": "이 PC", "status": "online", "role": "admin"},
        {"id": "studio-pc", "name": "Studio PC", "status": "online", "role": "operator"},
        {"id": "laptop", "name": "Laptop", "status": "offline", "role": "managed"}
    ]}
}

def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return DEFAULT

def save_state(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def sources():
    return json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]

def validate_source(item):
    """Only allow a normal public GitHub HTTPS source in the local MVP."""
    repo = item.get("repository", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", item.get("id", "")):
        raise ValueError("원본 ID가 올바르지 않습니다.")
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", repo):
        raise ValueError("GitHub HTTPS 저장소 주소만 허용됩니다.")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", item.get("catalogPath", "apps")):
        raise ValueError("카탈로그 경로가 올바르지 않습니다.")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", item.get("branch", "main")):
        raise ValueError("브랜치 이름이 올바르지 않습니다.")

def apps():
    result = []
    locations = [CATALOG]
    for source in sources():
        cached = CACHE / source["id"] / source.get("catalogPath", "apps")
        if source.get("enabled") and cached.is_dir(): locations.append(cached)
    for location in locations:
        for manifest in location.glob("*/manifest.json"):
            item = json.loads(manifest.read_text(encoding="utf-8"))
            if all(item.get("id") != existing.get("id") for existing in result): result.append(item)
    return result

def sync_source(source):
    validate_source(source)
    if not shutil.which("git"): raise RuntimeError("Git이 설치되어 있지 않습니다.")
    target = CACHE / source["id"]
    CACHE.mkdir(exist_ok=True)
    if target.exists():
        command = ["git", "-C", str(target), "fetch", "--depth", "1", "origin", source.get("branch", "main")]
    else:
        command = ["git", "clone", "--depth", "1", "--branch", source.get("branch", "main"), source["repository"], str(target)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    if completed.returncode: raise RuntimeError(completed.stderr.strip() or "Git 동기화에 실패했습니다.")
    return {"id": source["id"], "name": source["name"], "syncedAt": datetime.now(timezone.utc).isoformat()}

class OpusHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def json(self, payload, status=HTTPStatus.OK):
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        state = load_state()
        if path == "/api/apps": return self.json({"apps": apps(), "installed": state["installed"]})
        if path == "/api/sources": return self.json(sources())
        if path == "/api/automations": return self.json(state["automations"])
        if path == "/api/workspace": return self.json(state["workspace"])
        return super().do_GET()

    def do_POST(self):
        path, data, state = urlparse(self.path).path, self.read_json(), load_state()
        if path.startswith("/api/apps/") and path.endswith("/install"):
            app_id = path.split("/")[3]
            if app_id not in state["installed"]: state["installed"].append(app_id)
            save_state(state); return self.json({"ok": True, "message": "설치 요청이 기록되었습니다."})
        if path.startswith("/api/apps/") and path.endswith("/uninstall"):
            app_id = path.split("/")[3]
            state["installed"] = [x for x in state["installed"] if x != app_id]
            save_state(state); return self.json({"ok": True, "message": "제거 요청이 기록되었습니다."})
        if path == "/api/automations":
            item = {"id": data.get("id") or f"flow-{int(datetime.now().timestamp())}", "name": data.get("name", "새 자동화"), "enabled": bool(data.get("enabled", True)), "actions": data.get("actions", [])}
            state["automations"] = [x for x in state["automations"] if x["id"] != item["id"]] + [item]
            save_state(state); return self.json(item)
        if path == "/api/sources":
            incoming = data.get("sources", [])
            if not isinstance(incoming, list): return self.json({"error": "sources must be a list"}, HTTPStatus.BAD_REQUEST)
            for source in incoming: validate_source(source)
            SOURCES.write_text(json.dumps({"version": 1, "sources": incoming}, ensure_ascii=False, indent=2), encoding="utf-8")
            return self.json(incoming)
        if path == "/api/sources/sync":
            try:
                item = next(x for x in sources() if x["id"] == data.get("id"))
                return self.json(sync_source(item))
            except StopIteration: return self.json({"error": "원본을 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
            except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/workspace/command":
            # Network dispatch deliberately omitted. Production requires signed remote jobs.
            return self.json({"ok": True, "queuedAt": datetime.now(timezone.utc).isoformat(), "targets": data.get("targets", [])})
        return self.json({"error": "not found"}, HTTPStatus.NOT_FOUND)

if __name__ == "__main__":
    print("OPUS API: http://127.0.0.1:47821")
    ThreadingHTTPServer(("127.0.0.1", 47821), OpusHandler).serve_forever()
