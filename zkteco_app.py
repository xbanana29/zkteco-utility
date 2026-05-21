#!/usr/bin/env python3
"""
ZKTeco eFace10 Utility v4 — CV RAJ
Fitur: Device Info, User Management, Attendance + Report, SQLite History,
       Jam Standar, Keterlambatan, Lembur, Clear Log, Backup Otomatis
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import csv, os, threading, calendar, sqlite3, json
from datetime import datetime, date, timedelta

# ── Auto-updater ──────────────────────────────────────────────────────────────
try:
    from updater import get_latest_release, is_newer, download_and_replace
    _UPDATER_OK = True
except ImportError:
    _UPDATER_OK = False

# ── i18n
try:
    from i18n import T, LANG
except ImportError:
    def T(key, lang='en', **kw): return key

# ── Cross-platform file/folder opener ────────────────────────────────────────
import sys as _sys, subprocess as _sp

def _open_path(path):
    """Buka file atau folder di file manager / default app, cross-platform."""
    try:
        if _sys.platform == 'win32':
            os.startfile(path)
        elif _sys.platform == 'darwin':
            _sp.Popen(['open', path])
        else:
            _sp.Popen(['xdg-open', path])
    except Exception as e:
        print(f"Cannot open {path}: {e}")

# Top-level import agar PyInstaller bundle openpyxl dengan benar
try:
    from openpyxl import Workbook as _WB
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    _OPENPYXL_OK = True
except ImportError:
    _OPENPYXL_OK = False

APP_VERSION = "4.1.0"
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
DB_FILE     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "absensi.db")

BULAN_ID = ["Januari","Februari","Maret","April","Mei","Juni",
            "Juli","Agustus","September","Oktober","November","Desember"]
HARI_ID  = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]

DEFAULT_CONFIG = {
    "ip": "10.10.11.55", "port": "8088",
    "jam_masuk": "08:00", "jam_keluar": "16:00",
    "toleransi": 15, "output_dir": "", "auto_backup": True,
    "user_map": {
        "1":"NICHOLAS","2":"SERLI","3":"TIA","4":"MISRO",
        "5":"LISA","6":"TUR","7":"SLAMET","8":"ARI",
        "9":"REFA","10":"SUKUR","11":"PUGUH"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding='utf-8') as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg: cfg[k] = v
            return cfg
        except: pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER, nama TEXT,
        timestamp TEXT UNIQUE,
        punch INTEGER, pulled_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        uid INTEGER PRIMARY KEY, nama TEXT,
        card_id TEXT, updated_at TEXT
    )''')
    conn.commit(); conn.close()

def db_insert_attendance(rows):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ins = 0
    for r in rows:
        ts = r['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if hasattr(r['timestamp'],'strftime') else str(r['timestamp'])
        try:
            c.execute('INSERT INTO attendance (uid,nama,timestamp,punch,pulled_at) VALUES (?,?,?,?,?)',
                      (r['uid'], r['nama'], ts, r['punch'], now))
            ins += 1
        except sqlite3.IntegrityError: pass
    conn.commit(); conn.close()
    return ins

def db_query_attendance(year=None, month=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    q = "SELECT uid,nama,timestamp,punch FROM attendance WHERE strftime('%Y',timestamp)>'2000'"
    args = []
    if year:  q += " AND strftime('%Y',timestamp)=?";  args.append(str(year))
    if month: q += " AND strftime('%m',timestamp)=?";  args.append(f"{month:02d}")
    q += " ORDER BY timestamp"
    c.execute(q, args)
    rows = [{'uid':r[0],'nama':r[1],
             'timestamp':datetime.strptime(r[2],'%Y-%m-%d %H:%M:%S'),'punch':r[3]}
            for r in c.fetchall()]
    conn.close(); return rows

def db_count():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM attendance WHERE strftime('%Y',timestamp)>'2000'")
    n = c.fetchone()[0]; conn.close(); return n

def db_upsert_users(users):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for u in users:
        c.execute('INSERT OR REPLACE INTO users (uid,nama,card_id,updated_at) VALUES (?,?,?,?)',
                  (u['uid'], u['nama'], u.get('card_id',''), now))
    conn.commit(); conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# EXCEL GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
def generate_excel(rows, out_path, cfg):
    if not _OPENPYXL_OK:
        raise RuntimeError("openpyxl tidak ditemukan. Jalankan: pip install openpyxl")
    from openpyxl import Workbook
    jam_masuk_std  = cfg.get('jam_masuk','08:00')
    jam_keluar_std = cfg.get('jam_keluar','16:00')
    toleransi      = int(cfg.get('toleransi', 15))
    user_map       = {int(k):v for k,v in cfg.get('user_map',{}).items()}

    def F(h): return PatternFill('solid', fgColor=h)
    def Bs(st='thin', co='FFB0B0B0'):
        s=Side(style=st,color=co); return Border(left=s,right=s,top=s,bottom=s)
    def Bm(co='FF888888'):
        s=Side(style='medium',color=co); return Border(left=s,right=s,top=s,bottom=s)
    def fnt(sz=9, bold=False, color='FF000000', italic=False):
        return Font(name='Arial', size=sz, bold=bold, color=color, italic=italic)
    C  = Alignment(horizontal='center', vertical='center', wrap_text=False)
    CW = Alignment(horizontal='center', vertical='center', wrap_text=True)
    L  = Alignment(horizontal='left',   vertical='center')
    R  = Alignment(horizontal='right',  vertical='center')

    CH='FF1A56DB'; CS='FF3B82F6'; CA='FF1E40AF'
    GBG='FFD1FAE5'; GTX='FF065F46'
    RBG='FFFEE2E2'; RTX='FF991B1B'
    YBG='FFFEF9C3'; YTX='FF854D0E'
    OBG='FFFED7AA'; OTX='FF9A3412'
    R1='FFFFFFFF'; R2='FFF0F4FF'; STR='FFE8F0FE'; BD='FFCBD5E1'; HT='FFFFFFFF'

    # ── build data (pure python, no pandas) ─────────────────────────────────
    def _parse_ts(t):
        if isinstance(t, datetime): return t
        if isinstance(t, str):
            for fmt in ('%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M'):
                try: return datetime.strptime(t, fmt)
                except: pass
        return None

    # ── Kumpulkan semua tap per (nama, tanggal) dulu ────────────────────────
    _raw = {}   # key=(nama,tgl) -> list of datetime
    for r in rows:
        ts = _parse_ts(r['timestamp'])
        if ts is None or ts.year <= 2000: continue
        nama = user_map.get(r['uid'], r.get('nama', f"UID:{r['uid']}"))
        tgl  = ts.date()
        key  = (nama, tgl)
        _raw.setdefault(key, []).append(ts)

    if not _raw: raise RuntimeError("Tidak ada data untuk periode ini.")

    # ── Ambil TAP PALING AWAL = masuk, TAP PALING AKHIR = keluar ────────────
    # Semua tap di antaranya diabaikan (redundansi wajah).
    # Kalau hanya 1 tap pada hari itu → hanya masuk, keluar = '-'
    class _Row:
        __slots__ = ['nama','tanggal','masuk','keluar','tap','tap_total',
                     'jam_masuk','jam_keluar','terlambat','lembur']
    daily_list = []
    for (nama, tgl), taps in sorted(_raw.items()):
        taps_sorted = sorted(taps)           # urutkan semua tap hari itu
        tap_total   = len(taps_sorted)
        ts_masuk    = taps_sorted[0]         # paling awal  = masuk
        ts_keluar   = taps_sorted[-1]        # paling akhir = keluar

        row = _Row()
        row.nama       = nama
        row.tanggal    = tgl
        row.masuk      = ts_masuk
        row.keluar     = ts_keluar
        row.tap        = 2 if tap_total > 1 else 1   # valid: maks 2
        row.tap_total  = tap_total                    # total mentah dari mesin
        row.jam_masuk  = ts_masuk.strftime('%H:%M')
        row.jam_keluar = ts_keluar.strftime('%H:%M') if tap_total > 1 else '-'
        row.terlambat  = 0
        row.lembur     = 0
        daily_list.append(row)

    # dummy DataFrame-like wrapper so rest of code still works
    class _DF:
        def __init__(self, lst): self._lst = lst
        def __iter__(self): return iter(self._lst)
        def __len__(self): return len(self._lst)
        @property
        def empty(self): return len(self._lst)==0
        def iterrows(self): return enumerate(self._lst)
        def min_date(self): return min(r.tanggal for r in self._lst)
        def max_date(self): return max(r.tanggal for r in self._lst)
        def names(self): return sorted(set(r.nama for r in self._lst))
        def months(self): return sorted(set(r.tanggal.strftime('%Y-%m') for r in self._lst))
        def filter_month(self,m): return _DF([r for r in self._lst if r.tanggal.strftime('%Y-%m')==m])
        def filter_name(self,n): return _DF([r for r in self._lst if r.nama==n])
        def filter_date(self,d): return _DF([r for r in self._lst if r.tanggal==d])
        def filter_late(self): return _DF([r for r in self._lst if r.terlambat>0])
        def sort_by(self,*keys): 
            import operator
            return _DF(sorted(self._lst, key=lambda r: tuple(getattr(r,k) for k in keys)))

    daily = _DF(daily_list)

    std_in  = datetime.strptime(jam_masuk_std,'%H:%M')
    tol_dt  = std_in + timedelta(minutes=toleransi)
    std_out = datetime.strptime(jam_keluar_std,'%H:%M')

    for row in daily:
        try:
            t = datetime.strptime(row.jam_masuk,'%H:%M')
            row.terlambat = int((t-std_in).total_seconds()//60) if t > tol_dt else 0
        except: row.terlambat = 0
        try:
            if row.jam_keluar == '-': row.lembur = 0
            else:
                t = datetime.strptime(row.jam_keluar,'%H:%M')
                row.lembur = int((t-std_out).total_seconds()//60) if t > std_out else 0
        except: row.lembur = 0

    months    = daily.months()
    all_names = daily.names()
    wb = Workbook()
    wb.remove(wb.active)

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET: KARTU ABSENSI per BULAN
    # ══════════════════════════════════════════════════════════════════════════
    for month in months:
        yr2, mo2   = int(month[:4]), int(month[5:])
        _, days_in = calendar.monthrange(yr2, mo2)
        bln_label  = f"{BULAN_ID[mo2-1]} {yr2}"
        mdata      = daily.filter_month(month)

        ws = wb.create_sheet(f'{BULAN_ID[mo2-1][:3]}{yr2}')
        ws.sheet_view.showGridLines = False
        ws.page_setup.orientation='landscape'
        ws.page_setup.fitToPage=True
        ws.page_setup.fitToWidth=1

        TOT_COL = days_in+3; LAT_COL = days_in+4
        OT_COL  = days_in+5; AVG_COL = days_in+6
        LC      = get_column_letter(days_in+6)

        ws.merge_cells(f'A1:{LC}1')
        ws['A1'] = 'CV REJEKI AMERTA JAYA — KARTU ABSENSI KARYAWAN'
        ws['A1'].font=fnt(13,True,HT); ws['A1'].fill=F(CH); ws['A1'].alignment=C
        ws.row_dimensions[1].height=22

        ws.merge_cells(f'A2:{LC}2')
        ws['A2'] = f'{bln_label.upper()}  |  Masuk Std: {jam_masuk_std}  |  Keluar Std: {jam_keluar_std}  |  Toleransi: {toleransi} mnt'
        ws['A2'].font=fnt(9,False,HT,italic=True); ws['A2'].fill=F(CS); ws['A2'].alignment=C
        ws.row_dimensions[2].height=15

        ws.merge_cells(f'A3:{LC}3')
        ws['A3'] = f'Dicetak: {datetime.now().strftime("%d %B %Y %H:%M")}'
        ws['A3'].font=fnt(8,False,'FF555555',italic=True)
        ws['A3'].fill=F('FFF8FAFF'); ws['A3'].alignment=R
        ws.row_dimensions[3].height=13

        ws.column_dimensions['A'].width=4
        ws.column_dimensions['B'].width=15
        for d in range(1,days_in+1):
            ws.column_dimensions[get_column_letter(d+2)].width=5
        ws.column_dimensions[get_column_letter(TOT_COL)].width=5.5
        ws.column_dimensions[get_column_letter(LAT_COL)].width=9
        ws.column_dimensions[get_column_letter(OT_COL)].width=8
        ws.column_dimensions[get_column_letter(AVG_COL)].width=7

        HDR=4; ws.row_dimensions[HDR].height=28

        def hc(col, val, bg=CA):
            c = ws.cell(row=HDR, column=col, value=val)
            c.font=fnt(8,True,HT); c.fill=F(bg); c.alignment=CW
            c.border=Bs('thin','FF93C5FD')

        hc(1,'No'); hc(2,'Nama')
        for d in range(1, days_in+1):
            dt = datetime(yr2,mo2,d)
            dn = ['Sn','Sl','Rb','Km','Jm','Sb','Mg'][dt.weekday()]
            c  = ws.cell(row=HDR, column=d+2, value=f'{d}\n{dn}')
            c.font=fnt(7,True,HT); c.alignment=CW; c.border=Bs('thin','FF93C5FD')
            if   dt.weekday()==6: c.fill=F('FF991B1B')
            elif dt.weekday()==5: c.fill=F('FF92400E')
            else:                 c.fill=F(CA)
        hc(TOT_COL,'∑\nHadir','FF065F46')
        hc(LAT_COL,'Terlambat\n(mnt)','FF7C2D12')
        hc(OT_COL,'Lembur\n(mnt)','FF1E40AF')
        hc(AVG_COL,'Rata\nMasuk','FF1E3A5F')

        for idx, name in enumerate(all_names, 1):
            r = HDR+idx; ws.row_dimensions[r].height=17
            sub = mdata.filter_name(name)
            c=ws.cell(row=r,column=1,value=idx)
            c.font=fnt(8); c.fill=F(STR); c.alignment=C; c.border=Bs('thin',BD)
            c=ws.cell(row=r,column=2,value=name)
            c.font=fnt(9,True,'FF1E3A5F'); c.fill=F(STR); c.alignment=L; c.border=Bm('FF93C5FD')

            hadir=0; masuk_list=[]; total_late=0; total_ot=0
            for d in range(1, days_in+1):
                col=d+2; dt=datetime(yr2,mo2,d)
                dr=sub.filter_date(date(yr2,mo2,d))
                if len(dr)>0:
                    jam  = dr._lst[0].jam_masuk
                    late = int(dr._lst[0].terlambat)
                    ot   = int(dr._lst[0].lembur)
                    c=ws.cell(row=r,column=col,value=jam)
                    masuk_list.append(jam); hadir+=1; total_late+=late; total_ot+=ot
                    if   late>0:            c.font=fnt(7,True,OTX);        c.fill=F(OBG)
                    elif dt.weekday()==6:   c.font=fnt(7,True,'FF7C3AED'); c.fill=F('FFEDE9FE')
                    elif dt.weekday()==5:   c.font=fnt(7,True,'FF92400E'); c.fill=F(YBG)
                    else:                   c.font=fnt(7,False,GTX);        c.fill=F(GBG)
                else:
                    c=ws.cell(row=r,column=col,value='')
                    if   dt.weekday()==6: c.fill=F('FFFCE7F3')
                    elif dt.weekday()==5: c.fill=F(YBG)
                    else:                 c.fill=F(RBG)
                    c.font=fnt(7)
                c.alignment=C; c.border=Bs('thin',BD)

            pct = round(hadir/days_in*100)
            c=ws.cell(row=r,column=TOT_COL,value=hadir)
            c.font=fnt(9,True,GTX if pct>=80 else RTX)
            c.fill=F(GBG if pct>=80 else RBG); c.alignment=C; c.border=Bm()

            c=ws.cell(row=r,column=LAT_COL,value=total_late if total_late else '-')
            c.font=fnt(9,total_late>0,OTX if total_late>0 else 'FF888888')
            c.fill=F(OBG if total_late>0 else R1); c.alignment=C; c.border=Bs('thin',BD)

            c=ws.cell(row=r,column=OT_COL,value=total_ot if total_ot else '-')
            c.font=fnt(9,total_ot>0,'FF1D4ED8' if total_ot>0 else 'FF888888')
            c.fill=F('FFE0EAFF' if total_ot>0 else R1); c.alignment=C; c.border=Bs('thin',BD)

            try:
                if masuk_list:
                    total_secs = sum(datetime.strptime(t,'%H:%M').hour*3600+datetime.strptime(t,'%H:%M').minute*60 for t in masuk_list)
                    avg_secs   = total_secs // len(masuk_list)
                    avg        = f"{avg_secs//3600:02d}:{(avg_secs%3600)//60:02d}"
                else: avg='-'
            except: avg='-'
            c=ws.cell(row=r,column=AVG_COL,value=avg)
            c.font=fnt(8,False,'FF1E3A5F'); c.fill=F('FFE0EAFF'); c.alignment=C; c.border=Bs('thin',BD)

        # baris total harian
        rt = HDR+len(all_names)+1; ws.row_dimensions[rt].height=15
        ws.merge_cells(f'A{rt}:B{rt}')
        c=ws.cell(row=rt,column=1,value='TOTAL HADIR HARIAN')
        c.font=fnt(8,True,HT); c.fill=F(CA); c.alignment=C; c.border=Bs('thin',BD)
        for d in range(1,days_in+1):
            col=d+2
            cnt=len(set(r.nama for r in mdata.filter_date(date(yr2,mo2,d))))
            c=ws.cell(row=rt,column=col,value=cnt if cnt else '')
            c.font=fnt(8,True,GTX if cnt else 'FFAAAAAA')
            c.fill=F(GBG if cnt else 'FFF1F5F9'); c.alignment=C; c.border=Bs('thin',BD)
        for col in (TOT_COL,LAT_COL,OT_COL,AVG_COL):
            c=ws.cell(row=rt,column=col,value=''); c.fill=F(CA); c.border=Bs('thin',BD)

        # legenda
        rl=rt+2; ws.row_dimensions[rl].height=13
        items=[
            (GBG,GTX,'■ Hadir - tepat waktu'),
            (OBG,OTX,'■ Hadir - terlambat'),
            (YBG,'FF92400E','■ Hadir - Sabtu'),
            ('FFEDE9FE','FF7C3AED','■ Hadir - Minggu'),
            (RBG,RTX,'■ Tidak hadir'),
        ]
        cl=1
        for bg,tc,lb in items:
            ws.merge_cells(start_row=rl,start_column=cl,end_row=rl,end_column=cl+2)
            c=ws.cell(row=rl,column=cl,value=lb)
            c.font=fnt(8,False,tc); c.fill=F(bg); c.alignment=L
            cl+=3

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET: REKAP
    # ══════════════════════════════════════════════════════════════════════════
    wr=wb.create_sheet('Rekap'); wr.sheet_view.showGridLines=False
    for i,w in enumerate([5,15,15,8,8,10,8,12,10,10],1):
        wr.column_dimensions[get_column_letter(i)].width=w
    wr.merge_cells('A1:J1')
    wr['A1']='REKAP ABSENSI — CV REJEKI AMERTA JAYA'
    wr['A1'].font=fnt(13,True,HT); wr['A1'].fill=F(CH); wr['A1'].alignment=C
    wr.row_dimensions[1].height=24
    wr.merge_cells('A2:J2')
    _tgl_min = daily.min_date().strftime("%d %B %Y")
    _tgl_max = daily.max_date().strftime("%d %B %Y")
    wr['A2']=f'Periode: {_tgl_min} s/d {_tgl_max}  |  Jam Masuk Std: {jam_masuk_std}  |  Toleransi: {toleransi} mnt'
    wr['A2'].font=fnt(9,False,'FF444444',italic=True); wr['A2'].alignment=C
    wr['A2'].fill=F('FFF0F4FF'); wr.row_dimensions[2].height=15
    for i,h in enumerate(['No','Nama','Bulan','Hari','Hadir','Tdk Hadir','% Hadir','Terlambat (mnt)','Lembur (mnt)','Status'],1):
        c=wr.cell(row=3,column=i,value=h)
        c.font=fnt(9,True,HT); c.fill=F(CA); c.alignment=CW; c.border=Bs('thin','FF93C5FD')
    wr.row_dimensions[3].height=22
    r=4; no=1
    for name in all_names:
        sub=daily.filter_name(name)
        for month in months:
            yr2,mo2=int(month[:4]),int(month[5:])
            _,days_in=calendar.monthrange(yr2,mo2)
            md=sub.filter_month(month)
            if len(md)==0: continue
            hadir=len(md); tidak=days_in-hadir; pct=round(hadir/days_in*100)
            tl=sum(r.terlambat for r in md); to=sum(r.lembur for r in md)
            status='✓ Baik' if pct>=90 else ('△ Cukup' if pct>=75 else '✗ Kurang')
            bg=F(R1) if r%2==1 else F(R2)
            vals=[no,name,f"{BULAN_ID[mo2-1]} {yr2}",days_in,hadir,tidak,
                  f"{pct}%",tl if tl else '-',to if to else '-',status]
            for i,v in enumerate(vals,1):
                c=wr.cell(row=r,column=i,value=v)
                c.font=fnt(9,i==2); c.fill=bg; c.alignment=C if i!=2 else L; c.border=Bs('thin',BD)
            pc=wr.cell(row=r,column=7); sc=wr.cell(row=r,column=10)
            if pct>=90:
                for x in (pc,sc): x.font=fnt(9,True,GTX); x.fill=F(GBG)
            elif pct>=75:
                for x in (pc,sc): x.font=fnt(9,True,YTX); x.fill=F(YBG)
            else:
                for x in (pc,sc): x.font=fnt(9,True,RTX); x.fill=F(RBG)
            lc=wr.cell(row=r,column=8)
            if tl>0: lc.font=fnt(9,True,OTX); lc.fill=F(OBG)
            wr.row_dimensions[r].height=17; r+=1; no+=1

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET: KETERLAMBATAN DETAIL
    # ══════════════════════════════════════════════════════════════════════════
    wl=wb.create_sheet('Keterlambatan'); wl.sheet_view.showGridLines=False
    for i,w in enumerate([5,14,12,10,10,10,13],1):
        wl.column_dimensions[get_column_letter(i)].width=w
    wl.merge_cells('A1:G1')
    wl['A1']='REKAP KETERLAMBATAN — CV REJEKI AMERTA JAYA'
    wl['A1'].font=fnt(12,True,HT); wl['A1'].fill=F('FF7C2D12'); wl['A1'].alignment=C
    wl.row_dimensions[1].height=22
    wl.merge_cells('A2:G2')
    wl['A2']=f'Jam masuk standar: {jam_masuk_std}  |  Toleransi: {toleransi} menit'
    wl['A2'].font=fnt(9,False,'FF7C2D12',italic=True); wl['A2'].alignment=C
    wl['A2'].fill=F('FFFFF7ED'); wl.row_dimensions[2].height=15
    for i,h in enumerate(['No','Nama','Tanggal','Hari','Jam Masuk','Std Masuk','Terlambat (mnt)'],1):
        c=wl.cell(row=3,column=i,value=h)
        c.font=fnt(9,True,HT); c.fill=F('FF92400E'); c.alignment=C; c.border=Bs('thin','FFFDBA74')
    wl.row_dimensions[3].height=20
    late_rows=daily.filter_late().sort_by('tanggal','nama')
    for i,row in enumerate(late_rows):
        r4=i+4; bg=F(R1) if i%2==0 else F('FFFEF3C7')
        tgl=row.tanggal
        vals=[i+1,row.nama,tgl.strftime('%d/%m/%Y'),HARI_ID[tgl.weekday()],
              row.jam_masuk,jam_masuk_std,int(row.terlambat)]
        for col,v in enumerate(vals,1):
            c=wl.cell(row=r4,column=col,value=v)
            c.font=fnt(9,col==7,OTX if col==7 else '000000')
            c.fill=F(OBG) if col==7 else bg
            c.alignment=C if col!=2 else L; c.border=Bs('thin',BD)
        wl.row_dimensions[r4].height=15

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET: LOG DETAIL
    # ══════════════════════════════════════════════════════════════════════════
    wd=wb.create_sheet('Log Detail'); wd.sheet_view.showGridLines=False
    for i,w in enumerate([5,14,12,10,10,10,8,10,10],1):
        wd.column_dimensions[get_column_letter(i)].width=w
    wd.merge_cells('A1:H1')
    wd['A1']='LOG DETAIL ABSENSI — CV REJEKI AMERTA JAYA'
    wd['A1'].font=fnt(12,True,HT); wd['A1'].fill=F(CH); wd['A1'].alignment=C
    wd.row_dimensions[1].height=22
    for i,h in enumerate(['No','Nama','Tanggal','Hari','Jam Masuk','Jam Keluar','Total Tap','Terlambat','Lembur'],1):
        c=wd.cell(row=2,column=i,value=h)
        c.font=fnt(9,True,HT); c.fill=F(CA); c.alignment=C; c.border=Bs('thin','FF93C5FD')
    wd.row_dimensions[2].height=18
    ds=daily.sort_by('tanggal','nama')
    for i,row in enumerate(ds):
        r3=i+3; tgl=row.tanggal
        dn=HARI_ID[tgl.weekday()] if hasattr(tgl,'weekday') else ''
        bg=F(R1) if i%2==0 else F(R2)
        late=int(row.terlambat); ot=int(row.lembur)
        tap_info = f"{row.tap_total}x" if hasattr(row,'tap_total') else '-'
        vals=[i+1,row.nama,tgl.strftime('%d/%m/%Y'),dn,
              row.jam_masuk,row.jam_keluar,tap_info,
              f"{late} mnt" if late>0 else '-',
              f"{ot} mnt"   if ot>0   else '-']
        for col,v in enumerate(vals,1):
            c=wd.cell(row=r3,column=col,value=v)
            c.font=fnt(9,col==2)
            if col==7:  # total tap
                redundant = hasattr(row,'tap_total') and row.tap_total > 2
                c.font=fnt(9,True,'FF6B21A8' if redundant else GTX)
                c.fill=F('FFEDE9FE' if redundant else GBG)
            elif col==8 and late>0: c.font=fnt(9,True,OTX); c.fill=F(OBG)
            elif col==9 and ot>0:   c.font=fnt(9,True,'FF1D4ED8'); c.fill=F('FFE0EAFF')
            else: c.fill=bg
            c.alignment=C if col!=2 else L; c.border=Bs('thin',BD)
        wd.row_dimensions[r3].height=15

    # reorder
    ms=[s for s in wb.sheetnames if s not in ('Rekap','Keterlambatan','Log Detail')]
    wb._sheets=[wb[s] for s in ms+['Rekap','Keterlambatan','Log Detail']]
    wb.save(out_path)
    return len(daily)

# ─────────────────────────────────────────────────────────────────────────────
# DIALOG: SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, cfg, on_save):
        super().__init__(parent)
        self.title("Pengaturan"); self.resizable(False,False); self.grab_set()
        self.cfg=cfg; self.on_save=on_save; self._build()

    def _build(self):
        nb=ttk.Notebook(self); nb.pack(fill='both',expand=True,padx=10,pady=10)
        t1=ttk.Frame(nb); nb.add(t1,text='Koneksi & Jam')
        fields=[('IP Address','ip'),('Port','port'),
                ('Jam Masuk Standar (HH:MM)','jam_masuk'),
                ('Jam Keluar Standar (HH:MM)','jam_keluar'),
                ('Toleransi Terlambat (menit)','toleransi')]
        self.vars={}
        for i,(label,key) in enumerate(fields):
            ttk.Label(t1,text=label).grid(row=i,column=0,sticky='w',padx=10,pady=4)
            v=tk.StringVar(value=str(self.cfg.get(key,'')))
            ttk.Entry(t1,textvariable=v,width=20).grid(row=i,column=1,sticky='w',padx=10,pady=4)
            self.vars[key]=v
        ab=tk.BooleanVar(value=self.cfg.get('auto_backup',True))
        ttk.Checkbutton(t1,text='Auto backup CSV setelah tarik data',variable=ab).grid(
            row=len(fields),column=0,columnspan=2,sticky='w',padx=10,pady=4)
        self.vars['auto_backup']=ab

        t2=ttk.Frame(nb); nb.add(t2,text='Nama Karyawan')
        ttk.Label(t2,text='Format: UID=Nama (satu per baris)',
                  foreground='#666').pack(anchor='w',padx=10,pady=(8,2))
        self.user_text=scrolledtext.ScrolledText(t2,width=35,height=14,font=('Consolas',9))
        self.user_text.pack(padx=10,pady=(0,8))
        um=self.cfg.get('user_map',{})
        self.user_text.insert('end','\n'.join(f"{k}={v}" for k,v in sorted(um.items(),key=lambda x:int(x[0]))))

        bf=tk.Frame(self); bf.pack(pady=(0,10))
        ttk.Button(bf,text='💾 Simpan',command=self._save).pack(side='left',padx=6)
        ttk.Button(bf,text='Batal',command=self.destroy).pack(side='left',padx=6)

    def _save(self):
        for key,v in self.vars.items():
            try:
                if key=='toleransi': self.cfg[key]=int(v.get())
                elif key=='auto_backup': self.cfg[key]=bool(v.get())
                else: self.cfg[key]=v.get()
            except: self.cfg[key]=v.get()
        um={}
        for line in self.user_text.get('1.0','end').strip().splitlines():
            if '=' in line:
                k,_,v2=line.partition('=')
                if k.strip().isdigit(): um[k.strip()]=v2.strip()
        self.cfg['user_map']=um
        save_config(self.cfg)
        self.on_save(self.cfg)
        self.destroy()

# ─────────────────────────────────────────────────────────────────────────────
# DIALOG: DEVICE INFO
# ─────────────────────────────────────────────────────────────────────────────
class DeviceInfoDialog(tk.Toplevel):
    def __init__(self, parent, info_dict):
        super().__init__(parent)
        self.title("Info Device"); self.resizable(False,False); self.grab_set()
        tk.Label(self,text="  Info Device eFace10",font=("Segoe UI",11,"bold"),
                 bg='#1A56DB',fg='white').pack(fill='x',pady=4)
        fr=ttk.Frame(self,padding=12); fr.pack(fill='both',expand=True)
        for i,(k,v) in enumerate(info_dict.items()):
            ttk.Label(fr,text=k+':',font=('Segoe UI',9,'bold')).grid(row=i,column=0,sticky='w',pady=3,padx=(0,16))
            ttk.Label(fr,text=str(v),font=('Segoe UI',9)).grid(row=i,column=1,sticky='w')
        ttk.Button(self,text='Tutup',command=self.destroy).pack(pady=8)

# ─────────────────────────────────────────────────────────────────────────────
# DIALOG: USER MANAGER
# ─────────────────────────────────────────────────────────────────────────────
class UserManagerDialog(tk.Toplevel):
    def __init__(self, parent, users):
        super().__init__(parent)
        self.title("User di Mesin"); self.resizable(False,False); self.grab_set()
        tk.Label(self,text="  Daftar User di Mesin eFace10",font=("Segoe UI",11,"bold"),
                 bg='#1A56DB',fg='white').pack(fill='x',pady=4)
        fr=ttk.Frame(self,padding=8); fr.pack(fill='both',expand=True)
        cols=('UID','Nama','Card ID')
        self.tree=ttk.Treeview(fr,columns=cols,show='headings',height=14)
        for col,w in zip(cols,[80,180,140]):
            self.tree.heading(col,text=col); self.tree.column(col,width=w)
        sb=ttk.Scrollbar(fr,orient='vertical',command=self.tree.yview)
        self.tree.config(yscrollcommand=sb.set)
        self.tree.pack(side='left'); sb.pack(side='right',fill='y')
        for u in users:
            self.tree.insert('','end',values=(u['uid'],u['nama'],u.get('card_id','')))
        bf=tk.Frame(self); bf.pack(pady=6)
        ttk.Label(bf,text=f"Total: {len(users)} user").pack(side='left',padx=10)
        ttk.Button(bf,text='Tutup',command=self.destroy).pack(side='right',padx=10)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"ZKTeco eFace10 Utility v{APP_VERSION} — CV RAJ")
        self.resizable(False,False)
        self.configure(bg='#F1F5F9')
        self.cfg=load_config()
        self._cache=[]
        init_db()
        self._build_ui()
        self._update_status()

    def _build_ui(self):
        pad=dict(padx=10,pady=4)

        # Header
        hdr=tk.Frame(self,bg='#1A56DB'); hdr.grid(row=0,column=0,sticky='ew')
        # Set window icon
        _base = os.path.dirname(os.path.abspath(__file__))
        try:
            if _sys.platform=='win32' and os.path.exists(os.path.join(_base,'app_icon.ico')):
                self.iconbitmap(os.path.join(_base,'app_icon.ico'))
            elif os.path.exists(os.path.join(_base,'app_icon.png')):
                _img=tk.PhotoImage(file=os.path.join(_base,'app_icon.png'))
                self.iconphoto(True,_img)
        except Exception: pass
        tk.Label(hdr,text=f"  ZKTeco eFace10 Utility  ·  CV RAJ",
                 font=('Segoe UI',12,'bold'),bg='#1A56DB',fg='white',pady=9).pack(side='left')
        ttk.Button(hdr,text='⚙ Settings',command=self._open_settings).pack(side='right',padx=8,pady=6)
        ttk.Button(hdr,text='⬆ Update',command=self._check_update).pack(side='right',padx=4,pady=6)
        self.ver_lbl=tk.Label(hdr,text=f"v{APP_VERSION}  ",font=('Segoe UI',8),bg='#1A56DB',fg='#93C5FD')
        self.ver_lbl.pack(side='right')
        # Language picker
        lf=tk.Frame(hdr,bg='#1A56DB'); lf.pack(side='right',padx=4)
        tk.Label(lf,text='🌐',bg='#1A56DB',fg='white',font=('Segoe UI',9)).pack(side='left')
        self.lang_var=tk.StringVar(value=self.cfg.get('lang','en'))
        lc=ttk.Combobox(lf,textvariable=self.lang_var,values=['en','id'],width=4,state='readonly')
        lc.pack(side='left',pady=8,padx=(0,4))
        lc.bind('<<ComboboxSelected>>',self._on_lang_change)

        # Koneksi
        fc=ttk.LabelFrame(self,text='Koneksi Device',padding=8)
        fc.grid(row=1,column=0,sticky='ew',**pad)
        ttk.Label(fc,text='IP:').grid(row=0,column=0,sticky='w')
        self.ip_var=tk.StringVar(value=self.cfg['ip'])
        ttk.Entry(fc,textvariable=self.ip_var,width=16).grid(row=0,column=1,padx=4)
        ttk.Label(fc,text='Port:').grid(row=0,column=2,sticky='w',padx=(8,0))
        self.port_var=tk.StringVar(value=self.cfg['port'])
        ttk.Entry(fc,textvariable=self.port_var,width=7).grid(row=0,column=3,padx=4)
        ttk.Button(fc,text='🔌 Test Koneksi',command=lambda:self._run(self._do_test)).grid(row=0,column=4,padx=6)
        ttk.Button(fc,text='ℹ Info Device',command=lambda:self._run(self._do_info)).grid(row=0,column=5,padx=4)
        ttk.Button(fc,text='👤 Kelola User',command=lambda:self._run(self._do_users)).grid(row=0,column=6,padx=4)
        self.conn_lbl=tk.Label(fc,text='● Belum terhubung',font=('Segoe UI',8),fg='#888',bg='#F1F5F9')
        self.conn_lbl.grid(row=0,column=7,padx=8)

        # Output
        fo=ttk.LabelFrame(self,text='Folder Output',padding=8)
        fo.grid(row=2,column=0,sticky='ew',**pad)
        self.out_var=tk.StringVar(value=self.cfg.get('output_dir') or os.path.expanduser('~\\Desktop'))
        ttk.Entry(fo,textvariable=self.out_var,width=56).grid(row=0,column=0,padx=(0,6))
        ttk.Button(fo,text='Browse…',command=self._browse).grid(row=0,column=1)

        # Alur Kerja
        fw=ttk.LabelFrame(self,text='Alur Kerja',padding=10)
        fw.grid(row=3,column=0,sticky='ew',**pad)

        def mkstep(col, no, title, desc):
            f=tk.Frame(fw,bg='#EFF6FF',relief='groove',bd=1)
            f.grid(row=0,column=col,padx=4,pady=2,sticky='n')
            tk.Label(f,text=f"{'①②③④'[no-1]} {title}",font=('Segoe UI',8,'bold'),
                     bg='#EFF6FF',fg='#1e40af').pack(pady=(6,1),padx=10)
            tk.Label(f,text=desc,font=('Segoe UI',7),bg='#EFF6FF',fg='#555').pack(padx=10)
            return f

        def arrow(col):
            tk.Label(fw,text='→',font=('Segoe UI',14),fg='#94A3B8',bg='#F1F5F9').grid(row=0,column=col,padx=2)

        f1=mkstep(0,1,'Set Waktu','Sync RTC mesin\nke waktu PC')
        self.btn_time=ttk.Button(f1,text='🕐 Set Waktu Mesin',width=18,
                                  command=lambda:self._run(self._do_settime))
        self.btn_time.pack(pady=(4,8),padx=8)

        arrow(1)

        f2=mkstep(2,2,'Tarik Data','Ambil log absensi\n& simpan ke database')
        self.btn_pull=ttk.Button(f2,text='📥 Tarik Data Absensi',width=18,
                                  command=lambda:self._run(self._do_pull))
        self.btn_pull.pack(pady=(4,8),padx=8)

        arrow(3)

        f3=mkstep(4,3,'Filter Periode','Pilih rentang\nwaktu laporan')
        ff=tk.Frame(f3,bg='#EFF6FF'); ff.pack(padx=8,pady=2)
        tk.Label(ff,text='Bulan:',font=('Segoe UI',7),bg='#EFF6FF').grid(row=0,column=0,sticky='w')
        self.bulan_var=tk.StringVar(value='Semua')
        ttk.Combobox(ff,textvariable=self.bulan_var,values=['Semua']+BULAN_ID,width=10,state='readonly').grid(row=0,column=1,padx=3)
        tk.Label(ff,text='Tahun:',font=('Segoe UI',7),bg='#EFF6FF').grid(row=1,column=0,sticky='w',pady=2)
        now=datetime.now()
        self.tahun_var=tk.StringVar(value=str(now.year))
        ttk.Combobox(ff,textvariable=self.tahun_var,
                     values=[str(y) for y in range(now.year-3,now.year+2)],
                     width=7,state='readonly').grid(row=1,column=1,padx=3)
        tk.Label(f3,text='Sumber data:',font=('Segoe UI',7),bg='#EFF6FF').pack(pady=(2,0))
        self.src_var=tk.StringVar(value='database')
        ttk.Radiobutton(f3,text='Database lokal',variable=self.src_var,value='database').pack(anchor='w',padx=8)
        ttk.Radiobutton(f3,text='Cache sesi ini',variable=self.src_var,value='cache').pack(anchor='w',padx=8)

        arrow(5)

        f4=mkstep(6,4,'Generate Report','Buat Excel laporan\nkartu absensi')
        self.btn_report=ttk.Button(f4,text='📊 Generate Excel',width=18,
                                    command=lambda:self._run(self._do_report))
        self.btn_report.pack(pady=(4,8),padx=8)

        # Shortcut bar
        sf=tk.Frame(fw,bg='#F1F5F9'); sf.grid(row=1,column=0,columnspan=7,pady=(6,0))
        self.btn_all=ttk.Button(sf,text='⚡ Semua Sekaligus  (Set Waktu → Tarik → Generate)',
                                 command=lambda:self._run(self._do_all))
        self.btn_all.pack(side='left',padx=4)
        ttk.Separator(sf,orient='vertical').pack(side='left',fill='y',padx=8)
        ttk.Button(sf,text='🗑 Clear Log Mesin',command=self._confirm_clear).pack(side='left',padx=4)
        ttk.Button(sf,text='📂 Buka Folder Output',command=self._open_output).pack(side='left',padx=4)

        # status data
        self.data_lbl=tk.Label(fw,text='...',font=('Segoe UI',8),fg='#1e40af',bg='#F1F5F9')
        self.data_lbl.grid(row=2,column=0,columnspan=7,pady=(4,0))

        # Log
        fl=ttk.LabelFrame(self,text='Log',padding=6)
        fl.grid(row=4,column=0,sticky='nsew',**pad)
        self.log_box=scrolledtext.ScrolledText(fl,width=74,height=10,
            font=('Consolas',8),state='disabled',bg='#0F172A',fg='#CBD5E1')
        self.log_box.pack(fill='both',expand=True)

        # Status bar
        self.status_var=tk.StringVar(value='Siap.')
        ttk.Label(self,textvariable=self.status_var,relief='sunken',anchor='w'
                  ).grid(row=5,column=0,sticky='ew',padx=10,pady=(0,6))

        self._btns=[self.btn_time,self.btn_pull,self.btn_report,self.btn_all]

    # Helpers
    def _log(self,msg):
        ts=datetime.now().strftime('%H:%M:%S')
        self.log_box.config(state='normal')
        self.log_box.insert('end',f'[{ts}] {msg}\n')
        self.log_box.see('end')
        self.log_box.config(state='disabled')
        self.after(0,lambda:self.status_var.set(msg))

    def _browse(self):
        d=filedialog.askdirectory()
        if d: self.out_var.set(d)

    def _open_output(self):
        p=self.out_var.get()
        if os.path.exists(p): _open_path(p)

    def _get_conn(self):
        from zk import ZK
        return ZK(self.ip_var.get().strip(),port=int(self.port_var.get()),
                  timeout=15,password=0,force_udp=False,ommit_ping=False).connect()

    def _set_buttons(self,state):
        for b in self._btns:
            try: b.config(state=state)
            except: pass

    def _run(self,fn):
        self._set_buttons('disabled')
        threading.Thread(target=self._worker,args=(fn,),daemon=True).start()

    def _worker(self,fn):
        try: fn()
        except Exception as e:
            self.after(0,lambda: self._log(f'[ERROR] {e}'))
            self.after(0,lambda: messagebox.showerror('Error',str(e)))
        finally:
            self.after(0,lambda: self._set_buttons('normal'))
            self.after(0,self._update_status)

    def _update_status(self):
        n=db_count()
        self.data_lbl.config(
            text=f'Database lokal: {n:,} record  |  Cache sesi ini: {len(self._cache):,} record')

    def _open_settings(self):
        def on_save(new_cfg):
            self.cfg=new_cfg
            self.ip_var.set(new_cfg['ip'])
            self.port_var.set(new_cfg['port'])
            self._log('✓ Pengaturan disimpan')
        SettingsDialog(self,self.cfg,on_save)

    def _confirm_clear(self):
        if messagebox.askyesno('Konfirmasi',
            'Hapus SEMUA log absensi dari memori mesin?\n\n'
            'Data yang sudah tersimpan di database lokal TIDAK akan terhapus.'):
            self._run(self._do_clear)

    # Update
    def _check_update(self):
        if not _UPDATER_OK:
            messagebox.showinfo("Update", "Modul updater tidak ditemukan."); return
        self._log("Memeriksa versi terbaru di GitHub...")
        def _run():
            info = get_latest_release()
            if info is None:
                self.after(0, lambda: self._log("⚠ Tidak bisa cek update (tidak ada koneksi internet atau repo belum ada release)."))
                return
            latest  = info['version']
            body    = info['body'] or '(tidak ada catatan)'
            dl_url  = info['download_url']
            if not is_newer(latest, APP_VERSION):
                self.after(0, lambda: self._log(f"✓ Sudah versi terbaru (v{APP_VERSION})"))
                self.after(0, lambda: messagebox.showinfo("Update", f"Sudah versi terbaru!\nVersi kamu: v{APP_VERSION}"))
                return
            # Ada update
            msg = f"Versi baru tersedia: {latest}\n\nChangelog:\n{body[:400]}\n\nDownload & update sekarang?"
            if not self.after(0, lambda: None):  pass  # flush
            do_it = [False]
            def _ask():
                do_it[0] = messagebox.askyesno("Update Tersedia", msg)
            self.after(0, _ask)
            self.after(500, lambda: self._do_download(dl_url, latest) if do_it[0] else None)
        threading.Thread(target=_run, daemon=True).start()

    def _do_download(self, url, version):
        self._log(f"Mengunduh v{version} ...")
        # Progress bar dialog
        dlg = tk.Toplevel(self)
        dlg.title("Mengunduh Update"); dlg.resizable(False,False); dlg.grab_set()
        tk.Label(dlg, text=f"Mengunduh ZKTeco Utility {version}",
                 font=('Segoe UI',10)).pack(padx=20,pady=(14,4))
        pbar = ttk.Progressbar(dlg, length=320, mode='determinate')
        pbar.pack(padx=20,pady=6)
        pct_lbl = tk.Label(dlg, text="0%", font=('Segoe UI',9))
        pct_lbl.pack(pady=(0,14))

        def on_progress(pct):
            self.after(0, lambda: pbar.configure(value=pct))
            self.after(0, lambda: pct_lbl.configure(text=f"{pct}%"))

        def on_done():
            self.after(0, dlg.destroy)
            self._log(f"✓ Update {version} selesai diunduh — app akan restart otomatis")
            self.after(0, lambda: messagebox.showinfo(
                "Update Selesai",
                f"Update ke {version} selesai!\n\nApp akan ditutup dan restart otomatis.\n"
                "Kalau tidak restart, jalankan EXE secara manual."
            ))
            self.after(1500, self.destroy)  # tutup app, bat akan restart

        def on_error(msg):
            self.after(0, dlg.destroy)
            self._log(f"[ERROR] Gagal download update: {msg}")
            self.after(0, lambda: messagebox.showerror("Error", f"Gagal download:\n{msg}"))

        download_and_replace(url, on_progress=on_progress, on_done=on_done, on_error=on_error)

    def _on_lang_change(self, _=None):
        lang = self.lang_var.get()
        self.cfg['lang'] = lang
        save_config(self.cfg)
        msg = ("Language set to English. Restart app to apply."
               if lang=='en' else
               "Bahasa diubah ke Indonesia. Restart aplikasi untuk menerapkan.")
        messagebox.showinfo("Language", msg)

    # Aksi
    def _do_test(self):
        ip=self.ip_var.get().strip()
        self._log(f'Test koneksi ke {ip}:{self.port_var.get()} ...')
        conn=self._get_conn()
        try:
            fw=conn.get_firmware_version()
            self._log(f'✓ Terhubung! Firmware: {fw}')
            self.after(0,lambda: self.conn_lbl.config(text=f'● {ip}',fg='#16a34a'))
        finally: conn.disconnect()

    def _do_info(self):
        self._log('Mengambil info device ...')
        conn=self._get_conn()
        try:
            info={
                'Serial Number' : conn.get_serialnumber(),
                'Firmware'      : conn.get_firmware_version(),
                'Waktu Mesin'   : str(conn.get_time()),
                'Jumlah User'   : len(conn.get_users()),
                'Jumlah Log'    : len(conn.get_attendance()),
                'Database Lokal': f'{db_count():,} record',
            }
            self._log('✓ Info device diterima')
            self.after(0,lambda: DeviceInfoDialog(self,info))
        finally: conn.disconnect()

    def _do_users(self):
        self._log('Mengambil daftar user ...')
        conn=self._get_conn()
        try:
            users=conn.get_users()
            ulist=[{'uid':int(u.user_id),'nama':u.name,'card_id':getattr(u,'card','') or ''} for u in users]
            db_upsert_users(ulist)
            for u in ulist:
                self.cfg['user_map'][str(u['uid'])]=u['nama']
            save_config(self.cfg)
            self._log(f'✓ {len(ulist)} user — nama disimpan ke config & database')
            self.after(0,lambda: UserManagerDialog(self,ulist))
        finally: conn.disconnect()

    def _do_settime(self):
        self._log('Set waktu mesin ...')
        conn=self._get_conn()
        try:
            now=datetime.now()
            conn.set_time(now)
            self._log(f'✓ Waktu mesin → {now.strftime("%Y-%m-%d %H:%M:%S")}')
        finally: conn.disconnect()

    def _do_pull(self):
        self._log('Menarik data absensi dari mesin ...')
        conn=self._get_conn()
        try:
            atts=conn.get_attendance()
            if not atts: self._log('⚠ Tidak ada data.'); return
            um={int(k):v for k,v in self.cfg.get('user_map',{}).items()}
            self._cache=[{
                'uid'      : int(a.user_id),
                'nama'     : um.get(int(a.user_id), f'UID:{a.user_id}'),
                'timestamp': a.timestamp,
                'punch'    : a.punch,
            } for a in atts]
            new=db_insert_attendance(self._cache)
            self._log(f'✓ {len(atts)} record ditarik  |  {new} baru disimpan ke database')
            if self.cfg.get('auto_backup',True):
                ts=datetime.now().strftime('%Y%m%d_%H%M%S')
                path=os.path.join(self.out_var.get(),f'backup_raw_{ts}.csv')
                with open(path,'w',newline='',encoding='utf-8') as f:
                    w=csv.writer(f)
                    w.writerow(['UserID','Nama','Timestamp','Status'])
                    for a in atts:
                        uid=int(a.user_id)
                        w.writerow([uid,um.get(uid,f'UID:{uid}'),
                                    a.timestamp.strftime('%Y-%m-%d %H:%M:%S') if a.timestamp else '',
                                    'Check-In' if a.punch==0 else 'Check-Out'])
                self._log(f'  Auto backup CSV → {path}')
        finally: conn.disconnect()

    def _do_clear(self):
        self._log('⚠ Menghapus log dari memori mesin ...')
        conn=self._get_conn()
        try:
            conn.clear_attendance()
            self._log('✓ Log absensi di mesin berhasil dihapus')
        finally: conn.disconnect()

    def _do_report(self):
        yr  =int(self.tahun_var.get())
        bln =self.bulan_var.get()
        mo  =BULAN_ID.index(bln)+1 if bln!='Semua' else None
        src =self.src_var.get()
        if src=='cache':
            if not self._cache: raise RuntimeError('Belum ada cache. Tarik data dulu.')
            rows=self._cache
            self._log(f'Generate dari cache ({len(rows)} record) ...')
        else:
            rows=db_query_attendance(yr,mo)
            if not rows: raise RuntimeError(f'Tidak ada data di database untuk {bln} {yr}.')
            self._log(f'Generate dari database ({len(rows)} record) ...')
        bln_str=f'_{bln}' if bln!='Semua' else '_Semua'
        ts=datetime.now().strftime('%Y%m%d_%H%M%S')
        out=os.path.join(self.out_var.get(),f'Absensi_CVRAJ{bln_str}_{yr}_{ts}.xlsx')
        n=generate_excel(rows,out,self.cfg)
        self._log(f'✓ Report selesai ({n} baris) → {out}')
        _open_path(out)

    def _do_all(self):
        self._do_settime()
        self._do_pull()
        self._do_report()

if __name__=='__main__':
    app=App()
    app.mainloop()
