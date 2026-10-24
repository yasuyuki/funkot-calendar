#!/usr/bin/env python3
"""Generate funkot-parties.ics from events.json.

Usage: python3 gen_ics.py [--out PATH] [--events PATH]
  default --out: funkot-parties.ics next to this script (overwritten)

Format (matches the ICS published at GitHub yasuyuki/funkot-calendar):
- CRLF line endings, no line folding, UTF-8.
- VEVENTs sorted by start; UID = <id>@funkot-parties.yasuyuki.
- Timed events: DTSTART/DTEND;TZID=Asia/Tokyo. Events with no time
  (start/end as YYYY-MM-DD, or missing end) become all-day (VALUE=DATE).
- tentative: STATUS:TENTATIVE, SUMMARY prefixed 【Funkot?】 (not doubled),
  DESCRIPTION prefixed "確度: tentative（未確定）".
- cancelled: STATUS:CANCELLED, SUMMARY prefixed 【中止】.
- DTSTAMP: reused per UID from the existing output file (or the default ICS)
  so reruns don't produce noise; new events get a stable value derived from
  events.json updated_at.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_EVENTS = os.path.join(HERE, "events.json")
DEFAULT_OUT = os.path.join(HERE, "funkot-parties.ics")
UID_DOMAIN = "funkot-parties.yasuyuki"
TZID = "Asia/Tokyo"
JST = dt.timezone(dt.timedelta(hours=9))
TENTATIVE_PREFIX = "【Funkot?】"
CANCELLED_PREFIX = "【中止】"

HEADER = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//yasuyuki//Funkot Parties//JA",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:Funkot Parties",
    "X-WR-TIMEZONE:Asia/Tokyo",
]


def esc(text):
    return (str(text).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def existing_dtstamps(paths):
    stamps = {}
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        uid = None
        with open(p, encoding="utf-8") as f:
            for line in f.read().splitlines():
                if line.startswith("BEGIN:VEVENT"):
                    uid = None
                elif line.startswith("UID:"):
                    uid = line[4:]
                elif line.startswith("DTSTAMP:") and uid and uid not in stamps:
                    stamps[uid] = line[8:]
    return stamps


def is_date_only(s):
    return bool(s) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) is not None


def to_local(s):
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=JST)
    return t.astimezone(JST)


def time_lines(ev):
    start, end = ev.get("start"), ev.get("end")
    if is_date_only(start) or ev.get("all_day") or ev.get("time_tbd"):
        d0 = dt.date.fromisoformat(start[:10])
        if end and is_date_only(end) and end > start:
            d1 = dt.date.fromisoformat(end)  # treat as exclusive end
        elif end and not is_date_only(end):
            d1 = to_local(end).date() + dt.timedelta(days=1)
        else:
            d1 = d0 + dt.timedelta(days=1)
        if d1 <= d0:
            d1 = d0 + dt.timedelta(days=1)
        return [f"DTSTART;VALUE=DATE:{d0:%Y%m%d}", f"DTEND;VALUE=DATE:{d1:%Y%m%d}"]
    s = to_local(start)
    lines = [f"DTSTART;TZID={TZID}:{s:%Y%m%dT%H%M%S}"]
    if end:
        lines.append(f"DTEND;TZID={TZID}:{to_local(end):%Y%m%dT%H%M%S}")
    return lines


def sort_key(ev):
    s = ev.get("start") or "9999-12-31"
    try:
        k = (dt.datetime.combine(dt.date.fromisoformat(s), dt.time(0), JST)
             if is_date_only(s) else to_local(s))
    except ValueError:
        k = dt.datetime.max.replace(tzinfo=JST)
    return (k, ev.get("id", ""))


def build(data, stamps):
    fallback = data.get("updated_at")
    if fallback:
        fallback = to_local(fallback).astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    else:
        fallback = "20260101T000000Z"
    out = list(HEADER)
    for ev in sorted(data.get("events", []), key=sort_key):
        status = (ev.get("status") or "confirmed").lower()
        uid = f"{ev['id']}@{UID_DOMAIN}"
        summary = ev.get("summary") or ev.get("title") or ev["id"]
        desc = []
        if status == "tentative":
            if not summary.startswith(TENTATIVE_PREFIX):
                summary = TENTATIVE_PREFIX + summary
            desc.append("確度: tentative（未確定）")
        elif status == "cancelled":
            if not summary.startswith(CANCELLED_PREFIX):
                summary = CANCELLED_PREFIX + summary
            desc.append("状態: 中止")
        if ev.get("notes"):
            desc.append(ev["notes"])
        if ev.get("url"):
            desc.append(ev["url"])
        if ev.get("source"):
            desc.append(f"source: {ev['source']}")
        out += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamps.get(uid, fallback)}"]
        out += time_lines(ev)
        out.append(f"SUMMARY:{esc(summary)}")
        if ev.get("location"):
            out.append(f"LOCATION:{esc(ev['location'])}")
        if desc:
            out.append("DESCRIPTION:" + "\\n".join(esc(x) for x in desc))
        if ev.get("url"):
            out.append(f"URL:{ev['url']}")
        if status == "tentative":
            out.append("STATUS:TENTATIVE")
        elif status == "cancelled":
            out.append("STATUS:CANCELLED")
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--events", default=DEFAULT_EVENTS)
    a = ap.parse_args(argv)
    with open(a.events, encoding="utf-8") as f:
        data = json.load(f)
    stamps = existing_dtstamps([a.out, DEFAULT_OUT])
    ics = build(data, stamps)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    n = ics.count("BEGIN:VEVENT")
    print(f"wrote {a.out}: {n} events "
          f"(tentative {ics.count('STATUS:TENTATIVE')}, cancelled {ics.count('STATUS:CANCELLED')})")


if __name__ == "__main__":
    sys.exit(main())
