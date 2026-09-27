"""OPUS local controller. It binds to loopback only; never expose it directly."""
from __future__ import annotations

import json, re, shutil, subprocess, threading, time, uuid
from copy import deepcopy
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB, CATALOG = ROOT / "web", ROOT / "catalog" / "apps"
SOURCES, CACHE, STATE = ROOT / "catalog" / "sources.json", ROOT / ".opus-catalog-cache", ROOT / ".opus-state.json"
LOCK = threading.Lock()
ROLE_NAMES = {"admin": "관리자", "operator": "부관리자", "managed": "관리 대상"}
POLICIES = {"admin": {"install", "uninstall", "automation", "workspace_command", "source"},
            "operator": {"install", "uninstall", "automation", "workspace_command"}, "managed": set()}
DEFAULT = {
    "installed": [], "operations": [], "audit": [],
    "automations": [{"id": "morning-focus", "name": "아침 집중 모드", "enabled": True, "actions": [
        {"type": "notify", "label": "집중 시간을 시작합니다"}, {"type": "wait", "seconds": 2, "label": "2초 대기"}]}],
    "workspace": {"name": "내 OPUS 워크스페이스", "role": "admin", "devices": [
        {"id": "this-pc", "name": "이 PC", "status": "online", "role": "admin", "lastSeen": "지금"},
        {"id": "studio-pc", "name": "Studio PC", "status": "online", "role": "operator", "lastSeen": "2분 전"},
        {"id": "laptop", "name": "Laptop", "status": "offline", "role": "managed", "lastSeen": "어제"}],
        "policy": {"operator": ["install", "uninstall", "automation", "workspace_command"]}}
}

def now(): return datetime.now(timezone.utc).isoformat()
def load_state():
    with LOCK:
        saved = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        result = deepcopy(DEFAULT); result.update(saved)
        for key in ("installed", "operations", "audit", "automations"): result.setdefault(key, deepcopy(DEFAULT[key]))
        result["workspace"].setdefault("policy", deepcopy(DEFAULT["workspace"]["policy"]))
        return result
def save_state(state):
    with LOCK: STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
def audit(state, kind, detail):
    state["audit"] = ([{"at": now(), "kind": kind, "detail": detail}] + state["audit"])[:100]

def sources(): return json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]
def validate_source(item):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", item.get("id", "")): raise ValueError("원본 ID가 올바르지 않습니다.")
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", item.get("repository", "")): raise ValueError("GitHub HTTPS 저장소 주소만 허용됩니다.")
    for field, default in (("catalogPath", "apps"), ("branch", "main")):
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", item.get(field, default)): raise ValueError(f"{field} 값이 올바르지 않습니다.")
def sync_source(source):
    validate_source(source)
    if not shutil.which("git"): raise RuntimeError("Git이 설치되어 있지 않습니다.")
    target = CACHE / source["id"]; CACHE.mkdir(exist_ok=True)
    command = (["git", "-C", str(target), "fetch", "--depth", "1", "origin", source.get("branch", "main")]
               if target.exists() else ["git", "clone", "--depth", "1", "--branch", source.get("branch", "main"), source["repository"], str(target)])
    done = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    if done.returncode: raise RuntimeError(done.stderr.strip() or "Git 동기화에 실패했습니다.")
    return {"id": source["id"], "name": source["name"], "syncedAt": now()}

def catalog_apps():
    found, locations = [], [CATALOG]
    for source in sources():
        cached = CACHE / source["id"] / source.get("catalogPath", "apps")
        if source.get("enabled") and cached.is_dir(): locations.append(cached)
    for location in locations:
        for manifest in location.glob("*/manifest.json"):
            try:
                app = json.loads(manifest.read_text(encoding="utf-8"))
                if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", app.get("id", "")) and not any(x["id"] == app["id"] for x in found): found.append(app)
            except (OSError, json.JSONDecodeError): pass
    return found
def find_app(app_id): return next((x for x in catalog_apps() if x["id"] == app_id), None)
def authorized(state, capability):
    role = state["workspace"]["role"]
    allowed = set(state["workspace"].get("policy", {}).get("operator", [])) if role == "operator" else POLICIES.get(role, set())
    return capability in allowed

def create_operation(state, kind, target):
    op = {"id": str(uuid.uuid4()), "kind": kind, "target": target, "status": "queued", "createdAt": now(), "output": []}
    state["operations"] = [op] + state["operations"]; save_state(state); return op
def append_operation(op_id, status, line):
    state = load_state()
    for op in state["operations"]:
        if op["id"] == op_id:
            op["status"] = status; op["output"].append({"at": now(), "line": line})
            if status in ("completed", "failed"): op["finishedAt"] = now()
    save_state(state)
