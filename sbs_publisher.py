"""
sbs_publisher.py — Runs on Side-by-Side PC
Watches Device-Comparison-Report.csv and pushes it to GitHub
automatically whenever it is updated.

Install dependencies:
    pip install watchdog

Usage:
    python sbs_publisher.py
"""

import os
import shutil
import subprocess
import time
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ─── CONFIGURATION ────────────────────────────────────────────────
# Source file path
SOURCE_FILE = r"C:\Users\jesus\OneDrive\Desktop\Automation\oreganqa-automation\results\Device-Comparison-Report.csv"

# Path to the cloned repo
REPO_PATH = r"C:\Users\jesus\Documents\Publisher\Parser"

# Destination inside the repo
DEST_FILE = os.path.join(REPO_PATH, "test_results", "sbs", "Device-Comparison-Report.csv")

# Git branch
GIT_BRANCH = "master"
# ──────────────────────────────────────────────────────────────────


def copy_and_push():
    """Copies the CSV to the repo and pushes to GitHub."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Copy file
    os.makedirs(os.path.dirname(DEST_FILE), exist_ok=True)
    if not os.path.exists(SOURCE_FILE):
        print(f"  [!] Source file not found: {SOURCE_FILE}")
        return

    shutil.copy2(SOURCE_FILE, DEST_FILE)
    print(f"  ✓ Copied: Device-Comparison-Report.csv")

    # Git push
    commit_msg = f"chore: update side-by-side report [{timestamp}]"
    commands = [
        ["git", "-C", REPO_PATH, "pull", "origin", GIT_BRANCH],
        ["git", "-C", REPO_PATH, "add", "test_results/sbs/"],
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


class SBSHandler(FileSystemEventHandler):
    def __init__(self):
        self._last_run = 0

    def on_modified(self, event):
        if event.is_directory:
            return
        if os.path.basename(event.src_path) == "Device-Comparison-Report.csv":
            now = time.time()
            if now - self._last_run < 3:
                return
            self._last_run = now
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Change detected: Device-Comparison-Report.csv")
            time.sleep(2)  # wait for file to finish writing
            copy_and_push()

    on_created = on_modified


if __name__ == "__main__":
    watch_dir = os.path.dirname(SOURCE_FILE)
    os.makedirs(watch_dir, exist_ok=True)
    os.makedirs(os.path.dirname(DEST_FILE), exist_ok=True)

    print("=" * 50)
    print("  Side-by-Side Publisher")
    print(f"  Watching: {SOURCE_FILE}")
    print(f"  Dest:     {DEST_FILE}")
    print(f"  Branch:   {GIT_BRANCH}")
    print("=" * 50)

    # Run once on startup if file exists
    if os.path.exists(SOURCE_FILE):
        print(f"\n[Start] Publishing initial file...")
        copy_and_push()

    handler  = SBSHandler()
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()
    print(f"\nListening for changes... (Ctrl+C to stop)\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nPublisher stopped.")
    observer.join()
