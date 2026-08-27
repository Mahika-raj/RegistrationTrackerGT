#!/usr/bin/env python3
"""
GT seat watcher v8 - alerts the moment a real seat opens in your classes.

SEATS ONLY. Waitlists are not tracked, not displayed, and never alerted on.

Does NOT register for you. Reads Georgia Tech's PUBLIC per-CRN enrollment
endpoint (no login, no Duo), then beeps locally AND pushes to your phone.

RUN IT
  python3 gt_seat_watch_v8.py --ntfy gtseat-mahika-9xdvv3d0

NAME YOUR CLASSES so the notification is readable on a lock screen
(dashes become spaces; only needed if auto-naming misses):
  python3 gt_seat_watch_v8.py --ntfy gtseat-mahika-9xdvv3d0 \
      --crns 89609:CS-1332 89589:MATH-2551 93197:PHYS-2211

KEEP IT ALIVE with the screen off (lid must stay OPEN - closing it sleeps
the Mac and stops the watch):
  nohup caffeinate -dimsu python3 gt_seat_watch_v8.py \
      --ntfy gtseat-mahika-9xdvv3d0 > watch.log 2>&1 &
  tail -f watch.log          # see what it is doing
  pkill -f gt_seat_watch     # stop it

Stdlib only. Ctrl-C to stop.
"""

import argparse
import html as htmlmod
import re
import random
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import http.cookiejar
from datetime import datetime

BASE = "https://registration.banner.gatech.edu/StudentRegistrationSsb/ssb"
REGISTER_URL = "https://buzzport.gatech.edu/"

DEFAULT_CRNS = ["89609", "89589", "93197"]
DEFAULT_TERM = "202608"
SESSION_MAX_AGE = 480
DEAD_AFTER = 900          # if nothing has succeeded in 15 min, push a warning


# ------------------------------------------------------------------ phone push

def normalize_topic(topic):
    """Accept 'mytopic', 'ntfy.sh/mytopic', or 'https://ntfy.sh/mytopic'.

    v5 bug: it ran quote() over whatever you passed, so a full URL became the
    literal topic 'https%3A%2F%2Fntfy.sh%2Fmytopic' - posted fine, returned 200,
    and went nowhere. Normalize first.
    """
    t = (topic or "").strip().rstrip("/")
    t = re.sub(r"^https?://", "", t)
    if "/" in t:
        t = t.split("/")[-1]
    return t


def push(topic, title, message, priority="default", tags="bell", verbose=False):
    """ntfy.sh - free, no account. No-ops if --ntfy wasn't given.

    NOTE: ntfy accepts a POST to ANY topic and returns 200 whether or not a
    single device is subscribed. A 200 here means "ntfy took it", NOT
    "your phone got it". Only your phone buzzing proves delivery.
    """
    if not topic:
        return
    t = normalize_topic(topic)
    url = f"https://ntfy.sh/{urllib.parse.quote(t)}"
    try:
        req = urllib.request.Request(url, data=message.encode("utf-8"))
        req.add_header("Title", title)
        req.add_header("Priority", priority)
        req.add_header("Tags", tags)
        if priority == "urgent":
            req.add_header("Click", REGISTER_URL)
        resp = urllib.request.urlopen(req, timeout=15)
        if verbose:
            print(f"   -> POST {url}  HTTP {resp.status}")
            print("      (200 only means ntfy accepted it - your phone must be "
                  "subscribed to exactly this topic)")
    except Exception as e:
        print(f"   !! push FAILED to {url}: {e}", flush=True)


# ------------------------------------------------------------------ transport

def make_opener():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"),
        ("Accept", "text/html, */*; q=0.01"),
        ("X-Requested-With", "XMLHttpRequest"),
        ("Cache-Control", "no-cache, no-store, max-age=0"),
        ("Pragma", "no-cache"),
    ]
    return op


def start_session(opener, term):
    opener.open(f"{BASE}/classSearch/classSearch", timeout=25).read()
    body = urllib.parse.urlencode({
        "term": term, "studyPath": "", "startDatepicker": "", "endDatepicker": "",
    }).encode()
    req = urllib.request.Request(f"{BASE}/term/search?mode=search", data=body)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    opener.open(req, timeout=25).read()


def post(opener, path, fields, timeout=25):
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body)
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    return opener.open(req, timeout=timeout).read().decode("utf-8", "replace")


def to_text(raw):
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", htmlmod.unescape(t)).strip()


def grab(text, label):
    m = re.search(re.escape(label) + r"\s*:?\s*(-?\d+)", text, re.I)
    return int(m.group(1)) if m else None