def run_package_operation(op_id, app, action):
    append_operation(op_id, "running", "winget 실행을 준비합니다.")
    package_id = app.get("wingetId")
    if not package_id or not re.fullmatch(r"[A-Za-z0-9_.-]+", package_id): return append_operation(op_id, "failed", "검증된 winget 패키지 ID가 없습니다.")
    if not shutil.which("winget"): return append_operation(op_id, "failed", "winget이 설치되어 있지 않습니다.")
    command = ["winget", action, "--id", package_id, "--exact", "--accept-source-agreements"]
    if action == "install": command += ["--accept-package-agreements"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
        output = (done.stdout + "\n" + done.stderr).strip()[-6000:] or "winget이 출력 없이 종료되었습니다."
        append_operation(op_id, "completed" if done.returncode == 0 else "failed", output)
        state = load_state(); installed = state["installed"]
        if done.returncode == 0 and action == "install" and app["id"] not in installed: installed.append(app["id"])
        if done.returncode == 0 and action == "uninstall": state["installed"] = [x for x in installed if x != app["id"]]
        audit(state, action, app["id"]); save_state(state)
    except subprocess.TimeoutExpired: append_operation(op_id, "failed", "winget 실행 시간이 초과되었습니다.")

def run_automation(op_id, flow):
    append_operation(op_id, "running", f"{flow['name']} 실행을 시작합니다.")
    stack, index = [], 0
    try:
        actions = flow.get("actions", [])
        while index < len(actions):
            action = actions[index]; kind = action.get("type")
            if kind == "if": stack.append(bool(action.get("value", True)))
            elif kind == "repeat": stack.extend([True] * min(max(int(action.get("count", 1)), 0), 20))
            elif kind == "end":
                if stack: stack.pop()
            elif all(stack) if stack else True:
                if kind == "wait": time.sleep(min(max(float(action.get("seconds", 1)), 0), 30)); append_operation(op_id, "running", f"{action.get('seconds', 1)}초 대기 완료")
                elif kind == "notify": append_operation(op_id, "running", f"알림: {action.get('label', 'OPUS 자동화')}")
                elif kind == "open_url":
                    url = action.get("url", "")
                    if not re.fullmatch(r"https?://[^\s]+", url): raise ValueError("허용되지 않은 URL입니다.")
                    subprocess.Popen(["cmd", "/c", "start", "", url], shell=False); append_operation(op_id, "running", f"브라우저 열기: {url}")
                else: append_operation(op_id, "running", f"지원 예정 동작: {kind}")
            index += 1
        append_operation(op_id, "completed", "자동화가 완료되었습니다.")
    except (ValueError, OSError) as error: append_operation(op_id, "failed", str(error))

class OpusHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(WEB), **kwargs)
    def json(self, payload, status=HTTPStatus.OK):
        encoded = json.dumps(payload, ensure_ascii=False).encode(); self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
    def read_json(self):
        try: return json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 1_000_000)) or b"{}")
        except json.JSONDecodeError: return {}
    def denied(self): return self.json({"error": "현재 역할에 이 권한이 없습니다."}, HTTPStatus.FORBIDDEN)
    def do_GET(self):
        path, state = urlparse(self.path).path, load_state()
        if path == "/api/apps": return self.json({"apps": catalog_apps(), "installed": state["installed"]})
        if path == "/api/sources": return self.json(sources())
        if path == "/api/automations": return self.json(state["automations"])
        if path == "/api/workspace": return self.json(state["workspace"])
        if path == "/api/operations": return self.json(state["operations"][:30])
        if path == "/api/audit": return self.json(state["audit"][:30])
        return super().do_GET()
    def do_POST(self):
        path, data, state = urlparse(self.path).path, self.read_json(), load_state()
        if path.startswith("/api/apps/") and path.rsplit("/", 1)[-1] in ("install", "uninstall"):
            action, app_id = path.rsplit("/", 1)[-1], path.split("/")[3]
            if not authorized(state, action): return self.denied()
            app = find_app(app_id)
            if not app: return self.json({"error": "앱을 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
            op = create_operation(state, action, app_id); threading.Thread(target=run_package_operation, args=(op["id"], app, action), daemon=True).start(); return self.json(op, HTTPStatus.ACCEPTED)
        if path == "/api/automations":
            if not authorized(state, "automation"): return self.denied()
            item = {"id": data.get("id") or f"flow-{uuid.uuid4().hex[:8]}", "name": str(data.get("name", "새 자동화"))[:80], "enabled": bool(data.get("enabled", True)), "actions": data.get("actions", [])[:100]}
            state["automations"] = [x for x in state["automations"] if x["id"] != item["id"]] + [item]; audit(state, "automation_saved", item["name"]); save_state(state); return self.json(item)
        if path.startswith("/api/automations/") and path.endswith("/run"):
            if not authorized(state, "automation"): return self.denied()
            flow = next((x for x in state["automations"] if x["id"] == path.split("/")[3]), None)
            if not flow: return self.json({"error": "자동화를 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
            op = create_operation(state, "automation", flow["id"]); threading.Thread(target=run_automation, args=(op["id"], flow), daemon=True).start(); return self.json(op, HTTPStatus.ACCEPTED)
        if path == "/api/sources":
            if not authorized(state, "source"): return self.denied()
            incoming = data.get("sources", []); [validate_source(x) for x in incoming]
            SOURCES.write_text(json.dumps({"version": 1, "sources": incoming}, ensure_ascii=False, indent=2), encoding="utf-8"); return self.json(incoming)
        if path == "/api/sources/sync":
            if not authorized(state, "source"): return self.denied()
            try: return self.json(sync_source(next(x for x in sources() if x["id"] == data.get("id"))))
            except StopIteration: return self.json({"error": "원본을 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
            except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error: return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/workspace/command":
            if not authorized(state, "workspace_command"): return self.denied()
            targets = [x for x in data.get("targets", []) if any(d["id"] == x for d in state["workspace"]["devices"])]
            op = create_operation(state, "workspace_command", ",".join(targets)); append_operation(op["id"], "queued", "원격 에이전트 연결 대기 중입니다."); audit(state, "workspace_command", ",".join(targets)); save_state(state); return self.json(op, HTTPStatus.ACCEPTED)
        return self.json({"error": "not found"}, HTTPStatus.NOT_FOUND)

if __name__ == "__main__":
    print("OPUS API: http://127.0.0.1:47821")
    ThreadingHTTPServer(("127.0.0.1", 47821), OpusHandler).serve_forever()
