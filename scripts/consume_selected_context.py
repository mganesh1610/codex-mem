from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


DEFAULT_PATH = Path.home() / ".codex" / "memories" / "codex-mem" / "selected_startup_context.md"
DEFAULT_CLEAR_SIGNAL_PATH = DEFAULT_PATH.parent / "selected_startup_context_clear.json"
DEFAULT_SETTINGS_PATH = DEFAULT_PATH.parent / "dashboard_settings.json"
DEFAULT_MAX_AGE_MINUTES = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consume Codex Mem selected startup context.")
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--clear-signal-path", default=str(DEFAULT_CLEAR_SIGNAL_PATH))
    parser.add_argument("--settings-path", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--max-age-minutes", type=int, default=DEFAULT_MAX_AGE_MINUTES)
    parser.add_argument("--clear-only", action="store_true")
    parser.add_argument("--keep-dashboard-enabled", action="store_true")
    return parser.parse_args()


def write_clear_signal(signal_path: Path, context_path: Path, reason: str) -> None:
    payload = {
        "token": f"{datetime.now(timezone.utc).isoformat()}-{uuid4().hex[:8]}",
        "cleared_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "context_path": str(context_path),
    }
    try:
        signal_path.parent.mkdir(parents=True, exist_ok=True)
        signal_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def disable_dashboard_startup(settings_path: Path) -> None:
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw["startup_context_enabled"] = False
    raw.setdefault("startup_auto_select_limit", 3)
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    except OSError:
        pass


def clear(
    path: Path,
    *,
    signal_path: Path,
    settings_path: Path,
    reason: str,
    keep_dashboard_enabled: bool,
) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    write_clear_signal(signal_path, path, reason)
    if not keep_dashboard_enabled:
        disable_dashboard_startup(settings_path)


def main() -> int:
    args = parse_args()
    path = Path(args.path).expanduser()
    signal_path = Path(args.clear_signal_path).expanduser()
    settings_path = Path(args.settings_path).expanduser()
    if args.clear_only:
        clear(
            path,
            signal_path=signal_path,
            settings_path=settings_path,
            reason="clear-only",
            keep_dashboard_enabled=args.keep_dashboard_enabled,
        )
        return 0

    if not path.exists():
        clear(
            path,
            signal_path=signal_path,
            settings_path=settings_path,
            reason="startup-check-empty",
            keep_dashboard_enabled=args.keep_dashboard_enabled,
        )
        return 0

    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - modified).total_seconds()
        if age_seconds > max(60, args.max_age_minutes * 60):
            clear(
                path,
                signal_path=signal_path,
                settings_path=settings_path,
                reason="expired",
                keep_dashboard_enabled=args.keep_dashboard_enabled,
            )
            return 0
        text = path.read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        print(f"Could not read selected startup context: {exc}", file=sys.stderr)
        return 1

    clear(
        path,
        signal_path=signal_path,
        settings_path=settings_path,
        reason="consumed",
        keep_dashboard_enabled=args.keep_dashboard_enabled,
    )

    if text:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