def fetch_crn(opener, term, crn, debug=False):
    raw = post(opener, "/searchResults/getEnrollmentInfo",
               {"term": str(term), "courseReferenceNumber": str(crn)})
    text = to_text(raw)
    if debug:
        print(f"  [debug {crn}] {text[:320]}")

    seats = grab(text, "Enrollment Seats Available")
    cap = grab(text, "Enrollment Maximum")
    actual = grab(text, "Enrollment Actual")
    if seats is None and (cap is None or actual is None):
        return ("error", f"could not parse {crn} -> {text[:160]!r}")
    if seats is None:
        seats = cap - actual

    return {
        "crn": crn, "seats": seats, "cap": cap, "actual": actual,
    }


def course_name(opener, term, crn, debug=False):
    """Best-effort human label, e.g. 'CS 1332 - Data Structures & Algorithms'.

    Banner's class-details HTML varies, so try several shapes. If none hit,
    an explicit --crns 89609:CS-1332 label wins outright.
    """
    try:
        t = to_text(post(opener, "/searchResults/getClassDetails",
                         {"term": str(term), "courseReferenceNumber": str(crn)}, timeout=20))
        if debug:
            print(f"  [debug name {crn}] {t[:400]}")

        subj = re.search(r"Subject\s*:?\s*([A-Za-z &]+?)\s*(?:Course Number|Section|CRN|Campus)", t, re.I)
        num = re.search(r"Course Number\s*:?\s*([0-9A-Z]{3,5})", t, re.I)
        code = re.search(r"\b([A-Z]{2,4})\s*[- ]\s*(\d{4})\b", t)

        title = None
        for pat in (r"Course Title\s*:?\s*(.*?)\s*(?:Subject|CRN|Campus|Associated)",
                    r"Title\s*:?\s*(.*?)\s*(?:Subject|CRN|Campus|Associated)"):
            m = re.search(pat, t, re.I)
            if m and m.group(1).strip():
                title = m.group(1).strip()
                break

        bits = []
        if subj and num:
            bits.append(f"{subj.group(1).strip()} {num.group(1).strip()}")
        elif code:
            bits.append(f"{code.group(1)} {code.group(2)}")
        if title and (not bits or title.lower() != bits[0].lower()):
            bits.append(title)
        if bits:
            return " - ".join(bits)[:70]
    except Exception as e:
        if debug:
            print(f"  [debug name {crn}] lookup failed: {e}")
    return f"CRN {crn}"


def split_labels(items):
    """--crns 89609 89589:MATH-2551 -> (['89609','89589'], {'89589':'MATH 2551'})"""
    crns, manual = [], {}
    for it in items:
        it = it.strip()
        if ":" in it:
            c, lbl = it.split(":", 1)
            c = c.strip()
            crns.append(c)
            if lbl.strip():
                manual[c] = lbl.strip().replace("-", " ")
        else:
            crns.append(it)
    return crns, manual


# ---------------------------------------------------------------- local alarm

def alarm(text):
    for _ in range(6):
        sys.stdout.write("\a"); sys.stdout.flush(); time.sleep(0.25)
    try:
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e",
                f'display notification "{text}" with title "SEAT OPEN" sound name "Sosumi"'],
                check=False, timeout=10)
            subprocess.run(["say", "-r", "220", "seat open. go now."], check=False, timeout=10)
            subprocess.run(["open", REGISTER_URL], check=False, timeout=10)
        elif sys.platform.startswith("linux"):
            subprocess.run(["notify-send", "-u", "critical", "SEAT OPEN", text],
                           check=False, timeout=10)
            subprocess.run(["xdg-open", REGISTER_URL], check=False, timeout=10)
        elif sys.platform.startswith("win"):
            subprocess.run(["cmd", "/c", "start", "", REGISTER_URL], check=False, timeout=10)
    except Exception:
        pass


