#!/usr/bin/env python3
"""
Recover the "missing" 11-23 June attendance (clock-reset / year-2000 records) and
export a full attendance workbook — WITHOUT touching the device.

The eFace10 has no RTC battery, so a power loss resets its clock to year 2000.
Punches made during the outage are stored with bogus year-2000 dates. This script
pulls them, remaps them onto real calendar dates, and writes an .xlsx to Desktop.

Run:  python recover_and_export.py
"""
import os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zk import ZK
from zkteco_app import (load_config, generate_excel_bytes,
                        remap_anomalies, find_gap_start, is_anomaly_ts)


def main():
    cfg = load_config()
    ip  = cfg.get('ip', '10.10.11.55')
    port = int(cfg.get('port', 8088))
    print(f'Connecting to {ip}:{port} ...')
    conn = ZK(ip, port=port, timeout=25, password=0,
              force_udp=False, ommit_ping=False).connect()
    try:
        dev_time = conn.get_time()
        atts = conn.get_attendance()
    finally:
        conn.disconnect()
    print(f'Device clock: {dev_time}  |  total records on device: {len(atts)}')

    um = {int(k): v for k, v in cfg.get('user_map', {}).items()}
    recs = [{'uid': int(a.user_id),
             'nama': um.get(int(a.user_id), f'UID:{a.user_id}'),
             'timestamp': a.timestamp, 'punch': a.punch}
            for a in atts if a.timestamp]

    anomaly = [r for r in recs if is_anomaly_ts(r['timestamp'])]
    normal  = [r for r in recs if not is_anomaly_ts(r['timestamp'])]

    cfg_anchor = str(cfg.get('anomaly_anchor', '') or '').strip()
    anchor = None
    if cfg_anchor:
        try:
            anchor = datetime.strptime(cfg_anchor, '%Y-%m-%d').date()
        except ValueError:
            anchor = None
    if anchor is None:
        anchor = find_gap_start(normal)

    remapped = remap_anomalies(anomaly, anchor,
                               cfg.get('jam_masuk', '08:00'),
                               cfg.get('jam_keluar', '16:00'))
    n_days = len(set(r['timestamp'].date() for r in remapped))
    print(f'Anomaly (year-2000) records : {len(anomaly)}')
    print(f'Recovered onto              : {anchor} .. +{max(0,n_days-1)} days '
          f'({len(remapped)} punches, {n_days} days)')

    all_rows = normal + remapped

    # 1) Full styled workbook (same template as the app), all months present
    data = generate_excel_bytes(all_rows, cfg)
    desk = os.path.join(os.path.expanduser('~'), 'Desktop')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    xlsx = os.path.join(desk, f'Absensi_CVRAJ_RECOVERED_{stamp}.xlsx')
    with open(xlsx, 'wb') as f:
        f.write(data)
    print(f'Saved workbook  -> {xlsx}')

    # 2) Audit CSV: original corrupted timestamp vs remapped timestamp
    import csv
    audit = os.path.join(desk, f'Recovered_audit_{stamp}.csv')
    with open(audit, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['UID', 'Name', 'OriginalTimestamp', 'RemappedTimestamp', 'Status'])
        for r in sorted(remapped, key=lambda x: x['timestamp']):
            w.writerow([r['uid'], r['nama'],
                        r['orig_ts'].strftime('%Y-%m-%d %H:%M:%S'),
                        r['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                        'Check-In' if r['punch'] == 0 else 'Check-Out'])
    print(f'Saved audit CSV -> {audit}')


if __name__ == '__main__':
    main()
