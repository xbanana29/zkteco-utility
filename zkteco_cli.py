#!/usr/bin/env python3
"""
ZKTeco headless CLI agent — pull absensi from eFace10 and sync to VST cloud.

Usage:
  python zkteco_cli.py test-device
  python zkteco_cli.py test-cloud
  python zkteco_cli.py pull
  python zkteco_cli.py sync
  python zkteco_cli.py run-once
  python zkteco_cli.py daemon            # live capture + full pull every 60 min
  python zkteco_cli.py daemon --no-live  # old mode: full pull every --interval min
  python zkteco_cli.py status

Env:
  ZKTECO_CONFIG       path to config.json
  ZKTECO_CLOUD_TOKEN  overrides cloud_api_token
  ZKTECO_CLOUD_URL    overrides cloud_api_url
  ZKTECO_DEVICE_IP / ZKTECO_DEVICE_PORT
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys

import zkteco_core as core


def _setup_logging(verbose: bool, log_file: str | None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def _resolve_config_path(args) -> str:
    if getattr(args, "config", None):
        return os.path.abspath(args.config)
    env = os.environ.get("ZKTECO_CONFIG")
    if env:
        return os.path.abspath(env)
    return core.CONFIG_FILE


def _load(args) -> dict:
    cfg_path = _resolve_config_path(args)
    core.set_paths(config_file=cfg_path)
    # DB next to config by default
    if not os.environ.get("ZKTECO_DB"):
        core.set_paths(db_file=os.path.join(os.path.dirname(cfg_path), "absensi.db"))
    else:
        core.set_paths(db_file=os.environ["ZKTECO_DB"])
    cfg = core.load_config(cfg_path)
    if getattr(args, "interval", None) is not None:
        cfg["auto_pull_interval_min"] = int(args.interval)
    return cfg


def cmd_test_device(args) -> int:
    cfg = _load(args)
    info = core.test_device(cfg)
    print(json.dumps(info, indent=2, default=str))
    return 0


def cmd_test_cloud(args) -> int:
    cfg = _load(args)
    # allow test even if flag disabled
    cfg = dict(cfg)
    cfg["cloud_sync_enabled"] = True
    result = core.cloud_credentials_ok(cfg)
    print(json.dumps(result, indent=2))
    return 0


def cmd_pull(args) -> int:
    cfg = _load(args)
    core.init_db()
    do_cloud = False if args.no_cloud else None
    result = core.pull_attendance(cfg, do_cloud=do_cloud)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


def cmd_sync(args) -> int:
    cfg = _load(args)
    core.init_db()
    cfg = dict(cfg)
    cfg["cloud_sync_enabled"] = True
    result = core.cloud_sync(cfg, punches=None)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_run_once(args) -> int:
    cfg = _load(args)
    core.init_db()
    result = core.run_once(cfg, no_cloud=bool(args.no_cloud))
    print(json.dumps(result, indent=2, default=str))
    pull = result.get("pull") or {}
    return 0 if pull.get("ok") else 1


def cmd_daemon(args) -> int:
    cfg = _load(args)
    core.init_db()
    stop = {"flag": False}

    def _sig(*_a):
        logging.getLogger("zkteco").info("Signal received — stopping after cycle/sleep")
        stop["flag"] = True

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    if args.no_live:
        cfg["live_capture"] = False
    core.daemon_loop(
        cfg,
        interval_min=args.interval,
        no_cloud=bool(args.no_cloud),
        stop_flag=lambda: stop["flag"],
    )
    return 0


def cmd_status(args) -> int:
    cfg = _load(args)
    core.init_db()
    sessions = core.db_get_pull_sessions(5)
    status = {
        "config_file": core.CONFIG_FILE,
        "db_file": core.DB_FILE,
        "device": f"{cfg.get('ip')}:{cfg.get('port')}",
        "cloud_enabled": bool(cfg.get("cloud_sync_enabled")),
        "cloud_url": core.normalize_cloud_base_url(cfg.get("cloud_api_url") or ""),
        "cloud_token": core.redact_token(cfg.get("cloud_api_token") or ""),
        "interval_min": cfg.get("auto_pull_interval_min"),
        "live_capture": bool(cfg.get("live_capture")),
        "full_pull_interval_min": cfg.get("full_pull_interval_min"),
        "history_sync_time": cfg.get("history_sync_time"),
        "last_live_start": core.agent_state_get("last_live_start"),
        "last_history_sync_date": core.agent_state_get("last_history_sync_date"),
        "cloud_pending": core.agent_state_get("cloud_pending") == "1",
        "db_punch_count": core.db_count(),
        "user_map_count": len(cfg.get("user_map") or {}),
        "last_pull": core.agent_state_get("last_pull"),
        "last_pull_note": core.agent_state_get("last_pull_note"),
        "last_cloud_sync": core.agent_state_get("last_cloud_sync"),
        "recent_sessions": [
            {
                "id": r[0],
                "pulled_at": r[1],
                "records": r[2],
                "new": r[3],
                "ip": r[4],
                "note": r[5] if len(r) > 5 else "",
            }
            for r in sessions
        ],
    }
    print(json.dumps(status, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    # Shared flags work before OR after subcommand (parents=)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        "-c",
        help="Path config.json (default: ./config.json or $ZKTECO_CONFIG)",
    )
    common.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    common.add_argument("--log-file", help="Also write logs to file")
    common.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Override auto_pull_interval_min (daemon)",
    )
    common.add_argument(
        "--no-cloud",
        action="store_true",
        help="Skip cloud POST (pull/run-once/daemon only)",
    )
    common.add_argument(
        "--no-live",
        action="store_true",
        help="Daemon without live capture (full pull every --interval min)",
    )

    p = argparse.ArgumentParser(
        prog="zkteco-cli",
        description="ZKTeco eFace10 headless agent — pull absensi & sync VST cloud",
        parents=[common],
    )
    sub = p.add_subparsers(dest="command", required=True)

    for name, help_ in (
        ("test-device", "Connect device, show info"),
        ("test-cloud", "GET /employees credential test"),
        ("pull", "Pull device → SQLite (+ cloud if enabled)"),
        ("sync", "Full SQLite → VST cloud sync"),
        ("run-once", "One pull(+cloud) cycle"),
        ("daemon", "Loop forever (systemd)"),
        ("status", "Show agent status (token redacted)"),
    ):
        sub.add_parser(name, help=help_, parents=[common])

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose, args.log_file)

    handlers = {
        "test-device": cmd_test_device,
        "test-cloud": cmd_test_cloud,
        "pull": cmd_pull,
        "sync": cmd_sync,
        "run-once": cmd_run_once,
        "daemon": cmd_daemon,
        "status": cmd_status,
    }
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        logging.getLogger("zkteco").error("%s", e)
        if args.verbose:
            logging.getLogger("zkteco").exception("detail")
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
