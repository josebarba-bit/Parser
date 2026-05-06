"""
watcher.py — Detecta cambios en output.xml y archivos .csv
y genera automáticamente results.json para el dashboard.

Instalar dependencias:
    pip install watchdog

Uso:
    python watcher.py

Configura las rutas abajo según tu carpeta compartida.
"""

import json
import os
import time
import csv
import xml.etree.ElementTree as ET
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ─── CONFIGURACIÓN ────────────────────────────────────────────────
# Carpeta donde Robot Framework y Python guardan sus archivos
WATCH_FOLDER = "./test_results"

# Ruta del output.xml de Robot Framework
ROBOT_XML = os.path.join(WATCH_FOLDER, "output.xml")

# Ruta donde se guardará el JSON para el dashboard
OUTPUT_JSON = "./dashboard/results.json"

# Cada cuántos segundos re-chequear aunque no haya eventos (0 = solo por eventos)
POLLING_INTERVAL = 0
# ──────────────────────────────────────────────────────────────────


def parse_robot_xml(filepath):
    """Parsea output.xml de Robot Framework y devuelve lista de tests."""
    tests = []
    if not os.path.exists(filepath):
        return tests
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        for test in root.iter("test"):
            status_el = test.find("status")
            suite = test.find("../..") or test.find("..")
            suite_name = suite.get("name", "—") if suite is not None else "—"
            status = status_el.get("status", "UNKNOWN") if status_el is not None else "UNKNOWN"
            message = (status_el.get("message") or (status_el.text or "")).strip() if status_el is not None else ""
            elapsed = status_el.get("elapsed", "") if status_el is not None else ""
            starttime = status_el.get("starttime", status_el.get("start", "")) if status_el is not None else ""
            tests.append({
                "name": test.get("name", "Sin nombre"),
                "suite": suite_name,
                "status": status,
                "message": message,
                "time": elapsed + "s" if elapsed else starttime,
                "source": "RF",
            })
    except Exception as e:
        print(f"  [!] Error parseando {filepath}: {e}")
    return tests


def parse_csv_file(filepath):
    """Parsea un archivo .csv de pruebas Python y devuelve lista de tests."""
    tests = []
    filename = os.path.basename(filepath)
    try:
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = [h.lower().strip() for h in (reader.fieldnames or [])]

            def find_col(*keys):
                for k in keys:
                    for h in headers:
                        if k in h:
                            return h
                return None

            col_name   = find_col("Status", "Time", "prueba", "caso")
            col_status = find_col("status", "estado", "result", "resultado")
            col_msg    = find_col("message", "msg", "error", "falla", "descripcion")
            col_suite  = find_col("suite", "module", "modulo", "clase", "class", "archivo")
            col_time   = find_col("time", "fecha", "date", "timestamp", "hora")

            for i, row in enumerate(reader, start=1):
                # Normalizar claves a minúsculas
                row_lower = {k.lower().strip(): v for k, v in row.items()}

                raw_status = row_lower.get(col_status, "").upper() if col_status else ""
                if any(x in raw_status for x in ["PASS", "OK", "TRUE", "1", "EXITO", "ÉXITO"]):
                    status = "PASS"
                elif any(x in raw_status for x in ["FAIL", "ERROR", "FALSE", "0", "FALLA"]):
                    status = "FAIL"
                else:
                    # Si no hay columna de status, inferir por mensaje de error
                    msg_val = row_lower.get(col_msg, "").strip() if col_msg else ""
                    status = "FAIL" if msg_val else "PASS"

                tests.append({
                    "name":    row_lower.get(col_name, f"Fila {i}") if col_name else f"Fila {i}",
                    "suite":   row_lower.get(col_suite, filename) if col_suite else filename,
                    "status":  status,
                    "message": row_lower.get(col_msg, "") if col_msg else "",
                    "time":    row_lower.get(col_time, "") if col_time else "",
                    "source":  "CSV",
                })
    except Exception as e:
        print(f"  [!] Error parseando {filepath}: {e}")
    return tests


def generate_json():
    """Lee todos los archivos de resultados y genera results.json."""
    all_tests = []

    # Robot Framework
    rf_tests = parse_robot_xml(ROBOT_XML)
    all_tests.extend(rf_tests)
    print(f"  RF:  {len(rf_tests)} pruebas desde output.xml")

    # CSV files
    csv_count = 0
    if os.path.exists(WATCH_FOLDER):
        for fname in os.listdir(WATCH_FOLDER):
            if fname.endswith(".csv"):
                csv_tests = parse_csv_file(os.path.join(WATCH_FOLDER, fname))
                all_tests.extend(csv_tests)
                csv_count += len(csv_tests)
    print(f"  CSV: {csv_count} pruebas desde archivos .csv")

    # Calcular resumen
    total  = len(all_tests)
    passed = sum(1 for t in all_tests if t["status"] == "PASS")
    failed = sum(1 for t in all_tests if t["status"] == "FAIL")

    payload = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total":  total,
            "passed": passed,
            "failed": failed,
            "rate":   round((passed / total * 100), 1) if total > 0 else 0,
        },
        "tests": all_tests,
    }

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"  ✓ results.json actualizado — {total} pruebas ({passed} pass / {failed} fail)")


class ResultsHandler(FileSystemEventHandler):
    def __init__(self):
        self._last_run = 0

    def on_modified(self, event):
        if event.is_directory:
            return
        fname = os.path.basename(event.src_path)
        if fname.endswith(".xml") or fname.endswith(".csv"):
            # Debounce: esperar 1s para que el archivo termine de escribirse
            now = time.time()
            if now - self._last_run < 1:
                return
            self._last_run = now
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Cambio detectado: {fname}")
            generate_json()

    on_created = on_modified


if __name__ == "__main__":
    os.makedirs(WATCH_FOLDER, exist_ok=True)

    print("=" * 50)
    print("  QA Dashboard Watcher")
    print(f"  Carpeta vigilada: {os.path.abspath(WATCH_FOLDER)}")
    print(f"  JSON de salida:   {os.path.abspath(OUTPUT_JSON)}")
    print("=" * 50)

    # Generar al iniciar
    print(f"\n[Inicio] Generando results.json inicial...")
    generate_json()

    # Iniciar vigilancia
    handler = ResultsHandler()
    observer = Observer()
    observer.schedule(handler, WATCH_FOLDER, recursive=False)
    observer.start()
    print(f"\nEscuchando cambios en '{WATCH_FOLDER}'... (Ctrl+C para detener)\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nWatcher detenido.")
    observer.join()
