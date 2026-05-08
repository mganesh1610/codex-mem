from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request


DEFAULT_DASHBOARD_URL = "http://127.0.0.1:37801"
DEFAULT_PORT = 37801
CHECK_SECONDS = 2.0
STARTUP_GRACE_SECONDS = 8.0
ERROR_ALREADY_EXISTS = 183


def foreground_titles() -> list[str]:
    user32 = ctypes.windll.user32
    titles: list[str] = []

    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if title:
            titles.append(title)
        return True

    user32.EnumWindows(enum_windows_proc(callback), 0)
    return titles


def looks_like_codex(title: str) -> bool:
    lowered = title.lower()
    return "codex" in lowered and "companion" not in lowered and "dashboard" not in lowered


def codex_is_running() -> bool:
    return any(looks_like_codex(title) for title in foreground_titles())


def request_json(url: str, payload: dict | None = None, timeout: float = 3.0) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def dashboard_ok(base_url: str) -> bool:
    try:
        payload = request_json(f"{base_url.rstrip('/')}/api/health", timeout=1.5)
    except (OSError, error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    return bool(payload.get("ok"))


def companion_connected(base_url: str) -> bool:
    try:
        payload = request_json(f"{base_url.rstrip('/')}/api/companion-status", timeout=1.5)
    except (OSError, error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    return bool((payload.get("companion") or {}).get("connected"))


def post_event(base_url: str, event_type: str, details: str = "") -> None:
    try:
        request_json(
            f"{base_url.rstrip('/')}/api/companion-event",
            {
                "type": event_type,
                "details": details,
                "codex_focused": codex_is_running(),
                "overlay_visible": False,
            },
            timeout=1.5,
        )
    except (OSError, error.URLError, TimeoutError, json.JSONDecodeError):
        pass


def pythonw_path() -> str:
    current = Path(sys.executable)
    candidate = current.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else current)


def hidden_popen(args: list[str], cwd: Path) -> subprocess.Popen:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        args,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )


class AutostartWatcher:
    def __init__(self, repo_root: Path, dashboard_url: str, port: int) -> None:
        self.repo_root = repo_root.resolve(strict=False)
        self.dashboard_url = dashboard_url.rstrip("/")
        self.port = port
        self.dashboard_process: subprocess.Popen | None = None
        self.companion_process: subprocess.Popen | None = None
        self.last_codex_state = False
        self.last_dashboard_start = 0.0
        self.last_companion_start = 0.0

    def start_dashboard(self) -> None:
        now = time.monotonic()
        if now - self.last_dashboard_start < STARTUP_GRACE_SECONDS:
            return
        self.last_dashboard_start = now
        script = self.repo_root / "scripts" / "mcp_server.py"
        self.dashboard_process = hidden_popen(
            [
                sys.executable,
                str(script),
                "serve-ui",
                "--cwd",
                str(self.repo_root),
                "--port",
                str(self.port),
            ],
            cwd=self.repo_root,
        )

    def start_companion(self) -> None:
        now = time.monotonic()
        if now - self.last_companion_start < STARTUP_GRACE_SECONDS:
            return
        self.last_companion_start = now
        script = self.repo_root / "scripts" / "windows_companion.py"
        self.companion_process = hidden_popen(
            [
                pythonw_path(),
                str(script),
                "--dashboard-url",
                self.dashboard_url,
            ],
            cwd=self.repo_root,
        )
        post_event(self.dashboard_url, "companion_launch_requested", "Started by autostart watcher.")

    def ensure_stack(self) -> None:
        if not dashboard_ok(self.dashboard_url):
            self.start_dashboard()
            time.sleep(1.2)
        if dashboard_ok(self.dashboard_url) and not companion_connected(self.dashboard_url):
            self.start_companion()

    def run_once(self) -> bool:
        codex_now = codex_is_running()
        if codex_now and not self.last_codex_state:
            self.ensure_stack()
            post_event(self.dashboard_url, "codex_detected", "Autostart watcher detected Codex.")
        elif codex_now:
            self.ensure_stack()
        self.last_codex_state = codex_now
        return codex_now

    def run_forever(self) -> int:
        while True:
            self.run_once()
            time.sleep(CHECK_SECONDS)


def acquire_mutex() -> bool:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, "Global\\CodexMemAutostartWatcher")
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start Codex Mem when a Codex window appears.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--dashboard-url", default=DEFAULT_DASHBOARD_URL)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--once", action="store_true", help="Run one detection pass and exit.")
    return parser


def main() -> int:
    if sys.platform != "win32":
        print("The autostart watcher currently supports Windows only.", file=sys.stderr)
        return 2
    args = build_parser().parse_args()
    if not acquire_mutex():
        return 0
    watcher = AutostartWatcher(Path(args.repo_root), args.dashboard_url, args.port)
    if args.once:
        watcher.run_once()
        return 0
    return watcher.run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
