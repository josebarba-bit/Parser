"""
memory_leaks_publisher.py - Runs on this PC
Extracts the memory-leak degradation checkpoints (Stable / LEAK SUSPECTED) from
each model's Test_Summary_Report_Memory_Monitor CSV (STB3 = maple_uiw4001,
STB4 = maple_vip56x2), normalizes them into PASS/FAIL rows, copies them into the
Parser dashboard repo, and pushes to GitHub - triggered every time the source
report CSV actually changes, instead of on a fixed schedule.

A "test" here is one degradation checkpoint (evaluated every 10th iteration):
PASS ("Stable") if growth stayed within the +10% threshold vs. the first-5-
iteration baseline, FAIL ("LEAK SUSPECTED") otherwise - so a genuine memory
leak shows up as a failing test on the dashboard.

Install dependencies:
    pip install watchdog

Usage:
    python memory_leaks_publisher.py
"""

import glob
import os
import csv
import subprocess
import time
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ─── CONFIGURATION ──────────────────────────────────────────────────
# Base TestResults paths for each model
MODELS = {
    "uiw": r"C:\Users\jesus\OneDrive\Escritorio\Automation\oreganqa-automation\ONYX\TELUS\TELUS-STB\TELUS_LONGEVITY_STB3\TestResults",
    "vip": r"C:\Users\jesus\OneDrive\Escritorio\Automation\oreganqa-automation\ONYX\TELUS\TELUS-STB\TELUS_LONGEVITY_STB4\TestResults",
}

# Path to the cloned dashboard repo on this PC
REPO_PATH = r"C:\Users\jesus\OneDrive\Escritorio\Automation\Parser"

# Destination folder inside the repo
MEMORY_LEAKS_DEST = os.path.join(REPO_PATH, "test_results", "memory_leaks")

# Git branch
GIT_BRANCH = "master"

# Minimum seconds between two publishes, so a burst of file-write events
# (e.g. the report being rewritten every iteration) doesn't trigger repeated pushes
DEBOUNCE_SECONDS = 5
# ──────────────────────────────────────────────────────────────────────


def get_today_folder(base_path):
    """Returns today's results folder path."""
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(base_path, today)


def _find_report_csv(today_folder):
    """Finds the device-labeled Test_Summary_Report_Memory_Monitor CSV in today's folder."""
    matches = glob.glob(os.path.join(today_folder, "Test_Summary_Report_Memory_Monitor_*.csv"))
    return max(matches, key=os.path.getmtime) if matches else None


def _extract_checkpoints(report_csv_path):
    """Pulls the rows out of "Table 3: Degradation Checkpoints" in the report CSV."""
    checkpoints = []
    with open(report_csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    in_table = False
    for row in rows:
        if not row:
            if in_table:
                break
            continue
        if row[0].strip().startswith("Table 3: Degradation Checkpoints"):
            in_table = True
            continue
        if not in_table:
            continue
        if row[0].strip() == "Checkpoint (iter #)":
            continue  # header row
        if len(row) < 6:
            continue
        checkpoints.append(row)
    return checkpoints


def _normalize_checkpoints(rows):
    """[iter, baseline, current, delta, growth, status] -> PASS/FAIL with the growth detail as message."""
    out = []
    for row in rows:
        iteration, baseline, current, delta, growth, status = row[:6]
        verdict = "FAIL" if status.strip().upper() == "LEAK SUSPECTED" else "PASS"
        message = f"baseline {baseline} MiB -> current {current} MiB ({growth}% growth)"
        out.append([iteration, verdict, message, ""])
    return out


HEADER = ["iteration", "status", "message", "timestamp"]


def copy_csvs():
    """Extracts and copies today's memory-leak checkpoints for each model into the repo."""
    total_copied = 0

    for model, base_path in MODELS.items():
        today_folder = get_today_folder(base_path)
        dest_folder = os.path.join(MEMORY_LEAKS_DEST, model)

        if not os.path.exists(today_folder):
            print(f"  [!] {model.upper()} folder not found: {today_folder}")
            continue

        report_csv = _find_report_csv(today_folder)
        if not report_csv:
            print(f"  [!] {model.upper()} - No Test_Summary_Report_Memory_Monitor CSV found in {today_folder}")
            continue

        checkpoints = _extract_checkpoints(report_csv)
        if not checkpoints:
            print(f"  [!] {model.upper()} - No degradation checkpoints yet (fewer than 10 iterations completed).")
            continue

        normalized = _normalize_checkpoints(checkpoints)
        os.makedirs(dest_folder, exist_ok=True)
        dst = os.path.join(dest_folder, "memory_leaks.csv")
        with open(dst, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)
            writer.writerows(normalized)

        passed = sum(1 for r in normalized if r[1] == "PASS")
        print(f"  {model.upper()} - Copied: memory_leaks.csv ({len(normalized)} checkpoints, {passed} pass / {len(normalized) - passed} fail)")
        total_copied += 1

    return total_copied > 0


def git_push():
    """Pulls, adds, commits and pushes the CSV files to GitHub."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"chore: update memory leak results [{timestamp}]"

    commands = [
        ["git", "-C", REPO_PATH, "pull", "origin", GIT_BRANCH],
        ["git", "-C", REPO_PATH, "add", "test_results/memory_leaks/"],
        ["git", "-C", REPO_PATH, "commit", "-m", commit_msg],
        ["git", "-C", REPO_PATH, "push", "origin", GIT_BRANCH],
    ]

    for cmd in commands:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                print("  - Nothing new to commit.")
                return
            print(f"  [!] Error in '{' '.join(cmd[2:])}':")
            print(f"      {result.stderr.strip()}")
            return

    print(f"  Published to GitHub: {commit_msg}")


def run_once(reason="startup"):
    """Extract+copy memory-leak checkpoints and publish to GitHub."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ({reason}) Running memory leak publish...")
    if copy_csvs():
        git_push()
    else:
        print("  [!] No CSV files copied, skipping push.")


class ReportChangeHandler(FileSystemEventHandler):
    """Triggers a publish whenever a Test_Summary_Report_Memory_Monitor_*.csv changes."""

    def __init__(self):
        self._last_run = 0

    def _maybe_run(self, event):
        if event.is_directory:
            return
        fname = os.path.basename(event.src_path)
        if not (fname.startswith("Test_Summary_Report_Memory_Monitor_") and fname.endswith(".csv")):
            return
        now = time.time()
        if now - self._last_run < DEBOUNCE_SECONDS:
            return
        self._last_run = now
        run_once(reason=f"change detected: {fname}")

    def on_modified(self, event):
        self._maybe_run(event)

    def on_created(self, event):
        self._maybe_run(event)


if __name__ == "__main__":
    print("=" * 50)
    print("  Memory Leaks Publisher")
    print(f"  Models: {', '.join(m.upper() for m in MODELS.keys())}")
    for model, path in MODELS.items():
        print(f"  {model.upper()}: {path}")
    print(f"  Destination: {MEMORY_LEAKS_DEST}")
    print("=" * 50)

    # Publish once at startup so the dashboard reflects the current state immediately
    run_once(reason="startup")

    handler = ReportChangeHandler()
    observer = Observer()
    watched_any = False
    for model, path in MODELS.items():
        if os.path.exists(path):
            observer.schedule(handler, path, recursive=True)
            watched_any = True
        else:
            print(f"  [!] {model.upper()} - path does not exist yet, not watching: {path}")
    if not watched_any:
        print("  [!] No valid model paths to watch - exiting.")
    else:
        observer.start()
        print("\nWatching for report changes... (Ctrl+C to stop)\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
            print("\nPublisher stopped.")
        observer.join()
