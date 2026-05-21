# ZKTeco eFace10 Utility

Aplikasi desktop untuk manajemen mesin absensi wajah ZKTeco eFace10.
Dibuat dengan Python + Tkinter, tanpa ADMS, koneksi langsung via TCP.

![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/python-3.9%2B-green)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

---

## Fitur

- 🔌 **Koneksi langsung** ke mesin via TCP (tanpa ADMS)
- 🕐 **Set waktu mesin** — sync RTC ke waktu PC
- 📥 **Tarik data absensi** — simpan ke database SQLite lokal
- 📊 **Generate Excel report** — kartu absensi, rekap, keterlambatan, log detail
- 👤 **Kelola user** — lihat daftar karyawan langsung dari mesin
- ℹ️ **Info device** — firmware, serial, jumlah log
- 🗑 **Clear log mesin** — hapus memori setelah ditarik
- 💾 **Auto backup CSV** setiap kali tarik data
- ⬆️ **Auto update** — cek & download versi terbaru dari GitHub
- 🖥 **Cross-platform** — Windows, Linux, macOS

### Excel Report berisi:
| Sheet | Isi |
|-------|-----|
| Kartu Absensi (per bulan) | Jam masuk tiap hari, warna status, total hadir, terlambat, lembur |
| Rekap | Ringkasan bulanan per karyawan + % kehadiran |
| Keterlambatan | Detail siapa terlambat berapa menit |
| Log Detail | Semua baris lengkap + total tap per hari |

---

## Download

👉 **[Download EXE terbaru di Releases](https://github.com/nikokevin29/zkteco-utility/releases/latest)**

| Platform | File |
|----------|------|
| Windows  | `ZKTeco_Utility.exe` |
| Linux    | `ZKTeco_Utility_Linux` |
| macOS    | `ZKTeco_Utility_macOS` |

---

## Cara Pakai

### Windows
1. Download `ZKTeco_Utility.exe`
2. Buat folder baru (misal `C:\ZKTeco\`), taruh EXE di sana
3. Jalankan EXE
4. Isi IP mesin dan port, klik **Test Koneksi**
5. Ikuti alur: **① Set Waktu → ② Tarik Data → ③ Generate Excel**

### Linux / macOS
```bash
chmod +x ZKTeco_Utility_Linux
./ZKTeco_Utility_Linux
```

### Jalankan dari source (semua OS)
```bash
# Clone repo
git clone https://github.com/nikokevin29/zkteco-utility.git
cd zkteco-utility

# Install dependencies
pip install pyzk openpyxl

# Jalankan
python zkteco_app.py
```

---

## Build dari Source

### Windows
```
build_windows.bat
```

### Linux
```bash
chmod +x build_linux.sh
./build_linux.sh
```

---

## Konfigurasi

Saat pertama kali dijalankan, file `config.json` dibuat otomatis di folder yang sama dengan EXE.

```json
{
  "ip": "10.10.11.55",
  "port": "8088",
  "jam_masuk": "08:00",
  "jam_keluar": "16:00",
  "toleransi": 15,
  "auto_backup": true,
  "user_map": {
    "1": "NICHOLAS",
    "2": "SERLI"
  }
}
```

Semua setting bisa diubah via menu **⚙ Pengaturan** di dalam app.

---

## File yang dibuat app

| File | Keterangan |
|------|-----------|
| `config.json` | Pengaturan IP, jam kerja, nama karyawan |
| `absensi.db` | Database SQLite — histori semua data absensi |
| `backup_raw_*.csv` | Backup otomatis setiap tarik data |
| `Absensi_CVRAJ_*.xlsx` | Report Excel hasil generate |

---

## Kompatibilitas Mesin

Diuji pada:
- ✅ ZKTeco eFace10 (firmware Ver 6.60)

Kemungkinan kompatibel dengan mesin ZKTeco lain yang support protokol TCP port 4370/8088 via library `pyzk`.

---

## Rilis Baru (untuk maintainer)

```bash
# Update APP_VERSION di zkteco_app.py dan pyproject.toml
# lalu:
git add .
git commit -m "release: v4.2.0"
git tag v4.2.0
git push origin main --tags
```

GitHub Actions akan otomatis build EXE untuk Windows, Linux, macOS dan upload ke Releases.

---

## Lisensi

MIT License — bebas dipakai, dimodifikasi, dan didistribusikan.
Lihat [LICENSE](LICENSE) untuk detail.

---

## Kontribusi

Pull request welcome! Untuk perubahan besar, buka issue dulu.
