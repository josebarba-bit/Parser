"""
stability_publisher.py — Corre en PC 2
Copia los CSV de stability del dia actual a la carpeta del repo
y hace git push a GitHub automaticamente a las 11 PM.

Instalar dependencias:
    pip install schedule

Uso:
    python stability_publisher.py
"""

import os
import shutil
import subprocess
import schedule
import time
from datetime import datetime

# ─── CONFIGURACIÓN ────────────────────────────────────────────────
# Carpeta base donde se generan los CSV con subcarpeta de fecha
BASE_RESULTS = r"C:\Users\Auto-KPI\Desktop\Repos\ONYX\oreganqa-automation\ONYX\MIDDLEWARE_STABILITY\RACK_01\TestResults"

# Ruta del repo clonado en PC 2
REPO_PATH = r"C:\Users\Auto-KPI\Documents\Publisher\Parser"  # ← ajusta esta ruta

# Carpeta destino dentro del repo
STABILITY_DEST = os.path.join(REPO_PATH, "test_results", "stability")

# Archivos a copiar
CSV_FILES = ["longevity.csv", "performance.csv", "resource_contention.csv"]

# Rama de git
GIT_BRANCH = "master"

# Hora de publicación (formato 24h)
PUBLISH_TIME = "23:00"
# ──────────────────────────────────────────────────────────────────


def get_today_folder():
    """Retorna la ruta de la carpeta de hoy."""
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(BASE_RESULTS, today)


def copy_csvs():
    """Copia los CSV del día actual al repo."""
    today_folder = get_today_folder()
    if not os.path.exists(today_folder):
        print(f"  [!] Folder not found: {today_folder}")
        return False

    os.makedirs(STABILITY_DEST, exist_ok=True)
    copied = 0
    for fname in CSV_FILES:
        src = os.path.join(today_folder, fname)
        dst = os.path.join(STABILITY_DEST, fname)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  ✓ Copied: {fname}")
            copied += 1
        else:
            print(f"  [!] Not found: {fname}")

    return copied > 0


def git_push():
    """Hace add + commit + push de los CSV al repo."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    """Tarea principal: copia CSV y publica a GitHub."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running stability publish...")
    if copy_csvs():
        git_push()
    else:
        print("  [!] No CSV files copied, skipping push.")


if __name__ == "__main__":
    print("=" * 50)
    print("  Stability Publisher — PC 2")
    print(f"  Source: {BASE_RESULTS}")
    print(f"  Destination: {STABILITY_DEST}")
    print(f"  Scheduled: {PUBLISH_TIME} daily")
    print("=" * 50)

    # Instalar schedule si no está
    try:
        import schedule
    except ImportError:
        print("Installing schedule...")
        subprocess.run(["pip", "install", "schedule"])
        import schedule

    # Programar tarea diaria
    schedule.every().day.at(PUBLISH_TIME).do(run_daily)
    print(f"\nWaiting for {PUBLISH_TIME}... (Ctrl+C to stop)\n")

    # También correr al iniciar para hacer un push inmediato si se quiere
    run_daily()  # descomentar si quieres que corra al arrancar

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\nPublisher stopped.")
