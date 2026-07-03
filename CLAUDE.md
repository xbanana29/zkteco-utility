# CLAUDE.md — ZKTeco eFace10 Utility (CV RAJ)

> Catatan untuk sesi Claude Code berikutnya. **Baca ini dulu** sebelum menyelidiki
> ulang, biar hemat token. Terakhir diperbarui: 2026-07-03.

## Ringkasan proyek
Utility desktop (Python + tkinter) untuk menarik log absen dari mesin **ZKTeco
eFace10** via library `pyzk` (`from zk import ZK`), simpan ke SQLite, dan
generate laporan Excel (kartu absensi bulanan + rekap).

- **Mesin absen:** IP `10.10.11.55`, **port `8088`** (bukan 4370 default; port 4370 tertutup).
- **Firmware:** Ver 6.60 (2021). **Serial:** CN96212660182.
- **Karyawan:** UID 1-11 (lihat `user_map` di config / `DEFAULT_CONFIG`).
- **Jam kerja:** masuk 08:00, keluar 16:00, toleransi 15 mnt. **Kerja tiap hari termasuk Minggu.**
- EXE yang dipakai user: `C:\Users\Nicholas\Desktop\ZKTeco Utils\ZKTeco_Utility.exe`
  (PyInstaller). Source ada di sini: `C:\Users\Nicholas\Documents\zkteco-utility\`.
  **Edit source di sini TIDAK otomatis mengubah EXE** — perlu rebuild (`build_windows.bat`)
  atau jalankan langsung `python zkteco_app.py`.

## ⚠️ Masalah hardware yang MENAHUN (akar semua anomali)
**Mesin eFace10 ini TIDAK punya baterai RTC.** Hanya di-backup UPS. Kalau listrik
padam lebih lama dari UPS, **jam mesin reset ke tahun 2000**. Absen yang terjadi
selama outage tetap terekam tapi ber-timestamp **tahun 2000** (bukan tanggal asli),
jam-nya juga acak/drift. Ini AKAN terulang tiap mati listrik panjang.

Contoh kejadian: **11-23 Juni 2026 "hilang"** → ternyata 294 record tersimpan di
tahun 2000 (2000-02-01..02-09). Setelah "Set Time" ~24 Juni, data normal lagi.
Saran ke user: **pasang baterai RTC / jangan biarkan UPS habis**, dan **klik
"Set Time" tiap habis mati listrik**.

## Patch yang sudah diterapkan (2026-07-03) di `zkteco_app.py`
Tujuan: aplikasi mengenali record anomali (jam reset) dan memulihkannya otomatis.

1. **`DEFAULT_CONFIG`** + 2 key baru: `anomaly_recover` (bool, default True),
   `anomaly_anchor` (str "YYYY-MM-DD", kosong = auto).
2. **Helper baru** (setelah `DEFAULT_CONFIG`, sebelum i18n):
   - `ANOMALY_YEAR = 2000`, `is_anomaly_ts(ts)` — deteksi record tahun ≤ 2000.
   - `find_gap_start(normal_recs)` — cari **gap terpanjang** di kalender data
     normal = titik mulai outage (untuk THIS device menghasilkan 2026-06-11).
   - `remap_anomalies(anomaly, anchor, jam_masuk, jam_keluar)` — petakan tiap hari
     palsu → tanggal asli berurutan; jam dinormalisasi linear ke window
     [masuk−30mnt .. keluar+60mnt] biar "mirip" hari normal. Timestamp dijaga unik
     (constraint DB `timestamp UNIQUE`). Output tandai `recovered=True`, `orig_ts`.
3. **`App._do_pull`** — sekarang: cek jam → pisah normal vs anomaly → remap anomaly →
   simpan backup CSV (`anomaly_recovered_*.csv`) → gabung ke cache/DB → popup
   peringatan. Idempotent (remap deterministik, dedup by UNIQUE timestamp).
4. **`App._check_clock(conn)`** (baru) — bandingkan `conn.get_time()` vs PC;
   kalau meleset >120 dtk → log + popup "Set Time". Dipanggil di `_do_pull` & `_do_test`.
5. **`App._backup_anomaly_csv(remapped)`** (baru) — simpan jam asli vs remap untuk audit.
6. **`SettingsDialog`** — tambah field "Recovery anchor date" + checkbox
   "Auto-recover clock-reset (year 2000) records".

Filter lama `ts.year <= 2000: continue` di `generate_excel_bytes` dan
`strftime('%Y',timestamp)>'2000'` di `db_query_attendance` **sengaja dibiarkan**
sebagai jaring pengaman (record sudah di-remap jadi 2026 sebelum masuk DB).

## Skrip pemulihan sekali-jalan: `recover_and_export.py`
Tarik device → remap anomaly → tulis **Excel + audit CSV ke Desktop**. Tidak
menyentuh/menghapus data device. Jalankan: `python recover_and_export.py`.
Hasil terakhir: `Absensi_CVRAJ_RECOVERED_*.xlsx` (Jun 11-19 terisi; 20-23 memang
kosong karena device down), `Recovered_audit_*.csv`.

## Struktur file penting
- `zkteco_app.py` — aplikasi utama (UI + DB + Excel + device). ~1450 baris.
  - DB: SQLite `absensi.db` (di dir yang sama; ephemeral kalau EXE onefile).
  - Tabel: `attendance` (UNIQUE timestamp), `users`, `pull_sessions`, `excel_snapshots`.
  - `generate_excel_bytes(rows,cfg)` — generator laporan (dipakai ulang skrip recovery).
- `recover_and_export.py` — skrip recovery (dibuat 2026-07-03).
- `updater.py` — auto-update dari GitHub releases (`nikokevin29/zkteco-utility`).
- `i18n.py` — terjemahan EN/ID. `test_zkteco_app.py` — test.

## Catatan penting / jangan sampai salah
- **JANGAN tekan "Clear Device Log"** selama record tahun-2000 masih perlu dipulihkan —
  `clear_attendance()` menghapus permanen dari memori mesin.
- **JANGAN menulis apa pun ke device** saat menyelidiki (semua investigasi read-only).
- Data device (`get_attendance()`) adalah **sumber kebenaran**; DB lokal bisa ephemeral.
- Pemetaan tanggal anomali ke tanggal asli bersifat **pendekatan** (jam device korup).
  Yang REAL: siapa hadir & urutan; yang perkiraan: jam menit persis.
