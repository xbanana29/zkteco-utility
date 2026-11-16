#!/usr/bin/env python3
"""
Headless-safe core for ZKTeco eFace10 → VST cloud sync.
No Qt/PySide6. Shared by zkteco_cli.py (and optionally desktop later).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("zkteco")

APP_VERSION = "5.3.0-agent"
ANOMALY_YEAR = 2000
LEAVE_TYPES = ("izin", "cuti", "dinas", "sakit")

DEFAULT_CONFIG: Dict[str, Any] = {
    "ip": "10.10.11.55",
    "port": 8088,
    "lang": "id",
    "jam_masuk": "07:00",
    "jam_keluar": "16:00",
    "toleransi": 15,
    "auto_backup": False,
    "auto_pull_interval_min": 15,
    "anomaly_recover": True,
    "anomaly_anchor": "",
    "punch_mode": "first_last",
    "comm_password": 0,
    "cloud_sync_enabled": True,
    "cloud_api_url": "https://service.rejekiamerta.com/api/attendance",
    "cloud_api_token": "",
    "cloud_sync_after_pull": True,
    # Daemon: hold a live_capture connection so each punch reaches VST within
    # seconds. A full pull still runs every full_pull_interval_min (missed
    # punches, clock check, year-2000 recovery); auto_pull_interval_min is the
    # fallback interval while live capture is not working.
    "live_capture": True,
    "full_pull_interval_min": 60,
    # Once a day the whole local history is re-sent, so the monthly Nextcloud
    # recap (VST server, 1st of the month 07:30) never misses a punch.
    "history_sync_time": "23:50",
    "user_map": {
        "1": "NICHOLAS",
        "2": "SERLI",
        "3": "MISRO",
        "4": "MISRO",
        "5": "LISA",
        "6": "TUR",
        "7": "SLAMET",
        "8": "ARI",
        "9": "REFA",
        "10": "SUKUR",
        "11": "PUGUH",
        "12": "LELI",
    },
}

# Paths — set via set_base() or defaults next to this file / executable
_BASE = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
CONFIG_FILE = os.path.join(_BASE, "config.json")
DB_FILE = os.path.join(_BASE, "absensi.db")


def set_base(path: str) -> None:
    """Point config/db to a working directory (agent deploy root)."""
    global _BASE, CONFIG_FILE, DB_FILE
    _BASE = os.path.abspath(path)
    CONFIG_FILE = os.path.join(_BASE, "config.json")
    DB_FILE = os.path.join(_BASE, "absensi.db")


def set_paths(config_file: Optional[str] = None, db_file: Optional[str] = None) -> None:
    global CONFIG_FILE, DB_FILE, _BASE
    if config_file:
        CONFIG_FILE = os.path.abspath(config_file)
        _BASE = os.path.dirname(CONFIG_FILE)
    if db_file:
        DB_FILE = os.path.abspath(db_file)


# ── Anomaly recovery ─────────────────────────────────────────────────────────
def is_anomaly_ts(ts) -> bool:
    return ts is None or getattr(ts, "year", 9999) <= ANOMALY_YEAR


def _sec_of_day(ts) -> int:
    return ts.hour * 3600 + ts.minute * 60 + ts.second


def find_gaps(normal_recs, min_len=1):
    dates = sorted({r["timestamp"].date() for r in normal_recs if r.get("timestamp")})
    if not dates:
        return []
    dset = set(dates)
    d = dates[0]
    gaps = []
    while d <= dates[-1]:
        if d not in dset and (d - timedelta(days=1)) in dset:
            s = d
            n = 0
            while d not in dset and d <= dates[-1] + timedelta(days=1):
                d += timedelta(days=1)
                n += 1
            if n >= min_len:
                gaps.append((s, n))
        else:
            d += timedelta(days=1)
    gaps.sort(key=lambda g: -g[1])
    return gaps


def find_gap_start(normal_recs, fallback=None, min_significant=2):
    gaps = find_gaps(normal_recs, min_len=1)
    if not gaps:
        return fallback
    significant = [g for g in gaps if g[1] >= min_significant]
    if len(significant) > 1:
        return None
    if significant:
        return significant[0][0]
    return gaps[0][0]


def remap_anomalies(anomaly_recs, anchor_date, jam_masuk="08:00", jam_keluar="16:00"):
    try:
        hi, mi = (int(x) for x in jam_masuk.split(":"))
        ho, mo = (int(x) for x in jam_keluar.split(":"))
    except Exception:
        hi, mi, ho, mo = 8, 0, 16, 0
    win_s = hi * 3600 + mi * 60 - 30 * 60
    win_e = ho * 3600 + mo * 60 + 60 * 60
    byfake = defaultdict(list)
    for r in anomaly_recs:
        if r.get("timestamp"):
            byfake[r["timestamp"].date()].append(r)
    out = []
    used = set()
    for i, fday in enumerate(sorted(byfake)):
        real = anchor_date + timedelta(days=i)
        recs = byfake[fday]
        secs = [_sec_of_day(r["timestamp"]) for r in recs]
        t0, t1 = min(secs), max(secs)
        span = (t1 - t0) or 1
        base = datetime(real.year, real.month, real.day)
        for r in sorted(recs, key=lambda x: x["timestamp"]):
            frac = (_sec_of_day(r["timestamp"]) - t0) / span
            nts = base + timedelta(seconds=int(win_s + frac * (win_e - win_s)))
            while nts in used:
                nts += timedelta(seconds=1)
            used.add(nts)
            nr = dict(r)
            nr["timestamp"] = nts
            nr["recovered"] = True
            nr["orig_ts"] = r["timestamp"]
            out.append(nr)
    return out


# ── Config ────────────────────────────────────────────────────────────────────
def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    cfg_path = path or CONFIG_FILE
    cfg = DEFAULT_CONFIG.copy()
    cfg["user_map"] = dict(DEFAULT_CONFIG["user_map"])
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in raw.items():
                cfg[k] = v
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
        except Exception as e:
            log.warning("Failed to load config %s: %s — using defaults", cfg_path, e)
    # Env overrides (secrets / deploy)
    if os.environ.get("ZKTECO_CLOUD_TOKEN"):
        cfg["cloud_api_token"] = os.environ["ZKTECO_CLOUD_TOKEN"]
    if os.environ.get("ZKTECO_CLOUD_URL"):
        cfg["cloud_api_url"] = os.environ["ZKTECO_CLOUD_URL"]
    if os.environ.get("ZKTECO_DEVICE_IP"):
        cfg["ip"] = os.environ["ZKTECO_DEVICE_IP"]
    if os.environ.get("ZKTECO_DEVICE_PORT"):
        try:
            cfg["port"] = int(os.environ["ZKTECO_DEVICE_PORT"])
        except ValueError:
            cfg["port"] = os.environ["ZKTECO_DEVICE_PORT"]
    # normalize types
    try:
        cfg["port"] = int(cfg.get("port") or 8088)
    except (TypeError, ValueError):
        cfg["port"] = 8088
    try:
        cfg["comm_password"] = int(cfg.get("comm_password") or 0)
    except (TypeError, ValueError):
        cfg["comm_password"] = 0
    try:
        cfg["auto_pull_interval_min"] = int(cfg.get("auto_pull_interval_min") or 0)
    except (TypeError, ValueError):
        cfg["auto_pull_interval_min"] = 15
    cfg["cloud_api_url"] = normalize_cloud_base_url(cfg.get("cloud_api_url") or "")
    cfg["cloud_api_token"] = normalize_cloud_token(cfg.get("cloud_api_token") or "")
    return cfg


def save_config(cfg: Dict[str, Any], path: Optional[str] = None) -> None:
    cfg_path = path or CONFIG_FILE
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def redact_token(token: str) -> str:
    t = token or ""
    if len(t) <= 12:
        return "***" if t else "(empty)"
    return f"{t[:6]}…{t[-4:]} ({len(t)} chars)"


# ── Database ──────────────────────────────────────────────────────────────────
def init_db() -> None:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER, nama TEXT,
        timestamp TEXT, punch INTEGER, pulled_at TEXT,
        recovered INTEGER DEFAULT 0,
        UNIQUE(uid, timestamp)
    )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS users (
        uid INTEGER PRIMARY KEY, nama TEXT,
        card_id TEXT, updated_at TEXT
    )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS pull_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pulled_at TEXT, record_count INTEGER, new_count INTEGER,
        device_ip TEXT, note TEXT
    )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS leave_days (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER NOT NULL, tanggal TEXT NOT NULL,
        jenis TEXT NOT NULL, note TEXT DEFAULT '',
        UNIQUE(uid, tanggal)
    )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS holidays (
        tanggal TEXT PRIMARY KEY, note TEXT DEFAULT '', created_at TEXT
    )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS agent_state (
        key TEXT PRIMARY KEY, value TEXT
    )"""
    )
    _migrate_attendance_schema(conn)
    conn.commit()
    conn.close()


