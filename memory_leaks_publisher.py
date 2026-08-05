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

It also mirrors the STB3-vs-STB4 comparison CSVs (Device_Comparison_Report_*.csv
and the gathered Test_Summary_Report_Memory_Monitor_*.csv copies) from
oreganqa-automation's Comparisons/<date> folder into the repo - CSV-only, no PNGs -
using the same watch-and-push mechanism.

Install dependencies:
    pip install watchdog

Usage:
    python memory_leaks_publisher.py
"""

import glob
import os
import csv
import shutil
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

# Source folder for the STB3-vs-STB4 comparison CSVs (compare_devices_report.py's output)
COMPARISONS_SRC = r"C:\Users\jesus\OneDrive\Escritorio\Automation\oreganqa-automation\ONYX\TELUS\TELUS-STB\Comparisons"

# Path to the cloned dashboard repo on this PC
REPO_PATH = r"C:\Users\jesus\OneDrive\Escritorio\Automation\Parser"

# Destination folders inside the repo
MEMORY_LEAKS_DEST = os.path.join(REPO_PATH, "test_results", "memory_leaks")
COMPARISONS_DEST = os.path.join(REPO_PATH, "test_results", "comparisons")

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
    """Pulls the fixed-row Table 3 summary (Checkpoints evaluated / Latest / Minimum / Maximum / Average
    growth %) out of the report CSV. Table 3 is a static 5-row summary, not one row per checkpoint, so this
    always returns the same shape regardless of how long the run has been going."""
    summary = {}
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
        if row[0].strip() == "Metric":
            continue  # header row
        if len(row) < 4:
            continue
        summary[row[0].strip()] = row[1:4]
    return summary


def _normalize_checkpoints(summary):
    """Turns the Table 3 summary rows into PASS/FAIL dashboard entries (Latest / Minimum / Maximum / Average)."""
    out = []
    count_row = summary.get("Checkpoints evaluated")
    if not count_row or not count_row[0] or count_row[0] == "0":
        return out  # fewer than 10 iterations completed - no checkpoints yet

    for label in ("Latest checkpoint", "Minimum growth %", "Maximum growth %"):
        row = summary.get(label)
        if not row:
            continue
        iteration, growth, status = row
        verdict = "FAIL" if status.strip().upper() == "LEAK SUSPECTED" else "PASS"
        message = f"{label}: {growth}% growth"
        out.append([iteration, verdict, message, ""])

    avg_row = summary.get("Average growth %")
    if avg_row:
        _, growth, _ = avg_row
        try:
            verdict = "FAIL" if float(growth) > 10 else "PASS"
        except ValueError:
            verdict = "PASS"
        out.append(["avg", verdict, f"Average growth % across all checkpoints: {growth}% growth", ""])

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


def copy_comparisons():
    """Mirrors today's comparison CSVs (Device_Comparison_Report_*.csv and the gathered
    Test_Summary_Report_Memory_Monitor_*.csv copies) into the repo. CSV-only, no PNGs."""
    today = datetime.now().strftime("%Y-%m-%d")
    src_dir = os.path.join(COMPARISONS_SRC, today)

    if not os.path.exists(src_dir):
        print(f"  [!] Comparisons - no folder for today yet: {src_dir}")
        return False

    csv_files = glob.glob(os.path.join(src_dir, "*.csv"))
    if not csv_files:
        print(f"  [!] Comparisons - no CSV files found in {src_dir}")
        return False

    dest_dir = os.path.join(COMPARISONS_DEST, today)
    os.makedirs(dest_dir, exist_ok=True)
    copied = 0
    for src in csv_files:
        dst = os.path.join(dest_dir, os.path.basename(src))
        shutil.copy2(src, dst)
        copied += 1

    print(f"  Comparisons - Copied {copied} CSV file(s) for {today}")
    return copied > 0


def git_push():
    """Pulls, adds, commits and pushes the CSV files to GitHub."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"chore: update memory leak + comparison results [{timestamp}]"

    commands = [
        ["git", "-C", REPO_PATH, "pull", "origin", GIT_BRANCH],
        ["git", "-C", REPO_PATH, "add", "test_results/memory_leaks/", "test_results/comparisons/"],
        ["git", "-C", REPO_PATH, "commit", "-m", commit_msg],
        ["git", "-C", REPO_PATH, "push", "origin", GIT_BRANCH],
    ]

    for cmd in commands:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            combined = f"{result.stdout} {result.stderr}"
            if "nothing to commit" in combined or "no changes added to commit" in combined:
                print("  - Nothing new to commit.")
                return
            print(f"  [!] Error in '{' '.join(cmd[2:])}':")
            print(f"      {result.stdout.strip()}")
            print(f"      {result.stderr.strip()}")
            return

    print(f"  Published to GitHub: {commit_msg}")


def run_once(reason="startup"):
    """Extract+copy memory-leak checkpoints and comparison CSVs, then publish to GitHub."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ({reason}) Running publish...")
    leaks_copied = copy_csvs()
    comparisons_copied = copy_comparisons()
    if leaks_copied or comparisons_copied:
        git_push()
    else:
        print("  [!] No CSV files copied, skipping push.")


class ReportChangeHandler(FileSystemEventHandler):
    """Triggers a publish whenever a Test_Summary_Report_Memory_Monitor_*.csv or
    Device_Comparison_Report_*.csv changes."""

    WATCHED_PREFIXES = ("Test_Summary_Report_Memory_Monitor_", "Device_Comparison_Report_")

    def __init__(self):
        self._last_run = 0

    def _maybe_run(self, event):
        if event.is_directory:
            return
        fname = os.path.basename(event.src_path)
        if not (fname.endswith(".csv") and fname.startswith(self.WATCHED_PREFIXES)):
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
    print("  Memory Leaks + Comparisons Publisher")
    print(f"  Models: {', '.join(m.upper() for m in MODELS.keys())}")
    for model, path in MODELS.items():
        print(f"  {model.upper()}: {path}")
    print(f"  Comparisons source: {COMPARISONS_SRC}")
    print(f"  Destination: {MEMORY_LEAKS_DEST}")
    print(f"  Destination: {COMPARISONS_DEST}")
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
    if os.path.exists(COMPARISONS_SRC):
        observer.schedule(handler, COMPARISONS_SRC, recursive=True)
        watched_any = True
    else:
        print(f"  [!] Comparisons - path does not exist yet, not watching: {COMPARISONS_SRC}")
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