# ------------------------------------------------------------------- driver

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crns", nargs="+", default=DEFAULT_CRNS)
    ap.add_argument("--term", default=DEFAULT_TERM)
    ap.add_argument("--interval", type=float, default=25.0)
    ap.add_argument("--ntfy", default=None, metavar="TOPIC",
                    help="ntfy.sh topic to push phone alerts to")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--test", action="store_true", help="send a test push and exit")
    ap.add_argument("--duration", type=float, default=None, metavar="SECONDS",
                    help="run for N seconds then exit (the GitHub Action uses this)")
    ap.add_argument("--no-local", action="store_true",
                    help="skip beeps/say/open - for headless runs like CI")
    ap.add_argument("--quiet-start", action="store_true",
                    help="suppress the startup push (else CI pushes every run)")
    args = ap.parse_args()

    if args.test:
        if not args.ntfy:
            print("give me a topic:  --ntfy your-topic --test"); return
        t = normalize_topic(args.ntfy)
        print(f"you passed : {args.ntfy!r}")
        print(f"topic used : {t!r}")
        print(f"full url   : https://ntfy.sh/{t}\n")
        push(args.ntfy, "GT watcher test",
             "If you see this on your phone, it works.",
             priority="high", tags="white_check_mark", verbose=True)
        print("\nIf your phone stayed quiet, check IN THIS ORDER:")
        print(f"  1. ntfy app -> is there a subscription named EXACTLY {t!r}?")
        print("     (case-sensitive, no spaces, no https://, no slashes)")
        print("  2. iPhone Settings -> Notifications -> ntfy -> Allow Notifications ON")
        print(f"  3. open https://ntfy.sh/{t} in a browser - it shows live messages.")
        print("     If the test appears there but not on your phone, it is the app.")
        print("     If it does not appear there either, the topic name differs.")
        return

    interval = max(15.0, args.interval)
    opener = make_opener()
    start_session(opener, args.term)
    born = time.time()

    crns, manual = split_labels(args.crns)
    args.crns = crns
    names = {c: (manual.get(c) or course_name(opener, args.term, c, args.debug))
             for c in crns}

    print(f"v8 | term {args.term} | every ~{interval:.0f}s | "
          f"phone: {normalize_topic(args.ntfy) or 'OFF'}")
    for c in crns:
        src = "(you named it)" if c in manual else ""
        print(f"   {c}  {names[c]}  {src}")
    unresolved = [c for c in crns if names[c] == f"CRN {c}"]
    if unresolved:
        print(f"\n   NOTE: couldn't auto-name {', '.join(unresolved)}. Alerts would just "
              f"say the CRN.\n   Label them yourself so the notification is readable:")
        print(f"     --crns " + " ".join(
            c if c not in unresolved else f"{c}:YOUR-LABEL" for c in crns))
    print("\nCtrl-C to stop.\n")

    if not args.quiet_start:
        push(args.ntfy, "GT watcher started",
             "Watching " + ", ".join(f"{names[c]} ({c})" for c in crns),
             tags="eyes")

    known, fails = set(), 0
    last_ok = time.time()
    warned_dead = False
    deadline = (time.time() + args.duration) if args.duration else None

    while True:
        if time.time() - born > SESSION_MAX_AGE:
            try:
                opener = make_opener(); start_session(opener, args.term); born = time.time()
            except Exception:
                pass

        stamp = datetime.now().strftime("%H:%M:%S")
        parts = []

        for crn in args.crns:
            try:
                info = fetch_crn(opener, args.term, crn, debug=args.debug)
                fails = 0
            except Exception as e:
                fails += 1
                parts.append(f"{crn}:err")
                if fails >= 4:
                    print(f"[{stamp}] repeated failures ({e}) - rebuilding session")
                    try:
                        opener = make_opener(); start_session(opener, args.term)
                        born, fails = time.time(), 0
                    except Exception:
                        time.sleep(15)
                continue

            if isinstance(info, tuple):
                parts.append(f"{crn}:PARSE-FAIL")
                print(f"[{stamp}] !! {info[1]}")
                continue

            last_ok = time.time()
            warned_dead = False

            seats = info["seats"]
            tag = f"{crn}:{seats}"
            if info["cap"] is not None:
                tag += f"({info['actual']}/{info['cap']})"
            parts.append(tag)

            # Real open seats only. Waitlists are not tracked or alerted at all.
            hit = seats > 0
            kind = "SEAT"
            n = seats

            if hit and crn not in known:
                known.add(crn)
                print("\n" + "!" * 70)
                print(f"!!  {n} {kind}(S) OPEN - {names[crn]}  [CRN {crn}]")
                print("!" * 70 + "\n", flush=True)
                if not args.no_local:
                    alarm(f"{names[crn]} - CRN {crn}")
                # Lock-screen readable: course first, CRN second, counts last.
                body = f"CRN {crn}  -  {n} {'seat' if n == 1 else 'seats'} open"
                if info["cap"] is not None:
                    body += f"  ({info['actual']}/{info['cap']} filled)"
                body += "\nRegister NOW - tap to open BuzzPort."
                push(args.ntfy, f"{names[crn]} - {kind} OPEN", body,
                     priority="urgent", tags="rotating_light")
            elif not hit:
                known.discard(crn)

        print(f"[{stamp}] " + "  ".join(parts), flush=True)

        # Silence must not look like success.
        if not warned_dead and time.time() - last_ok > DEAD_AFTER:
            warned_dead = True
            push(args.ntfy, "GT watcher is stuck",
                 "No successful check in 15 min. It may have lost network or GT changed "
                 "something. Go look at the terminal.", priority="high", tags="warning")

        if args.once:
            return
        nap = interval + random.uniform(0, 3)
        if deadline and time.time() + nap >= deadline:
            print(f"[{stamp}] duration reached - exiting cleanly", flush=True)
            return
        time.sleep(nap)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped.")
    except Exception as e:
        # A crash with phone alerts on must announce itself.
        try:
            t = [a.split("=", 1)[-1] for a in sys.argv if a.startswith("--ntfy=")]
            if "--ntfy" in sys.argv:
                t.append(sys.argv[sys.argv.index("--ntfy") + 1])
            if t:
                push(t[-1], "GT watcher CRASHED", f"{type(e).__name__}: {e}",
                     priority="high", tags="skull")
        except Exception:
            pass
        raise
