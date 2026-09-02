"""
A read-only FTP server holding sample TOA5 (Campbell Scientific) files for
three demo stations, regenerated at every start so the newest observations
are always "now". Layout, per station, mirrors the three file-listing
strategies of the ADL FTP plugin:

  /data/DEMO001/DEMO001_Table10.dat                one appended file (Pattern Only)
  /data/DEMO002/<YYYY>/<MM>/<DD>/DEMO002_<YYYYMMDD>.dat   one file per day (Filter by Date)
  /data/DEMO003/DEMO003_<YYYYMMDDHHMM>.dat          one file per hour (Direct Fetch)

Values are a smooth diurnal cycle plus a little noise, so charts look like
weather rather than random numbers. Nothing here is real data.
"""

import math
import os
import random
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

ROOT = "/srv/ftp"
USER = os.environ.get("FTP_USER", "demo")
PASSWORD = os.environ.get("FTP_PASSWORD", "demo")
TZ = ZoneInfo(os.environ.get("SAMPLE_TZ", "Africa/Nairobi"))
HOURS = int(os.environ.get("SAMPLE_HOURS", "48"))

COLUMNS = ["TIMESTAMP", "RECORD", "AirTC_Avg", "RH", "BP_hPa_Avg",
           "Rain_mm_Tot", "WS_ms_Avg", "WindDir", "SlrW_Avg"]
UNITS = ["TS", "RN", "Deg C", "%", "hPa", "mm", "meters/second", "Deg", "W/m^2"]
PROC = ["", "", "Avg", "Smp", "Avg", "Tot", "Avg", "Smp", "Avg"]


def header(station):
    return [
        f'"TOA5","{station}","CR1000X","12345","CR1000X.Std.05.01","CPU:demo_aws.CR1X","4321","Table10"',
        ",".join(f'"{c}"' for c in COLUMNS),
        ",".join(f'"{u}"' for u in UNITS),
        ",".join(f'"{p}"' for p in PROC),
    ]


def row(moment, record, seed):
    rng = random.Random(f"{seed}-{moment:%Y%m%d%H%M}")
    hour = moment.hour + moment.minute / 60
    diurnal = math.sin((hour - 9) / 24 * 2 * math.pi)  # peaks mid-afternoon
    temp = 21 + 6 * diurnal + rng.uniform(-0.4, 0.4)
    rh = 70 - 25 * diurnal + rng.uniform(-2, 2)
    pressure = 1012 + 2 * math.sin(hour / 12 * math.pi) + rng.uniform(-0.3, 0.3)
    rain = round(rng.choice([0, 0, 0, 0, 0, 0.2, 0.4, 1.2]), 1) if 14 <= hour <= 17 else 0
    wind = max(0.0, 2.5 + 2 * diurnal + rng.uniform(-0.8, 0.8))
    wdir = (90 + 40 * diurnal + rng.uniform(-15, 15)) % 360
    solar = max(0.0, 850 * math.sin((hour - 6) / 12 * math.pi)) if 6 <= hour <= 18 else 0
    solar += rng.uniform(-10, 10) if solar else 0
    return (f'"{moment:%Y-%m-%d %H:%M:%S}",{record},{temp:.2f},{rh:.1f},{pressure:.1f},'
            f'{rain},{wind:.2f},{wdir:.0f},{max(solar, 0):.1f}')


def write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")


def generate():
    now = datetime.now(TZ).replace(second=0, microsecond=0)
    now -= timedelta(minutes=now.minute % 10)
    start = now - timedelta(hours=HOURS)
    moments = [start + timedelta(minutes=10 * i) for i in range(HOURS * 6 + 1)]

    # DEMO001: one file, appended to
    lines = header("DEMO001") + [row(m, i, "DEMO001") for i, m in enumerate(moments)]
    write(f"{ROOT}/data/DEMO001/DEMO001_Table10.dat", lines)

    # DEMO002: a file per day in a YYYY/MM/DD tree
    by_day = {}
    for m in moments:
        by_day.setdefault(m.date(), []).append(m)
    for day, day_moments in by_day.items():
        lines = header("DEMO002") + [row(m, i, "DEMO002") for i, m in enumerate(day_moments)]
        write(f"{ROOT}/data/DEMO002/{day:%Y/%m/%d}/DEMO002_{day:%Y%m%d}.dat", lines)

    # DEMO003: a file per hour, named by its first timestamp
    by_hour = {}
    for m in moments:
        by_hour.setdefault(m.replace(minute=0), []).append(m)
    for hour, hour_moments in by_hour.items():
        lines = header("DEMO003") + [row(m, i, "DEMO003") for i, m in enumerate(hour_moments)]
        write(f"{ROOT}/data/DEMO003/DEMO003_{hour:%Y%m%d%H%M}.dat", lines)

    print(f"[mock-ftp] generated samples for {HOURS}h up to {now:%Y-%m-%d %H:%M} {TZ.key}", flush=True)


def run_plugin_generator():
    """A plugin that needs samples in its own vendor format ships a
    ``docs/screenshots/mock-ftp/generate.py``; the harness mounts that folder
    here and it runs after the built-in TOA5 samples, with ``SAMPLE_ROOT``,
    ``SAMPLE_TZ`` and ``SAMPLE_HOURS`` in its environment."""
    script = "/srv/plugin-samples/generate.py"
    if os.path.exists(script):
        env = {**os.environ, "SAMPLE_ROOT": ROOT, "SAMPLE_TZ": TZ.key, "SAMPLE_HOURS": str(HOURS)}
        print(f"[mock-ftp] running plugin sample generator {script}", flush=True)
        subprocess.run(["python", script], check=True, env=env)


def main():
    os.makedirs(ROOT, exist_ok=True)
    generate()
    run_plugin_generator()
    authorizer = DummyAuthorizer()
    authorizer.add_user(USER, PASSWORD, ROOT, perm="elr")  # list + retrieve only
    handler = FTPHandler
    handler.authorizer = authorizer
    handler.passive_ports = range(30000, 30010)
    handler.banner = "ADL docs mock FTP source"
    server = FTPServer(("0.0.0.0", 21), handler)
    print(f"[mock-ftp] serving {ROOT} on :21 as {USER}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
