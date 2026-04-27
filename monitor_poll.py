"""monitor_poll.py — quick status snapshot"""
import sqlite3, json, sys, time, subprocess
from pathlib import Path

ROOT  = Path(r'C:\Riot Commander')
TODAY = time.strftime('%Y-%m-%d')

h           = json.loads((ROOT/'ops/runtime/health.json').read_text(encoding='utf-8'))
pid         = h['pid']
alive       = h['alive']
mode        = h['mode']
has_game    = h['has_game']
aram        = h['aram_mode']
ui_age      = h.get('ui_pulse_age_s', 0)
poll_age    = h.get('game_poll_worker_age_s', 0)
reload_ok   = h['last_reload_ok']
reload_err  = h['last_reload_error']

issues = []
if not alive:          issues.append('DEAD')
if ui_age > 10:        issues.append('UI_STALE({:.0f}s)'.format(ui_age))
if poll_age > 15:      issues.append('POLL_STALE({:.0f}s)'.format(poll_age))
if not reload_ok:      issues.append('RELOAD_FAIL: {}'.format(reload_err))
if h.get('booting'):   issues.append('BOOTING')

log_path = ROOT / ('logs/' + TODAY + '.log')
new_errors = []
if log_path.exists():
    lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
    start = 0
    for i in range(len(lines)-1, -1, -1):
        if 'SrAramWorker gen=1 started' in lines[i]:
            start = i; break
    for l in lines[start:]:
        if ' ERROR ' in l or ' CRITICAL ' in l:
            if 'config_validator' not in l and 'ERROR  0' not in l:
                new_errors.append(l.strip()[-120:])
if new_errors:
    issues.append('{} LOG_ERRORS'.format(len(new_errors)))

db = ROOT / 'data/rewind_history.db'
scraper_info = 'no_db'
if db.exists():
    try:
        conn = sqlite3.connect(str(db), timeout=2)
        m  = conn.execute('SELECT COUNT(*) FROM matches').fetchone()[0]
        ev = conn.execute('SELECT COUNT(*) FROM timeline_events').fetchone()[0]
        conn.close()
        pct = int(m/2846*100)
        scraper_info = 'rewind={}/2846({}%) ev={:,}'.format(m, pct, ev)
        if m < 2846:
            r = subprocess.run(['tasklist','/FI','IMAGENAME eq python.exe','/FO','CSV'],
                               capture_output=True, text=True)
            py_procs = max(0, r.stdout.count('python.exe') - 1)
            scraper_info += ' scraper={}'.format('running' if py_procs > 0 else 'STOPPED')
    except Exception as e:
        scraper_info = 'db_err:{}'.format(str(e)[:40])

import urllib.request
moon_ok = False
moon_info = 'unreachable'
try:
    req = urllib.request.Request('http://127.0.0.1:8889/health',
                                 headers={'User-Agent': 'RC'})
    resp = json.loads(urllib.request.urlopen(req, timeout=3).read())
    moon_ok = resp.get('alive', False)
    moon_info = 'ok uptime={}h'.format(resp.get('uptime_s', 0)//3600)
except Exception:
    if has_game and aram:
        issues.append('MOON_DOWN_DURING_ARAM')

ts   = time.strftime('%H:%M:%S')
flag = 'WARN' if issues else 'OK  '
print('{} [{}] pid={} mode={} game={} aram={} ui={:.1f}s'.format(
    flag, ts, pid, mode, has_game, aram, ui_age))
print('     moon={} | {}'.format(moon_info, scraper_info))
if issues:
    for i in issues:
        print('     ISSUE: {}'.format(i))
for e in new_errors[:3]:
    print('     ERR: {}'.format(e))
sys.exit(1 if issues else 0)
