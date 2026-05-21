"""
ZKTeco Utility — Auto Updater
Cek versi terbaru di GitHub Releases, download & replace EXE jika ada update.
"""

import os
import sys
import json
import shutil
import tempfile
import threading
import urllib.request
import urllib.error
from pathlib import Path

GITHUB_OWNER = "nikokevin29"
GITHUB_REPO  = "zkteco-utility"
API_URL      = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
EXE_NAME     = "ZKTeco_Utility.exe"   # nama file di GitHub Release assets


def _version_tuple(v: str):
    """'1.2.3' -> (1, 2, 3)"""
    try:
        return tuple(int(x) for x in v.lstrip('v').split('.'))
    except Exception:
        return (0,)


def get_latest_release() -> dict | None:
    """
    Fetch info release terbaru dari GitHub API.
    Return dict {version, download_url, body} atau None kalau gagal.
    """
    try:
        req = urllib.request.Request(
            API_URL,
            headers={"User-Agent": "ZKTeco-Utility-Updater"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        tag     = data.get("tag_name", "")
        body    = data.get("body", "")
        assets  = data.get("assets", [])
        dl_url  = next(
            (a["browser_download_url"] for a in assets
             if a["name"].lower() == EXE_NAME.lower()),
            None
        )
        if not tag or not dl_url:
            return None
        return {"version": tag, "download_url": dl_url, "body": body}
    except Exception:
        return None


def is_newer(latest_ver: str, current_ver: str) -> bool:
    return _version_tuple(latest_ver) > _version_tuple(current_ver)


def download_and_replace(download_url: str, on_progress=None, on_done=None, on_error=None):
    """
    Download EXE ke tempfile, lalu:
    - Windows : schedule replace via .bat yang dijalankan setelah app exit
    - Linux/macOS : replace langsung (tidak ada lock)
    Callback on_progress(pct:int), on_done(), on_error(msg:str)
    """
    def _run():
        try:
            # Download ke temp dir
            tmp_dir  = tempfile.mkdtemp()
            tmp_path = os.path.join(tmp_dir, EXE_NAME)

            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "ZKTeco-Utility-Updater"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk = 65536
                with open(tmp_path, 'wb') as f:
                    while True:
                        buf = resp.read(chunk)
                        if not buf: break
                        f.write(buf)
                        downloaded += len(buf)
                        if total and on_progress:
                            on_progress(int(downloaded / total * 100))

            # Path EXE yang sedang berjalan
            if getattr(sys, 'frozen', False):
                # running as PyInstaller EXE
                current_exe = Path(sys.executable)
            else:
                # running as .py script — tidak perlu replace
                if on_done: on_done()
                return

            if sys.platform == 'win32':
                # Buat bat yang menunggu app exit, copy, lalu restart
                bat_path = os.path.join(tmp_dir, "do_update.bat")
                bat = f"""@echo off
ping 127.0.0.1 -n 3 >nul
copy /Y "{tmp_path}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
"""
                with open(bat_path, 'w') as f:
                    f.write(bat)
                import subprocess
                subprocess.Popen(
                    ['cmd', '/c', bat_path],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # Linux/macOS: langsung replace
                shutil.copy2(tmp_path, current_exe)
                os.chmod(current_exe, 0o755)

            if on_done: on_done()

        except Exception as e:
            if on_error: on_error(str(e))

    threading.Thread(target=_run, daemon=True).start()
