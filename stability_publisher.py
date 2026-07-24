"""
stability_publisher.py — Runs on PC 2
Copies stability CSV files for UIW and VIP models from today's folder
to the repo and pushes to GitHub automatically at 11 PM.

Install dependencies:
    pip install schedule

Usage:
    python stability_publisher.py
"""

import os
import shutil
import subprocess
import schedule
import time
from datetime import datetime

# ─── CONFIGURATION ────────────────────────────────────────────────
# Base paths for each model
MODELS = {
    "uiw": r"C:\Users\Auto-KPI\Desktop\Repos\ONYX\oreganqa-automation\ONYX\MIDDLEWARE_STABILITY\UIW\TestResults",
    "vip": r"C:\Users\Auto-KPI\Desktop\Repos\ONYX1\oreganqa-automation\ONYX\MIDDLEWARE_STABILITY\VIP\TestResults",
}

# Path to the cloned repo on PC 2
REPO_PATH = r"C:\Users\Auto-KPI\Documents\Publisher\Parser"

# Destination folder inside the repo
STABILITY_DEST = os.path.join(REPO_PATH, "test_results", "stability")

# CSV files to copy
CSV_FILES = ["longevity.csv", "performance.csv", "resource_contention.csv"]

# Git branch
GIT_BRANCH = "master"

# Publish time (24h format)
PUBLISH_TIME = "23:00"
# ──────────────────────────────────────────────────────────────────


def get_today_folder(base_path):
    """Returns today's results folder path."""
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(base_path, today)


def copy_csvs():
    """Copies CSV files from today's folder for each model to the repo."""
    total_copied = 0

    for model, base_path in MODELS.items():
        today_folder = get_today_folder(base_path)
        dest_folder  = os.path.join(STABILITY_DEST, model)

        if not os.path.exists(today_folder):
            print(f"  [!] {model.upper()} folder not found: {today_folder}")
            continue

        os.makedirs(dest_folder, exist_ok=True)
        copied = 0
        for fname in CSV_FILES:
            src = os.path.join(today_folder, fname)
            dst = os.path.join(dest_folder, fname)
            if os.path.exists(src):
                shutil.copy2(src, dst)
                print(f"  ✓ {model.upper()} — Copied: {fname}")
                copied += 1
            else:
                print(f"  [!] {model.upper()} — Not found: {fname}")
        total_copied += copied

    return total_copied > 0


def git_push():
    """Adds, commits and pushes CSV files to GitHub."""
    timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"chore: update stability results [{timestamp}]"

    commands = [
        ["git", "-C", REPO_PATH, "pull", "origin", GIT_BRANCH],
        ["git", "-C", REPO_PATH, "add", "test_results/stability/"],
        ["git", "-C", REPO_PATH, "commit", "-m", commit_msg],
        ["git", "-C", REPO_PATH, "push", "origin", GIT_BRANCH],
    ]

    for cmd in commands:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                print(f"  — Nothing new to commit.")
                return
            print(f"  [!] Error in '{' '.join(cmd[2:])}':")
            print(f"      {result.stderr.strip()}")
            return

    print(f"  ✓ Published to GitHub: {commit_msg}")


def run_daily():
    """Main task: copy CSVs and publish to GitHub."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running stability publish...")
    if copy_csvs():
        git_push()
    else:
        print("  [!] No CSV files copied, skipping push.")


if __name__ == "__main__":
    print("=" * 50)
    print("  Stability Publisher — PC 2")
    print(f"  Models: {', '.join(m.upper() for m in MODELS.keys())}")
    for model, path in MODELS.items():
        print(f"  {model.upper()}: {path}")
    print(f"  Destination: {STABILITY_DEST}")
    print(f"  Scheduled: {PUBLISH_TIME} daily")
    print("=" * 50)

    schedule.every().day.at(PUBLISH_TIME).do(run_daily)
    print(f"\nWaiting for {PUBLISH_TIME}... (Ctrl+C to stop)\n")

    # Uncomment to run immediately on startup (for testing)
    run_daily()

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\nPublisher stopped.")
