"""
publisher.py — Publica results.json a GitHub automáticamente
cuando el watcher lo actualiza.

Requiere:
  - Git instalado y configurado (git config user.name / user.email)
  - Repositorio ya creado en GitHub y clonado localmente
  - El dashboard/results.json debe estar dentro del repo

Uso:
    python publisher.py

Ejecutar junto con watcher.py (en otra terminal o en paralelo).
"""

import os
import time
import subprocess
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ─── CONFIGURACIÓN ────────────────────────────────────────────────
# Ruta al archivo que activa el push (generado por watcher.py)
WATCH_FILE = "./docs/results.json"

# Rama de git a usar
GIT_BRANCH = "master"

# Mensaje de commit (se agrega timestamp automáticamente)
COMMIT_MSG_PREFIX = "chore: update test results"
# ──────────────────────────────────────────────────────────────────


def git_push():
    """Hace add + commit + push del results.json."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"{COMMIT_MSG_PREFIX} [{timestamp}]"

    commands = [
        ["git", "add", "./docs/results.json", "./docs/history/"],
        ["git", "commit", "-m", commit_msg],
        ["git", "push", "origin", GIT_BRANCH],
    ]

    for cmd in commands:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # "nothing to commit" no es un error real
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                print(f"  — Sin cambios nuevos para publicar.")
                return
            print(f"  [!] Error en '{' '.join(cmd)}':")
            print(f"      {result.stderr.strip()}")
            return

    print(f"  ✓ Publicado en GitHub: {commit_msg}")


class JsonHandler(FileSystemEventHandler):
    def __init__(self):
        self._last_push = 0

    def on_modified(self, event):
        if event.is_directory:
            return
        if os.path.abspath(event.src_path) == os.path.abspath(WATCH_FILE):
            now = time.time()
            if now - self._last_push < 3:  # debounce 3s
                return
            self._last_push = now
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] results.json actualizado — publicando...")
            git_push()

    on_created = on_modified


if __name__ == "__main__":
    watch_dir = os.path.dirname(os.path.abspath(WATCH_FILE))

    print("=" * 50)
    print("  QA Dashboard Publisher")
    print(f"  Vigilando: {os.path.abspath(WATCH_FILE)}")
    print(f"  Branch:    {GIT_BRANCH}")
    print("=" * 50)
    print("\nEsperando cambios en results.json... (Ctrl+C para detener)\n")

    handler = JsonHandler()
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nPublisher detenido.")
    observer.join()
