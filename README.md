# GT seat watch — runs on GitHub, not your laptop

Watches Georgia Tech's public enrollment endpoint for **open seats** and pushes
your phone when one appears. Runs on GitHub's servers, so your laptop can be
closed, asleep, or out of battery.

Waitlists are not tracked. Real open seats only.

It does **not** register for you. It tells you; you click.

---

## Setup — about 10 minutes, once

### 1. Confirm phone alerts already work

You should already have the **ntfy** app subscribed to your topic. Prove it
still works before building anything on top of it:

```
curl -d "still working" ntfy.sh/gtseat-mahika-9xdvv3d0
```

Phone buzzes? Good. If not, fix that first — everything below depends on it.

### 2. Make the repo

1. Go to [github.com/new](https://github.com/new)
2. Name it `gt-seat-watch`
3. **Public.** This matters: public repos get unlimited free Actions minutes,
   private ones get 2,000/month and this would burn through that in about
   four days. Nothing secret goes in the repo — your topic lives in a secret
   (step 3), and CRNs aren't sensitive.
4. Create it, then **Add file → Upload files** and drag in:
   - `gt_seat_watch.py`
   - the `.github` folder

   If the browser won't take the folder, do it by hand instead:
   **Add file → Create new file**, name it exactly
   `.github/workflows/watch.yml`, and paste that file's contents in.
5. Commit.

### 3. Store your ntfy topic as a secret

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Field | Value |
|---|---|
| Name | `NTFY_TOPIC` |
| Secret | `gtseat-mahika-9xdvv3d0` |

Just the topic — no `https://`, no slashes.

### 4. Turn it on and prove it runs

1. **Actions** tab → click **I understand my workflows, go ahead and enable them**
2. Click **GT seat watch** in the left sidebar → **Run workflow** → **Run workflow**
3. Open the run and watch the log. You want to see your three courses listed by
   name, then status lines every 15 seconds:

   ```
   v8 | term 202608 | every ~15s | phone: gtseat-mahika-9xdvv3d0
      89609  CS 1332 - Data Structures & Algorithms
      89589  MATH 2551 - Multivariable Calculus
      93197  PHYS 2211 - Intro Physics I

   [14:02:11] 89609:0(70/70)  89589:0(70/70)  93197:0(70/70)
   ```

**Check two things in that output:**

- Three *different* course names and numbers. If all three are identical,
  something regressed — that was the bug that took four versions to find.
- Names, not bare `CRN 89609`. If it can't name them, see below.

Once that looks right, you're done. It runs itself every 5 minutes from now on.

---

## Tweaks

All in `.github/workflows/watch.yml`:

**Label the classes yourself** if auto-naming missed (dashes become spaces):

```yaml
--crns 89609:CS-1332 89589:MATH-2551 93197:PHYS-2211 \
```

**Different CRNs or term** — `202608` is Fall 2026, `202702` is Spring 2027:

```yaml
--crns 12345 67890 \
--term 202702 \
```

**Check interval** — 15s is the floor and a sensible one. Going lower means
tens of thousands of requests/day at a university endpoint from shared GitHub
IPs, which is how a client gets blocked. It also wouldn't help: GitHub's
scheduling delay and your own reaction time both dwarf it.

---

## Things worth knowing

**GitHub's scheduler is best-effort.** Free-tier cron is often a few minutes
late, occasionally 15–20 when queues are busy. Each run covers ~4.6 minutes,
so when GitHub is punctual coverage is near-continuous — and when it isn't,
you get gaps no interval setting can close. Run the script on your Mac too
whenever you're at it.

**It nags on purpose.** Each run starts fresh, so a seat that stays open keeps
pushing every run until you take it or it fills.

**A failed run pushes you a warning.** Silence should never be mistaken for
"still full" — that exact bug is why this took eight versions.

**GitHub pauses schedules after 60 days without commits.** Irrelevant for a
registration window; push any commit to wake it if it ever matters.

---

## Deadline

Fall 2026 Phase II registration closes **Friday, August 28, 2026 at 11:59 PM ET.**
After that this repo has nothing left to watch. Drops cluster in the final
hours before a deadline, so Friday evening is the window that matters most.
