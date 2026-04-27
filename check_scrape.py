import sqlite3
from pathlib import Path

db = Path(r'C:\Riot Commander\data\rewind_history.db')
conn = sqlite3.connect(str(db))

m      = conn.execute('SELECT COUNT(*) FROM matches').fetchone()[0]
p      = conn.execute('SELECT COUNT(*) FROM participants').fetchone()[0]
fr     = conn.execute('SELECT COUNT(*) FROM timeline_frames').fetchone()[0]
ev     = conn.execute('SELECT COUNT(*) FROM timeline_events').fetchone()[0]
nostats = conn.execute('SELECT COUNT(*) FROM matches WHERE has_stats=0').fetchone()[0]
last   = conn.execute('SELECT patch, game_mode, tracked_champion_name, fetched_at FROM matches ORDER BY rowid DESC LIMIT 1').fetchone()
conn.close()

size_mb = db.stat().st_size // 1024 // 1024
rate_pct = m / 2846 * 100
remaining = 2846 - m

print(f"Progress:      {m:,} / 2846  ({rate_pct:.1f}%)")
print(f"Remaining:     {remaining:,} matches")
print(f"Participants:  {p:,}")
print(f"TL frames:     {fr:,}")
print(f"TL events:     {ev:,}")
print(f"No-stats err:  {nostats}")
print(f"DB size:       {size_mb} MB")
print(f"Last scraped:  {last}")
