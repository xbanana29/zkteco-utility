# ZKTeco eFace10 Utility

<p align="center">
  <img src="app_icon.png" width="120" alt="ZKTeco x CV RAJ Logo"/>
</p>

<p align="center">
  <strong>Desktop utility for ZKTeco eFace10 face recognition attendance device.</strong><br/>
  Direct TCP connection — no ADMS required.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blue"/>
  <img src="https://img.shields.io/badge/python-3.9%2B-green"/>
  <img src="https://img.shields.io/badge/license-MIT-brightgreen"/>
  <img src="https://img.shields.io/github/v/release/nikokevin29/zkteco-utility"/>
</p>

---

## Features

| Feature | Description |
|---------|-------------|
| Direct TCP connection | Connects to device via TCP — no ADMS/cloud needed |
| Set device time | Sync RTC clock to PC time in one click |
| Pull attendance | Fetch all logs, auto-deduplicate, save to local SQLite |
| Excel report | Attendance card, recap, late report, log detail |
| User management | View registered users synced from device |
| Device info | Firmware, serial number, memory usage |
| Clear device log | Free up device memory after pulling data |
| Auto backup CSV | Raw backup on every pull |
| Auto update | Check and download latest version from GitHub |
| Multi-language | English / Bahasa Indonesia |
| Cross-platform | Windows, Linux, macOS |

### Smart Deduplication
All face scan taps on the same day collapse to **2 valid records**:
- **Earliest tap** = check-in
- **Latest tap** = check-out
- All taps in between are ignored

---

## Download

### [Latest Release](https://github.com/nikokevin29/zkteco-utility/releases/latest)

| Platform | File |
|----------|------|
| Windows  | `ZKTeco_Utility.exe` (~13 MB) |
| Linux    | `ZKTeco_Utility_Linux` |
| macOS    | `ZKTeco_Utility_macOS` |

---

## Quick Start

**Windows:** Download EXE, place in a dedicated folder (not Downloads), run.

**Linux / macOS:**
```bash
chmod +x ZKTeco_Utility_Linux
./ZKTeco_Utility_Linux
```

**From source:**
```bash
git clone https://github.com/nikokevin29/zkteco-utility.git
cd zkteco-utility
pip install pyzk openpyxl
python zkteco_app.py
```

---

## Configuration

`config.json` is auto-created on first run:

```json
{
  "ip": "10.10.11.55",
  "port": "8088",
  "lang": "en",
  "jam_masuk": "08:00",
  "jam_keluar": "16:00",
  "toleransi": 15,
  "auto_backup": true,
  "user_map": { "1": "NICHOLAS" }
}
```

Language can be switched (English / Bahasa Indonesia) from the header dropdown without restarting.

---

## Build from Source

```bash
# Windows
build_windows.bat

# Linux / macOS
chmod +x build_linux.sh && ./build_linux.sh
```

## Release a New Version

```bash
git commit -am "release: v4.2.0"
git tag v4.2.0
git push origin main --tags
# GitHub Actions auto-builds for all platforms
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `pyzk` | ZKTeco device protocol |
| `openpyxl` | Excel file generation |
| `tkinter` | GUI (bundled with Python) |
| `sqlite3` | Local database (bundled with Python) |

No pandas, no numpy — binary stays small (~13 MB on Windows).

---

## License

MIT — free to use, modify, and distribute. See [LICENSE](LICENSE).

---

*Built for CV Rejeki Amerta Jaya, Wangon, Banyumas.*