def _migrate_attendance_schema(conn) -> None:
    c = conn.cursor()
    cols = {r[1] for r in c.execute("PRAGMA table_info(attendance)")}
    if not cols:
        return
    if "recovered" not in cols:
        try:
            c.execute("ALTER TABLE attendance ADD COLUMN recovered INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    idx = list(c.execute("PRAGMA index_list(attendance)"))
    need_rebuild = False
    has_pair = False
    for _, name, unique, *_ in idx:
        if not unique:
            continue
        info = list(c.execute(f'PRAGMA index_info("{name}")'))
        col_names = [r[2] for r in info]
        if col_names == ["timestamp"]:
            need_rebuild = True
        if col_names == ["uid", "timestamp"] or set(col_names) == {"uid", "timestamp"}:
            has_pair = True
    if not has_pair:
        need_rebuild = True
    if not need_rebuild:
        return
    c.execute(
        """CREATE TABLE IF NOT EXISTS attendance_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER, nama TEXT, timestamp TEXT,
        punch INTEGER, pulled_at TEXT, recovered INTEGER DEFAULT 0,
        UNIQUE(uid, timestamp)
    )"""
    )
    c.execute(
        """INSERT OR IGNORE INTO attendance_new
           (uid, nama, timestamp, punch, pulled_at, recovered)
           SELECT uid, nama, timestamp, punch, pulled_at,
                  COALESCE(recovered, 0) FROM attendance"""
    )
    c.execute("DROP TABLE attendance")
    c.execute("ALTER TABLE attendance_new RENAME TO attendance")


def db_insert_attendance(rows) -> Tuple[int, int]:
    new_rows, skip = db_insert_attendance_rows(rows)
    return len(new_rows), skip


def db_insert_attendance_rows(rows) -> Tuple[List[dict], int]:
    """Insert rows; return (rows that were new, duplicate count)."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_rows: List[dict] = []
    skip = 0
    for r in rows:
        ts = (
            r["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(r["timestamp"], "strftime")
            else str(r["timestamp"])
        )
        rec = 1 if r.get("recovered") else 0
        try:
            c.execute(
                "INSERT INTO attendance (uid,nama,timestamp,punch,pulled_at,recovered) "
                "VALUES (?,?,?,?,?,?)",
                (r["uid"], r["nama"], ts, r.get("punch", 0), now, rec),
            )
            new_rows.append(r)
        except sqlite3.IntegrityError:
            skip += 1
    conn.commit()
    conn.close()
    return new_rows, skip


def db_query_attendance(year=None, month=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    q = (
        "SELECT uid,nama,timestamp,punch,COALESCE(recovered,0) FROM attendance "
        "WHERE strftime('%Y',timestamp)>'2000'"
    )
    args = []
    if year:
        q += " AND strftime('%Y',timestamp)=?"
        args.append(str(year))
    if month:
        q += " AND strftime('%m',timestamp)=?"
        args.append(f"{month:02d}")
    q += " ORDER BY timestamp"
    c.execute(q, args)
    rows = [
        {
            "uid": r[0],
            "nama": r[1],
            "timestamp": datetime.strptime(r[2], "%Y-%m-%d %H:%M:%S"),
            "punch": r[3],
            "recovered": bool(r[4]),
        }
        for r in c.fetchall()
    ]
    conn.close()
    return rows


def db_count() -> int:
    conn = sqlite3.connect(DB_FILE)
    n = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE strftime('%Y',timestamp)>'2000'"
    ).fetchone()[0]
    conn.close()
    return n


def db_add_pull_session(record_count, new_count, device_ip, note="") -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO pull_sessions (pulled_at,record_count,new_count,device_ip,note) "
        "VALUES (?,?,?,?,?)",
        (now, record_count, new_count, device_ip, note),
    )
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid


def db_get_pull_sessions(limit=10):
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        "SELECT id,pulled_at,record_count,new_count,device_ip,note "
        "FROM pull_sessions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def db_list_leaves(year=None, month=None):
    conn = sqlite3.connect(DB_FILE)
    try:
        q = "SELECT uid, tanggal, jenis, note FROM leave_days WHERE 1=1"
        args = []
        if year:
            q += " AND strftime('%Y', tanggal)=?"
            args.append(str(year))
        if month:
            q += " AND strftime('%m', tanggal)=?"
            args.append(f"{month:02d}")
        q += " ORDER BY tanggal, uid"
        rows = conn.execute(q, args).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [
        {"uid": r[0], "tanggal": r[1], "jenis": r[2], "note": r[3]} for r in rows
    ]


def db_list_holidays(year=None, month=None):
    conn = sqlite3.connect(DB_FILE)
    try:
        q = "SELECT tanggal, note FROM holidays WHERE 1=1"
        args = []
        if year:
            q += " AND strftime('%Y', tanggal)=?"
            args.append(str(year))
        if month:
            q += " AND strftime('%m', tanggal)=?"
            args.append(f"{month:02d}")
        q += " ORDER BY tanggal"
        rows = conn.execute(q, args).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [{"tanggal": r[0], "note": r[1] or ""} for r in rows]


def agent_state_set(key: str, value: str) -> None:
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?,?)",
        (key, value),
    )
    conn.commit()
    conn.close()


def agent_state_get(key: str, default: str = "") -> str:
    conn = sqlite3.connect(DB_FILE)
    try:
        row = conn.execute(
            "SELECT value FROM agent_state WHERE key=?", (key,)
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()
    return row[0] if row else default


# ── Cloud sync ────────────────────────────────────────────────────────────────
def normalize_cloud_token(token: str) -> str:
    t = (token or "").strip().strip('"').strip("'")
    t = t.replace("\ufeff", "").replace("\u200b", "").replace("\u00a0", " ")
    t = "".join(t.split())
    if t.lower().startswith("bearer"):
        t = t[6:].lstrip(":").lstrip()
    return t


def normalize_cloud_base_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if u.lower().endswith("/sync"):
        u = u[:-5].rstrip("/")
    return u


def build_cloud_payload(cfg, punches=None, year=None, month=None) -> dict:
    um = cfg.get("user_map") or {}
    employees = [
        {"uid": int(k), "name": str(v)}
        for k, v in um.items()
        if str(k).isdigit() and v
    ]
    if punches is None:
        punches = db_query_attendance(year, month)
    punch_payload = []
    for r in punches:
        ts = r["timestamp"]
        if hasattr(ts, "strftime"):
            ts = ts.strftime("%Y-%m-%d %H:%M:%S")
        punch_payload.append(
            {
                "uid": int(r["uid"]),
                "timestamp": str(ts),
                "punch": int(r.get("punch") or 0),
                "nama": r.get("nama") or "",
                "recovered": bool(r.get("recovered")),
            }
        )
    leaves = db_list_leaves(year, month)
    leave_payload = [
        {
            "uid": int(l["uid"]),
            "tanggal": l["tanggal"],
            "jenis": l["jenis"],
            "note": l.get("note") or "",
        }
        for l in leaves
    ]
    holidays = db_list_holidays(year, month)
    holiday_payload = [
        {"tanggal": h["tanggal"], "note": h.get("note") or ""} for h in holidays
    ]
    return {
        "employees": employees,
        "punches": punch_payload,
        "leaves": leave_payload,
        "holidays": holiday_payload,
    }


def _cloud_headers(token: str) -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Attendance-Token": token,
        "User-Agent": f"ZKTeco-Agent/{APP_VERSION}",
    }


def _cloud_auth_hint(code, body="") -> str:
    b = (body or "").lower()
    if code == 401:
        return (
            "\n→ Token ditolak. Generate ulang di VST Absensi → salin token baru "
            "(tanpa prefix Bearer)."
        )
    if code == 404:
        return (
            "\n→ URL salah. Base: https://service.rejekiamerta.com/api/attendance"
        )
    if code == 422 or "validation" in b:
        return "\n→ Payload tidak valid."
    return ""


def cloud_credentials_ok(cfg) -> dict:
    base = normalize_cloud_base_url(cfg.get("cloud_api_url") or "")
    token = normalize_cloud_token(cfg.get("cloud_api_token") or "")
    if not base or not token:
        raise RuntimeError("Cloud API URL / token kosong.")
    url = base + "/employees"
    req = urllib.request.Request(url, method="GET", headers=_cloud_headers(token))
    log.info("☁ Tes credential → %s", url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
            n = len(data.get("employees") or [])
            msg = f"Credential OK — {n} karyawan di VST"
            log.info("✓ %s", msg)
            return {"ok": True, "status": resp.status, "message": msg, "employees": n}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:400]
        hint = _cloud_auth_hint(e.code, err_body)
        raise RuntimeError(f"HTTP {e.code}: {err_body or e.reason}{hint}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network: {e.reason}") from e


def cloud_sync(cfg, punches=None, year=None, month=None) -> dict:
    if not cfg.get("cloud_sync_enabled"):
        raise RuntimeError("Cloud sync disabled (cloud_sync_enabled=false).")
    base = normalize_cloud_base_url(cfg.get("cloud_api_url") or "")
    token = normalize_cloud_token(cfg.get("cloud_api_token") or "")
    cfg["cloud_api_url"] = base
    cfg["cloud_api_token"] = token
    if not base or not token:
        raise RuntimeError("Cloud API URL / token kosong.")
    url = base + "/sync"
    body = build_cloud_payload(cfg, punches=punches, year=year, month=month)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers=_cloud_headers(token)
    )
    log.info(
        "☁ Sync → %s  (%s punch, %s emp, %s leave, %s libur)",
        url,
        len(body["punches"]),
        len(body["employees"]),
        len(body["leaves"]),
        len(body.get("holidays", [])),
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            result = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:400]
        hint = _cloud_auth_hint(e.code, err_body)
        raise RuntimeError(f"HTTP {e.code}: {err_body or e.reason}{hint}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network: {e.reason}") from e

    log.info(
        "✓ Cloud sync OK — punches new=%s skip=%s emp=%s leave=%s",
        result.get("punches_new", "?"),
        result.get("punches_skipped", "?"),
        result.get("employees_upserted", "?"),
        result.get("leaves_upserted", "?"),
    )
    agent_state_set("last_cloud_sync", datetime.now().isoformat(timespec="seconds"))
    agent_state_set("last_cloud_result", json.dumps(result)[:500])
    return result


# ── Device ────────────────────────────────────────────────────────────────────
def connect_device(cfg):
    """Open pyzk connection. Caller must disconnect()."""
    try:
        from zk import ZK
    except ImportError as e:
        raise RuntimeError(
            "Package pyzk tidak terpasang. pip install pyzk"
        ) from e
    ip = str(cfg.get("ip") or "").strip()
    port = int(cfg.get("port") or 8088)
    pwd = int(cfg.get("comm_password") or 0)
    if not ip:
        raise RuntimeError("Device IP kosong di config.")
    zk = ZK(ip, port=port, timeout=10, password=pwd, force_udp=False, ommit_ping=False)
    log.info("Connecting %s:%s ...", ip, port)
    return zk.connect()


def check_clock(conn, set_if_skew=True) -> Optional[float]:
    try:
        dev = conn.get_time()
        pc = datetime.now()
        skew = abs((dev - pc).total_seconds())
        if skew > 120 and set_if_skew:
            mins = int(skew // 60)
            conn.set_time(datetime.now())
            log.warning(
                "Device clock off by ~%s min (was %s) — auto-synced to PC",
                mins,
                dev,
            )
        else:
            log.info("Device clock OK (%s, skew %.0fs)", dev, skew)
        return skew
    except Exception as e:
        log.warning("Clock check skipped: %s", e)
        return None


def test_device(cfg) -> dict:
    conn = connect_device(cfg)
    try:
        check_clock(conn, set_if_skew=True)
        info = {
            "ip": cfg.get("ip"),
            "port": cfg.get("port"),
            "firmware": getattr(conn, "firmware_version", None)
            or getattr(conn, "get_firmware_version", lambda: None)(),
            "serial": None,
            "users": None,
            "records": None,
        }
        try:
            info["serial"] = conn.get_serialnumber()
        except Exception:
            pass
        try:
            users = conn.get_users()
            info["users"] = len(users) if users is not None else None
        except Exception as e:
            info["users_error"] = str(e)
        try:
            conn.read_sizes()
            info["records"] = getattr(conn, "records", None)
            info["rec_cap"] = getattr(conn, "rec_cap", None)
        except Exception:
            try:
                atts = conn.get_attendance()
                info["records"] = len(atts) if atts else 0
            except Exception as e:
                info["records_error"] = str(e)
        try:
            info["device_time"] = str(conn.get_time())
        except Exception:
            pass
        return info
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


def _backup_anomaly_csv(remapped) -> Optional[str]:
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(_BASE, f"anomaly_recovered_{ts}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                ["UID", "Name", "OriginalTimestamp", "RemappedTimestamp", "Punch"]
            )
            for r in sorted(remapped, key=lambda x: x["timestamp"]):
                w.writerow(
                    [
                        r["uid"],
                        r["nama"],
                        r["orig_ts"].strftime("%Y-%m-%d %H:%M:%S"),
                        r["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                        r.get("punch", 0),
                    ]
                )
        log.info("Anomaly audit CSV → %s", path)
        return path
    except Exception as e:
        log.warning("Anomaly backup failed: %s", e)
        return None


def _sync_after_pull(cfg, mode: str, cache, new_rows) -> dict:
    """POST to VST after a pull.

    mode "all"     = every record on the device (old behaviour, CLI `pull`)
         "new"     = only punches that were new in SQLite; no request if none
         "history" = the whole local SQLite history (nightly safety net)
    A failed POST sets agent_state cloud_pending=1; the next "new" sync then
    sends everything once, so nothing is lost while VST is unreachable.
    """
    if mode == "new" and agent_state_get("cloud_pending") == "1":
        log.info("☁ Sync sebelumnya gagal — kirim ulang semua data mesin")
        mode = "all"
    if mode == "new":
        if not new_rows:
            return {"ok": True, "skipped": "no new punches"}
        punches = new_rows
    elif mode == "history":
        punches = None
    else:
        punches = cache
    try:
        result = cloud_sync(cfg, punches=punches)
    except Exception as e:
        log.error("Cloud sync failed after pull: %s", e)
        agent_state_set("cloud_pending", "1")
        return {"ok": False, "error": str(e)}
    if mode in ("all", "history"):
        agent_state_set("cloud_pending", "0")
    return result


def pull_attendance(cfg, do_cloud: Optional[bool] = None, sync: str = "all") -> dict:
    """
    Pull device → SQLite; optionally cloud_sync after pull.
    do_cloud: None = follow cloud_sync_after_pull + cloud_sync_enabled
    sync: what to POST — "all", "new" or "history" (see _sync_after_pull)
    """
    init_db()
    conn = connect_device(cfg)
    cache = []
    note = ""
    try:
        check_clock(conn, set_if_skew=True)
        atts = conn.get_attendance()
        if not atts:
            log.warning("No attendance data on device.")
            agent_state_set(
                "last_pull", datetime.now().isoformat(timespec="seconds")
            )
            agent_state_set("last_pull_note", "empty")
            return {
                "ok": True,
                "records": 0,
                "new": 0,
                "skipped": 0,
                "session_id": None,
                "cloud": None,
            }

        um = {int(k): v for k, v in (cfg.get("user_map") or {}).items()}
        recs = [
            {
                "uid": int(a.user_id),
                "nama": um.get(int(a.user_id), f"UID:{a.user_id}"),
                "timestamp": a.timestamp,
                "punch": a.punch,
            }
            for a in atts
            if a.timestamp
        ]
        anomaly = [r for r in recs if is_anomaly_ts(r["timestamp"])]
        normal = [r for r in recs if not is_anomaly_ts(r["timestamp"])]

        if anomaly and cfg.get("anomaly_recover", True):
            cfg_anchor = str(cfg.get("anomaly_anchor", "") or "").strip()
            anchor = None
            if cfg_anchor:
                try:
                    anchor = datetime.strptime(cfg_anchor, "%Y-%m-%d").date()
                except Exception:
                    anchor = None
            gaps = find_gaps(normal, min_len=2)
            if anchor is None:
                anchor = find_gap_start(normal)
            if anchor is None:
                gap_txt = ", ".join(
                    f"{s.isoformat()}({n}d)" for s, n in gaps[:5]
                ) or "none"
                log.warning(
                    "%s anomaly records need manual anomaly_anchor (gaps: %s)",
                    len(anomaly),
                    gap_txt,
                )
                note = f"anomaly_needs_anchor:{len(anomaly)}"
                cache = normal
            else:
                remapped = remap_anomalies(
                    anomaly,
                    anchor,
                    cfg.get("jam_masuk", "08:00"),
                    cfg.get("jam_keluar", "16:00"),
                )
                log.warning(
                    "%s ANOMALY recovered onto %s (%s punches)",
                    len(anomaly),
                    anchor,
                    len(remapped),
                )
                _backup_anomaly_csv(remapped)
                note = f"recovered:{len(anomaly)}"
                cache = normal + remapped
        else:
            if anomaly:
                log.warning(
                    "%s anomaly ignored (recovery disabled)", len(anomaly)
                )
                note = f"anomaly_ignored:{len(anomaly)}"
            cache = normal

        new_rows, skipped = db_insert_attendance_rows(cache)
        new = len(new_rows)
        sid = db_add_pull_session(
            len(cache), new, str(cfg.get("ip") or ""), note=note
        )
        log.info(
            "✓ %s pulled | %s new | %s dup | session #%s",
            len(atts),
            new,
            skipped,
            sid,
        )

        if cfg.get("auto_backup", False):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(_BASE, f"backup_raw_{ts}.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["UserID", "Name", "Timestamp", "Punch", "Recovered"])
                for r in cache:
                    w.writerow(
                        [
                            r["uid"],
                            r["nama"],
                            r["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                            if r["timestamp"]
                            else "",
                            r.get("punch", 0),
                            "Y" if r.get("recovered") else "",
                        ]
                    )
            log.info("Backup CSV → %s", path)

        cloud_result = None
        want_cloud = (
            do_cloud
            if do_cloud is not None
            else (
                bool(cfg.get("cloud_sync_enabled"))
                and bool(cfg.get("cloud_sync_after_pull", True))
            )
        )
        if want_cloud:
            cloud_result = _sync_after_pull(cfg, sync, cache, new_rows)

        agent_state_set("last_pull", datetime.now().isoformat(timespec="seconds"))
        agent_state_set(
            "last_pull_note",
            f"new={new} skip={skipped} note={note}",
        )
        return {
            "ok": True,
            "records": len(atts),
            "new": new,
            "skipped": skipped,
            "session_id": sid,
            "cloud": cloud_result,
            "note": note,
        }
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


def run_once(cfg, no_cloud: bool = False) -> dict:
    """One cycle: pull device → SQLite → optional cloud (same as desktop silent pull)."""
    pull = pull_attendance(cfg, do_cloud=False if no_cloud else None)
    return {"pull": pull, "sync": pull.get("cloud")}


# ── Live capture ──────────────────────────────────────────────────────────────
LIVE_TIMEOUT_S = 2  # live_capture socket timeout = how often the loop wakes up
LIVE_BATCH_S = 2  # wait this long after a new punch before POSTing (groups a queue)
LIVE_RETRY_S = 60  # pause after a dropped live connection
LIVE_MAX_FAILS = 3  # then fall back to auto_pull_interval_min until the next cycle


def _parse_hhmm(value, default: Tuple[int, int]) -> Tuple[int, int]:
    try:
        h, m = str(value).split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except (TypeError, ValueError):
        pass
    return default


def history_sync_due_at(cfg, now: datetime) -> datetime:
    """Today's nightly history-sync moment, or tomorrow's if today's already ran."""
    h, m = _parse_hhmm(cfg.get("history_sync_time"), (23, 50))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if agent_state_get("last_history_sync_date") == now.date().isoformat():
        at += timedelta(days=1)
    return at


def _sleep_until(deadline: datetime, stopped: Callable[[], bool]) -> None:
    while not stopped():
        left = (deadline - datetime.now()).total_seconds()
        if left <= 0:
            return
        time.sleep(min(5, left))


def _live_flush(cfg, rows) -> None:
    try:
        cloud_sync(cfg, punches=rows)
    except Exception as e:
        log.error("Live sync gagal (%s) — dikirim ulang di tarik penuh berikutnya", e)
        agent_state_set("cloud_pending", "1")


def live_session(
    cfg,
    until: datetime,
    no_cloud: bool = False,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> str:
    """Hold one live_capture connection until `until`; POST each new punch.

    Returns why it ended: "deadline", "stop", or "anomaly" (a punch dated
    year 2000 = device clock reset; it is NOT sent, the caller runs a full
    pull, which fixes the clock and applies the anomaly recovery).
    Device/network errors propagate to the caller.
    """
    um = {int(k): v for k, v in (cfg.get("user_map") or {}).items()}
    want_cloud = not no_cloud and bool(cfg.get("cloud_sync_enabled"))
    pending: List[dict] = []
    first_at = 0.0
    reason = "deadline"
    conn = connect_device(cfg)
    try:
        check_clock(conn, set_if_skew=True)
        log.info("● Live capture aktif sampai %s", until.strftime("%Y-%m-%d %H:%M"))
        agent_state_set("last_live_start", datetime.now().isoformat(timespec="seconds"))
        # Never `break` out of this loop: the generator only unregisters the
        # event (reg_event(0)) when it ends by itself after end_live_capture.
        for att in conn.live_capture(new_timeout=LIVE_TIMEOUT_S):
            if att is not None and att.timestamp and reason != "anomaly":
                uid = int(att.user_id)
                if is_anomaly_ts(att.timestamp):
                    log.warning(
                        "Live punch UID %s bertanggal %s — jam mesin reset; "
                        "ditahan, tarik penuh sekarang",
                        uid,
                        att.timestamp,
                    )
                    reason = "anomaly"
                    conn.end_live_capture = True
                    continue
                rec = {
                    "uid": uid,
                    "nama": um.get(uid, f"UID:{uid}"),
                    "timestamp": att.timestamp,
                    "punch": att.punch,
                }
                new_rows, _ = db_insert_attendance_rows([rec])
                if new_rows:
                    log.info("● Live punch UID %s %s %s", uid, rec["nama"], att.timestamp)
                    if not pending:
                        first_at = time.monotonic()
                    pending.extend(new_rows)
            if pending and time.monotonic() - first_at >= LIVE_BATCH_S:
                if want_cloud:
                    _live_flush(cfg, pending)
                pending = []
            if reason == "deadline":
                if stop_flag and stop_flag():
                    reason = "stop"
                    conn.end_live_capture = True
                elif datetime.now() >= until:
                    conn.end_live_capture = True
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass
        if pending and want_cloud:
            _live_flush(cfg, pending)
    return reason


def _live_until(
    cfg, deadline: datetime, no_cloud: bool, stopped: Callable[[], bool]
) -> bool:
    """Run live sessions until `deadline`. False = live capture is not working."""
    fails = 0
    while not stopped() and datetime.now() < deadline:
        try:
            if live_session(cfg, deadline, no_cloud, stopped) == "anomaly":
                return True
            fails = 0
        except Exception as e:
            fails += 1
            log.warning("Live capture putus (%s) — percobaan %s/%s", e, fails, LIVE_MAX_FAILS)
            if fails >= LIVE_MAX_FAILS:
                poll = max(1, int(cfg.get("auto_pull_interval_min") or 15))
                log.warning(
                    "Live capture tidak jalan — tarik penuh tiap %s mnt sampai pulih", poll
                )
                _sleep_until(min(deadline, datetime.now() + timedelta(minutes=poll)), stopped)
                return False
            _sleep_until(
                min(deadline, datetime.now() + timedelta(seconds=LIVE_RETRY_S)), stopped
            )
    return True


def live_daemon_loop(
    cfg,
    no_cloud: bool = False,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> None:
    """Live capture between full pulls. Survives errors."""
    full_min = max(5, int(cfg.get("full_pull_interval_min") or 60))
    poll_min = max(1, int(cfg.get("auto_pull_interval_min") or 15))
    stopped = lambda: bool(stop_flag and stop_flag())  # noqa: E731
    log.info(
        "Daemon start (live) — device %s:%s, tarik penuh tiap %s mnt "
        "(cadangan %s mnt), riwayat harian %s, cloud=%s",
        cfg.get("ip"),
        cfg.get("port"),
        full_min,
        poll_min,
        cfg.get("history_sync_time"),
        not no_cloud and bool(cfg.get("cloud_sync_enabled")),
    )
    live_ok = True
    backoff = 30
    while not stopped():
        now = datetime.now()
        mode = "history" if now >= history_sync_due_at(cfg, now) else "new"
        try:
            res = pull_attendance(cfg, do_cloud=False if no_cloud else None, sync=mode)
            cloud = res.get("cloud")
            if mode == "history" and (cloud is None or cloud.get("ok") is not False):
                agent_state_set("last_history_sync_date", now.date().isoformat())
            backoff = 30
        except Exception as e:
            log.exception("Tarik penuh gagal: %s", e)
            log.info("Backoff sleep %ss", backoff)
            _sleep_until(datetime.now() + timedelta(seconds=backoff), stopped)
            backoff = min(backoff * 2, 600)
            continue
        now = datetime.now()
        deadline = now + timedelta(minutes=full_min if live_ok else poll_min)
        hist_at = history_sync_due_at(cfg, now)
        if hist_at > now:
            deadline = min(deadline, hist_at)
        live_ok = _live_until(cfg, deadline, no_cloud, stopped)
    log.info("Daemon stop requested")


def daemon_loop(
    cfg,
    interval_min: Optional[int] = None,
    no_cloud: bool = False,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> None:
    """Forever loop for systemd. Survives errors."""
    if cfg.get("live_capture"):
        if interval_min is not None:
            cfg["auto_pull_interval_min"] = interval_min
        live_daemon_loop(cfg, no_cloud=no_cloud, stop_flag=stop_flag)
        return
    mins = interval_min
    if mins is None:
        mins = int(cfg.get("auto_pull_interval_min") or 15)
    if mins < 1:
        mins = 15
    log.info(
        "Daemon start — device %s:%s, interval %s min, cloud=%s",
        cfg.get("ip"),
        cfg.get("port"),
        mins,
        not no_cloud and bool(cfg.get("cloud_sync_enabled")),
    )
    backoff = 30
    while True:
        if stop_flag and stop_flag():
            log.info("Daemon stop requested")
            break
        try:
            run_once(cfg, no_cloud=no_cloud)
            backoff = 30
        except Exception as e:
            log.exception("Cycle failed: %s", e)
            sleep_s = min(backoff, mins * 60)
            log.info("Backoff sleep %ss", sleep_s)
            time.sleep(sleep_s)
            backoff = min(backoff * 2, 600)
            continue
        # sleep in chunks so stop is responsive
        remaining = mins * 60
        while remaining > 0:
            if stop_flag and stop_flag():
                log.info("Daemon stop requested during sleep")
                return
            chunk = min(5, remaining)
            time.sleep(chunk)
            remaining -= chunk
