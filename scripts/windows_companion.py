from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import sys
import time
import tkinter as tk
import webbrowser
from datetime import datetime, timezone
from ctypes import wintypes
from tkinter import ttk
from urllib import error, request


DEFAULT_DASHBOARD_URL = "http://127.0.0.1:37801"
POLL_MS = 700
HEARTBEAT_SECONDS = 2.5
ERROR_ALREADY_EXISTS = 183
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 42
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_SYSCOMMAND = 0x0112
SC_MINIMIZE = 0xF020
GWLP_WNDPROC = -4
NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
IDI_APPLICATION = 32512
WNDPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
COMPANION_MUTEX_HANDLE = None


class NotifyIconData(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HANDLE),
        ("szTip", wintypes.WCHAR * 128),
    ]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def foreground_window_title() -> str:
    user32 = ctypes.windll.user32
    handle = user32.GetForegroundWindow()
    if not handle:
        return ""
    length = user32.GetWindowTextLengthW(handle)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(handle, buffer, length + 1)
    return buffer.value


def looks_like_codex(title: str) -> bool:
    lowered = title.lower()
    return "codex" in lowered and "companion" not in lowered and "dashboard" not in lowered


def acquire_mutex() -> bool:
    global COMPANION_MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    COMPANION_MUTEX_HANDLE = kernel32.CreateMutexW(None, False, "Global\\CodexMemCompanion")
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


class DashboardClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def json(self, path: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def event(self, payload: dict) -> None:
        try:
            self.json("/api/companion-event", payload, timeout=2.0)
        except (OSError, error.URLError, TimeoutError):
            pass


class CompanionApp:
    def __init__(self, dashboard_url: str) -> None:
        self.client = DashboardClient(dashboard_url)
        self.dashboard_url = dashboard_url.rstrip("/")
        self.root = tk.Tk()
        self.root.title("Codex Mem Companion")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.root.bind("<Unmap>", self.on_unmap)

        self.include_context = tk.BooleanVar(value=True)
        self.watch_codex = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="Connecting to dashboard...")
        self.detail_text = tk.StringVar(value="")
        self.button_text = tk.StringVar(value="Copy + hide")

        self.auto_select_limit = 3
        self.last_title = ""
        self.last_heartbeat = 0.0
        self.suppress_until_blur = False
        self.visible_once = False
        self.hidden_to_tray = False
        self.hwnd = None
        self.tray_added = False
        self._notify_data = None
        self._old_wnd_proc = None
        self._wnd_proc_ref = None

        self.build_ui()
        self.place_window()
        self.install_tray_icon()
        atexit.register(self.remove_tray_icon)
        self.load_dashboard_state()
        self.root.after(POLL_MS, self.tick)

    def build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)

        title = ttk.Label(frame, text="Codex Mem", font=("Segoe UI", 12, "bold"))
        title.grid(row=0, column=0, sticky="w")

        status = ttk.Label(frame, textvariable=self.status_text, wraplength=300)
        status.grid(row=1, column=0, sticky="we", pady=(6, 0))
        detail = ttk.Label(frame, textvariable=self.detail_text, foreground="#5d6871", wraplength=300)
        detail.grid(row=2, column=0, sticky="we", pady=(2, 10))

        include = ttk.Checkbutton(
            frame,
            text="Include startup context",
            variable=self.include_context,
            command=self.toggle_startup_context,
        )
        include.grid(row=3, column=0, sticky="w")

        watch = ttk.Checkbutton(frame, text="Show when Codex is active", variable=self.watch_codex)
        watch.grid(row=4, column=0, sticky="w", pady=(2, 10))

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky="we")
        buttons.columnconfigure(0, weight=1)
        ttk.Button(buttons, textvariable=self.button_text, command=self.copy_context_and_hide).grid(
            row=0,
            column=0,
            sticky="we",
        )
        ttk.Button(buttons, text="Dashboard", command=lambda: webbrowser.open(self.dashboard_url)).grid(
            row=0,
            column=1,
            padx=(8, 0),
        )
        ttk.Button(buttons, text="Hide", command=self.hide_to_tray).grid(row=0, column=2, padx=(8, 0))

    def place_window(self) -> None:
        self.root.update_idletasks()
        width = 360
        height = 205
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(12, screen_width - width - 24)
        y = max(12, screen_height - height - 72)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def install_tray_icon(self) -> None:
        if sys.platform != "win32":
            return
        self.root.update_idletasks()
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = wintypes.HWND
        self.hwnd = user32.FindWindowW(None, self.root.title()) or self.root.winfo_id()
        self.install_window_proc()
        self.add_tray_icon()

    def on_unmap(self, event) -> None:
        if event.widget == self.root:
            self.root.after(80, self.hide_if_iconified)

    def hide_if_iconified(self) -> None:
        try:
            state = self.root.state()
        except tk.TclError:
            return
        if state == "iconic":
            self.hide_to_tray()

    def install_window_proc(self) -> None:
        if not self.hwnd or self._wnd_proc_ref:
            return
        user32 = ctypes.windll.user32
        self._wnd_proc_ref = WNDPROC(self.window_proc)
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        self._old_wnd_proc = user32.SetWindowLongPtrW(
            self.hwnd,
            GWLP_WNDPROC,
            ctypes.cast(self._wnd_proc_ref, ctypes.c_void_p).value,
        )

    def window_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            event = int(lparam)
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_CONTEXTMENU):
                self.root.after(0, self.restore_from_tray)
                return 0
        if msg == WM_SYSCOMMAND and (int(wparam) & 0xFFF0) == SC_MINIMIZE:
            self.root.after(0, self.hide_to_tray)
            return 0
        if self._old_wnd_proc:
            ctypes.windll.user32.CallWindowProcW.restype = wintypes.LPARAM
            return ctypes.windll.user32.CallWindowProcW(self._old_wnd_proc, hwnd, msg, wparam, lparam)
        ctypes.windll.user32.DefWindowProcW.restype = wintypes.LPARAM
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def add_tray_icon(self) -> None:
        if self.tray_added or not self.hwnd:
            return
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        user32.LoadIconW.restype = wintypes.HANDLE
        icon_handle = user32.LoadIconW(None, IDI_APPLICATION)

        data = NotifyIconData()
        data.cbSize = ctypes.sizeof(NotifyIconData)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAYICON
        data.hIcon = icon_handle
        data.szTip = "Codex Mem Companion"
        self._notify_data = data
        self.tray_added = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)))

    def remove_tray_icon(self) -> None:
        if not self.tray_added or not self._notify_data:
            return
        try:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._notify_data))
        except Exception:
            pass
        self.tray_added = False

    def load_dashboard_state(self) -> None:
        try:
            payload = self.client.json("/api/bootstrap")
        except (OSError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.status_text.set("Dashboard is not reachable.")
            self.detail_text.set(str(exc))
            self.client.event({"type": "connect_failed", "details": str(exc)})
            return
        settings = payload.get("settings") or {}
        self.include_context.set(bool(settings.get("startup_context_enabled", True)))
        self.auto_select_limit = int(settings.get("startup_auto_select_limit") or 3)
        related = ((payload.get("overview") or {}).get("related") or [])
        self.status_text.set(f"{min(len(related), self.auto_select_limit)} context rows ready")
        self.detail_text.set("Paste the copied context into the first Codex message.")
        self.client.event({"type": "connected", "details": "Companion app loaded."})

    def toggle_startup_context(self) -> None:
        enabled = self.include_context.get()
        try:
            self.client.json(
                "/api/settings",
                {
                    "startup_context_enabled": enabled,
                    "startup_auto_select_limit": self.auto_select_limit,
                },
            )
        except (OSError, error.URLError, TimeoutError):
            self.status_text.set("Could not save setting.")
        self.client.event({"type": "startup_toggle", "details": f"enabled={enabled}"})

    def build_context_bundle(self) -> dict:
        payload = self.client.json("/api/bootstrap")
        settings = payload.get("settings") or {}
        limit = int(settings.get("startup_auto_select_limit") or self.auto_select_limit)
        overview = payload.get("overview") or {}
        rows = list(overview.get("related") or [])
        session_ids = [row.get("session_id") for row in rows[:limit] if row.get("session_id")]
        request_payload = {
            "cwd": "",
            "project_group": "",
            "query": "",
            "limit": limit,
            "session_ids": session_ids if self.include_context.get() else [],
            "file_paths": [],
        }
        if self.include_context.get():
            self.client.json("/api/selected-startup-context", {**request_payload, "enabled": True})
        else:
            self.client.json("/api/selected-startup-context", {"clear": True, "enabled": False})
        return self.client.json("/api/context-bundle", request_payload)

    def copy_context_and_hide(self) -> None:
        self.button_text.set("Copying...")
        self.root.update_idletasks()
        try:
            bundle = self.build_context_bundle()
            text = str(bundle.get("text") or "")
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            chars = int(bundle.get("character_count") or len(text))
            self.status_text.set("Context copied.")
            self.detail_text.set(f"{chars:,} characters on clipboard. Paste into Codex and press Enter.")
            self.client.event(
                {
                    "type": "context_copied",
                    "details": f"{chars} chars",
                    "window_title": self.last_title,
                    "codex_focused": looks_like_codex(self.last_title),
                    "overlay_visible": True,
                }
            )
            self.root.after(1300, self.hide_to_tray)
        except (OSError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.status_text.set("Copy failed.")
            self.detail_text.set(str(exc))
            self.client.event({"type": "copy_failed", "details": str(exc)})
        finally:
            self.button_text.set("Copy + hide")

    def show(self) -> None:
        self.hidden_to_tray = False
        self.visible_once = True
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)

    def restore_from_tray(self) -> None:
        self.suppress_until_blur = False
        self.show()
        self.client.event(
            {
                "type": "overlay_restored",
                "window_title": self.last_title,
                "codex_focused": looks_like_codex(self.last_title),
                "overlay_visible": True,
            }
        )

    def hide_to_tray(self) -> None:
        self.hidden_to_tray = True
        self.suppress_until_blur = True
        self.root.withdraw()
        self.client.event(
            {
                "type": "overlay_hidden",
                "window_title": self.last_title,
                "codex_focused": looks_like_codex(self.last_title),
                "overlay_visible": False,
            }
        )

    def overlay_visible(self) -> bool:
        if self.hidden_to_tray:
            return False
        try:
            return self.root.state() not in {"withdrawn", "iconic"}
        except tk.TclError:
            return False

    def tick(self) -> None:
        try:
            if self.root.state() == "iconic":
                self.hide_to_tray()
        except tk.TclError:
            return

        try:
            self.last_title = foreground_window_title()
        except Exception:
            self.last_title = ""
        codex_focused = looks_like_codex(self.last_title)

        if not codex_focused:
            self.suppress_until_blur = False
        elif self.watch_codex.get() and not self.suppress_until_blur and not self.hidden_to_tray:
            self.show()

        if self.hidden_to_tray:
            self.root.withdraw()

        now = time.monotonic()
        if now - self.last_heartbeat > HEARTBEAT_SECONDS:
            self.last_heartbeat = now
            self.client.event(
                {
                    "type": "heartbeat",
                    "at": now_iso(),
                    "window_title": self.last_title,
                    "codex_focused": codex_focused,
                    "overlay_visible": self.overlay_visible(),
                }
            )
        self.root.after(POLL_MS, self.tick)

    def run(self) -> int:
        self.show()
        try:
            self.root.mainloop()
        finally:
            self.remove_tray_icon()
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex Mem Windows companion overlay")
    parser.add_argument("--dashboard-url", default=DEFAULT_DASHBOARD_URL)
    return parser


def main() -> int:
    if sys.platform != "win32":
        print("The companion app currently supports Windows only.", file=sys.stderr)
        return 2
    if not acquire_mutex():
        return 0
    args = build_parser().parse_args()
    return CompanionApp(args.dashboard_url).run()


if __name__ == "__main__":
    raise SystemExit(main())
