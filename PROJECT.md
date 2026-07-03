# ZKTeco Utility — Project Summary

Desktop app (Python/tkinter, single window) untuk mesin absen **ZKTeco eFace10** di CV RAJ.
Tarik log absensi via LAN → simpan SQLite → generate laporan Excel berformat → preview in-app.

**Konteks hardware penting:** eFace10 TIDAK punya baterai RTC. Mati listrik = jam mesin reset ke tahun 2000, absensi selama outage tercatat tanggal palsu. Sebagian besar kompleksitas app ini ada untuk menangani itu (anomaly recovery + auto clock sync).

## Files

| File | Isi |
|------|-----|
| `zkteco_app.py` | SEMUA logika app (~1500 baris, satu file, sengaja): config, SQLite, anomaly recovery, Excel generator, seluruh UI |
| `updater.py` | Auto-update dari GitHub Releases (`nikokevin29/zkteco-utility`). Download → rename old `_old.exe` → replace → restart |
| `recover_and_export.py` | Script standalone one-off: recovery anomali + export ke Desktop tanpa buka app. Duplikasi logika in-app (import dari zkteco_app), kandidat hapus kalau tak dipakai lagi |
| `test_zkteco_app.py` | 55 test unittest/pytest: anomaly detection/remap, gap-finder, DB CRUD, config, excel bytes, updater version compare. Run: `py -m pytest test_zkteco_app.py -q` |
| `build_windows.bat` / `build_linux.sh` | PyInstaller onefile. Output `dist\ZKTeco_Utility.exe` |
| `config.json` (runtime) | IP/port device, jam masuk/keluar, toleransi, user_map UID→nama, lang (en/id, hanya untuk label Excel) |
| `absensi.db` (runtime) | SQLite: `attendance` (timestamp UNIQUE), `users`, `pull_sessions`, `excel_snapshots` (xlsx blob di DB) |

## Struktur zkteco_app.py

- **Anomaly recovery** (top of file): `is_anomaly_ts`, `find_gap_start` (cari gap kalender terpanjang = outage), `remap_anomalies` (map hari-2000 → tanggal riil, jam di-rescale ke jendela kerja)
- **DB helpers**: fungsi `db_*` polos, satu koneksi per call
- **`generate_excel_bytes(rows, cfg)`**: laporan 3 jenis sheet (Kartu Absensi per bulan, Rekap, Log Detail) → bytes. Ada mini-dataframe class `_DF` internal (pengganti pandas, sengaja biar exe kecil) — kontainer, jangan diganti tanpa alasan
- **Dialogs**: `SettingsDialog`, `DeviceInfoDialog`, `UserManagerDialog` (add/rename/delete user di mesin)
- **`App(tk.Tk)`**: split panel. Kiri = koneksi + workflow 3 langkah (Pull → Filter → Preview) + log. Kanan = notebook (Report Viewer treeview, Pull History + saved reports)
- Semua aksi device jalan di thread via `self._run(fn)`; update UI selalu via `self.after(0, ...)`
- Device I/O via **pyzk** (`from zk import ZK`), port default 8088

## Perilaku kunci

- **RTC auto-sync**: `_check_clock` dipanggil saat Test Connection & Pull — skew >2 menit → `conn.set_time()` otomatis. Tidak ada tombol Set Time manual lagi (dihapus, by design)
- **Pull**: deteksi record tahun-2000 → auto-remap (anchor dari config atau auto gap-finder) → warning popup + backup CSV audit → insert DB (dedup via timestamp UNIQUE)
- Report disimpan sebagai snapshot xlsx blob di DB, bisa di-load/export ulang dari tab History
- `⚡ All at Once` = pull + report sekaligus

## Build

```
cd D:\Developer\zkteco-utility
py -m pytest test_zkteco_app.py -q   # test dulu
build_windows.bat                     # atau pyinstaller command di dalamnya
```
Catatan: exe di `dist\` kekunci kalau app lagi jalan — kill `ZKTeco_Utility` dulu sebelum rebuild.

## Riwayat kurasi (Jul 2026)

- Ditambah: user add/rename/delete di device, tombol Restart device, RTC auto-sync
- Dihapus: `i18n.py` (dead code, `T()` tak pernah dipanggil), blok cleanup duplikat di `__init__`, step Set Time, popup restart bahasa yang menyesatkan
- Sengaja dibiarkan: `_DF` class (kecil, teruji, hindari pandas), `recover_and_export.py` (tool darurat offline)
