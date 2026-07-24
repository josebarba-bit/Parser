"""
watcher.py — Detecta cambios en archivos de resultados por cliente y suite,
genera JSON por día y mantiene 30 días de historial.
Incluye soporte para pruebas de stability (longevity, performance, resource_contention).

Estructura esperada:
    test_results/
    ├── telus/
    │   ├── sanity/output.xml
    │   └── smoke/output.xml
    ├── mega/
    │   └── sanity/output.xml
    └── stability/
        ├── longevity.csv
        ├── performance.csv
        └── resource_contention.csv

Instalar dependencias:
    pip install watchdog

Uso:
    python watcher.py
"""

import json
import os
import time
import csv
import subprocess
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ─── CONFIGURACIÓN ────────────────────────────────────────────────
WATCH_FOLDER = "./test_results"
OUTPUT_DIR   = "./docs/history"
LATEST_JSON  = "./docs/results.json"
HISTORY_DAYS = 30

CLIENTS = {
    "telus": ["sanity", "smoke"],
    "mega":  ["sanity"],
    # "mega": ["sanity", "smoke"],
}

STABILITY_FOLDER = os.path.join(WATCH_FOLDER, "stability")
# ──────────────────────────────────────────────────────────────────


def parse_robot_xml(filepath, client, suite_type):
    tests = []
    if not os.path.exists(filepath):
        return tests
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        for test in root.iter("test"):
            status_el  = test.find("status")
            suite      = test.find("../..") or test.find("..")
            suite_name = suite.get("name", "—") if suite is not None else "—"
            status     = status_el.get("status", "UNKNOWN") if status_el is not None else "UNKNOWN"
            message    = (status_el.get("message") or (status_el.text or "")).strip() if status_el is not None else ""
            elapsed    = status_el.get("elapsed", "") if status_el is not None else ""
            start      = status_el.get("starttime", status_el.get("start", "")) if status_el is not None else ""
            tests.append({
                "name":       test.get("name", "No name"),
                "suite":      suite_name,
                "status":     status,
                "message":    message,
                "time":       elapsed + "s" if elapsed else start,
                "source":     "RF",
                "client":     client,
                "suite_type": suite_type,
            })
    except Exception as e:
        print(f"  [!] Error parsing {filepath}: {e}")
    return tests


def parse_csv_file(filepath, client, suite_type):
    tests = []
    filename = os.path.basename(filepath)
    try:
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader  = csv.DictReader(f)
            headers = [h.lower().strip() for h in (reader.fieldnames or [])]

            def find_col(*keys):
                for k in keys:
                    for h in headers:
                        if k in h:
                            return h
                return None

            col_name   = find_col("test", "name", "prueba", "caso")
            col_status = find_col("status", "estado", "result", "resultado")
            col_msg    = find_col("message", "msg", "error", "falla", "descripcion")
            col_suite  = find_col("suite", "module", "modulo", "clase", "class", "archivo")
            col_time   = find_col("time", "fecha", "date", "timestamp", "hora")

            for i, row in enumerate(reader, start=1):
                row_lower  = {k.lower().strip(): v for k, v in row.items()}
                raw_status = row_lower.get(col_status, "").upper() if col_status else ""

                if any(x in raw_status for x in ["PASS", "OK", "TRUE", "1", "EXITO", "ÉXITO"]):
                    status = "PASS"
                elif any(x in raw_status for x in ["FAIL", "ERROR", "FALSE", "0", "FALLA"]):
                    status = "FAIL"
                elif "SKIP" in raw_status:
                    status = "SKIP"
                else:
                    msg_val = row_lower.get(col_msg, "").strip() if col_msg else ""
                    status  = "FAIL" if msg_val else "PASS"

                tests.append({
                    "name":       row_lower.get(col_name, f"Row {i}") if col_name else f"Row {i}",
                    "suite":      row_lower.get(col_suite, filename) if col_suite else filename,
                    "status":     status,
                    "message":    row_lower.get(col_msg, "") if col_msg else "",
                    "time":       row_lower.get(col_time, "") if col_time else "",
                    "source":     "CSV",
                    "client":     client,
                    "suite_type": suite_type,
                })
    except Exception as e:
        print(f"  [!] Error parsing {filepath}: {e}")
    return tests


def parse_longevity(filepath):
    """Parsea longevity.csv y extrae métricas."""
    if not os.path.exists(filepath):
        return None
    try:
        total = 0
        hangs = 0
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total += 1
                result = row.get("result", "").strip().upper()
                if result == "HANG":
                    hangs += 1
        success_rate = round((total - hangs) / total * 100, 1) if total > 0 else 0
        return {
            "total_iterations": total,
            "hangs":            hangs,
            "success_rate":     success_rate,
        }
    except Exception as e:
        print(f"  [!] Error parsing longevity.csv: {e}")
        return None


def parse_performance(filepath):
    """Parsea performance.csv y extrae métricas."""
    if not os.path.exists(filepath):
        return None
    try:
        times = []
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    times.append(float(row.get("response_time_sec", 0)))
                except ValueError:
                    pass
        if not times:
            return None
        return {
            "avg_response_time": round(sum(times) / len(times), 2),
            "max_response_time": round(max(times), 2),
            "min_response_time": round(min(times), 2),
            "total_iterations":  len(times),
        }
    except Exception as e:
        print(f"  [!] Error parsing performance.csv: {e}")
        return None


def parse_resource_contention(filepath, drift_threshold=20):
    """Parsea resource_contention.csv y extrae métricas."""
    if not os.path.exists(filepath):
        return None
    try:
        drifts = []
        out_of_baseline = 0
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    drift = float(row.get("drift_pct", 0))
                    drifts.append(drift)
                    if abs(drift) > drift_threshold:
                        out_of_baseline += 1
                except ValueError:
                    pass
        if not drifts:
            return None
        return {
            "avg_drift_pct":      round(sum(drifts) / len(drifts), 2),
            "max_drift_pct":      round(max(drifts, key=abs), 2),
            "out_of_baseline":    out_of_baseline,
            "total_iterations":   len(drifts),
            "drift_threshold_pct": drift_threshold,
        }
    except Exception as e:
        print(f"  [!] Error parsing resource_contention.csv: {e}")
        return None


def build_summary(tests):
    total   = len(tests)
    passed  = sum(1 for t in tests if t["status"] == "PASS")
    failed  = sum(1 for t in tests if t["status"] == "FAIL")
    skipped = sum(1 for t in tests if t["status"] == "SKIP")
    return {
        "total":   total,
        "passed":  passed,
        "failed":  failed,
        "skipped": skipped,
        "rate":    round((passed / total * 100), 1) if total > 0 else 0,
    }


def cleanup_old_files():
    if not os.path.exists(OUTPUT_DIR):
        return
    cutoff  = datetime.now() - timedelta(days=HISTORY_DAYS)
    removed = 0
    for fname in os.listdir(OUTPUT_DIR):
        if not fname.startswith("results_") or not fname.endswith(".json"):
            continue
        try:
            date_str  = fname.replace("results_", "").replace(".json", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                os.remove(os.path.join(OUTPUT_DIR, fname))
                removed += 1
        except ValueError:
            pass
    if removed:
        print(f"  🗑  Removed {removed} old history file(s) (>{HISTORY_DAYS} days)")


def update_index():
    if not os.path.exists(OUTPUT_DIR):
        return
    dates = []
    for fname in sorted(os.listdir(OUTPUT_DIR), reverse=True):
        if fname.startswith("results_") and fname.endswith(".json"):
            date_str = fname.replace("results_", "").replace(".json", "")
            dates.append(date_str)
    with open(os.path.join(OUTPUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"dates": dates, "clients": list(CLIENTS.keys())}, f)


def get_file_mtime(filepath):
    if os.path.exists(filepath):
        return datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d %H:%M")
    return None


def generate_json():
    all_tests = []

    # Pruebas por cliente
    for client, suites in CLIENTS.items():
        for suite_type in suites:
            xml_path = os.path.join(WATCH_FOLDER, client, suite_type, "output.xml")
            tests    = parse_robot_xml(xml_path, client, suite_type)
            all_tests.extend(tests)
            print(f"  {client.capitalize()} {suite_type}: {len(tests)} tests from RF")

        client_folder = os.path.join(WATCH_FOLDER, client)
        if os.path.exists(client_folder):
            for fname in os.listdir(client_folder):
                if fname.endswith(".csv"):
                    csv_tests = parse_csv_file(os.path.join(client_folder, fname), client, "sanity")
                    all_tests.extend(csv_tests)

    # Summaries por cliente y suite
    summaries = {}
    for client in CLIENTS:
        client_tests = [t for t in all_tests if t["client"] == client]
        summaries[client] = {"all": build_summary(client_tests)}
        for suite_type in CLIENTS[client]:
            suite_tests = [t for t in client_tests if t["suite_type"] == suite_type]
            summaries[client][suite_type] = build_summary(suite_tests)

    # Last run por cliente y suite
    last_run = {}
    for client, suites in CLIENTS.items():
        last_run[client] = {}
        for suite_type in suites:
            xml_path = os.path.join(WATCH_FOLDER, client, suite_type, "output.xml")
            last_run[client][suite_type] = get_file_mtime(xml_path)

    # Stability metrics
    longevity_path    = os.path.join(STABILITY_FOLDER, "longevity.csv")
    performance_path  = os.path.join(STABILITY_FOLDER, "performance.csv")
    contention_path   = os.path.join(STABILITY_FOLDER, "resource_contention.csv")

    stability = {
        "longevity":            parse_longevity(longevity_path),
        "performance":          parse_performance(performance_path),
        "resource_contention":  parse_resource_contention(contention_path),
        "last_updated": {
            "longevity":           get_file_mtime(longevity_path),
            "performance":         get_file_mtime(performance_path),
            "resource_contention": get_file_mtime(contention_path),
        }
    }

    print(f"  Stability longevity:           {stability['longevity']}")
    print(f"  Stability performance:         {stability['performance']}")
    print(f"  Stability resource_contention: {stability['resource_contention']}")

    payload = {
        "generated_at": datetime.now().isoformat(),
        "date":         datetime.now().strftime("%Y-%m-%d"),
        "clients":      list(CLIENTS.keys()),
        "summary":      build_summary(all_tests),
        "summaries":    summaries,
        "last_run":     last_run,
        "stability":    stability,
        "tests":        all_tests,
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today      = datetime.now().strftime("%Y-%m-%d")
    daily_path = os.path.join(OUTPUT_DIR, f"results_{today}.json")
    with open(daily_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    os.makedirs(os.path.dirname(LATEST_JSON), exist_ok=True)
    with open(LATEST_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    total  = payload["summary"]["total"]
    passed = payload["summary"]["passed"]
    failed = payload["summary"]["failed"]
    print(f"  ✓ results_{today}.json saved — {total} tests ({passed} pass / {failed} fail)")

    cleanup_old_files()
    update_index()


class ResultsHandler(FileSystemEventHandler):
    def __init__(self):
        self._last_run = 0

    def on_modified(self, event):
        if event.is_directory:
            return
        fname = os.path.basename(event.src_path)
        if fname.endswith(".xml") or fname.endswith(".csv"):
            now = time.time()
            if now - self._last_run < 1:
                return
            self._last_run = now
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Change detected: {fname}")
            time.sleep(3)
            generate_json()

    on_created = on_modified
    
def auto_pull():
    """Hace git pull a las 11:05 PM para traer CSV de stability de PC2."""
    while True:
        now = datetime.now()
        target = now.replace(hour=23, minute=5, second=0, microsecond=0)
        if now >= target:
            target = target.replace(day=target.day + 1)
        wait_seconds = (target - now).total_seconds()
        time.sleep(wait_seconds)
        try:
            result = subprocess.run(
                ["git", "pull", "origin", "master"],
                capture_output=True, text=True,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Auto git pull:")
            print(f"  {result.stdout.strip()}")
            if "Already up to date" not in result.stdout:
                print(f"  New stability data detected, regenerating JSON...")
                generate_json()
        except Exception as e:
            print(f"  [!] git pull error: {e}")


if __name__ == "__main__":
    for client, suites in CLIENTS.items():
        for suite_type in suites:
            os.makedirs(os.path.join(WATCH_FOLDER, client, suite_type), exist_ok=True)
    os.makedirs(STABILITY_FOLDER, exist_ok=True)

    print("=" * 50)
    print("  QA Dashboard Watcher")
    print(f"  Clients:   {', '.join(CLIENTS.keys())}")
    print(f"  Stability: {os.path.abspath(STABILITY_FOLDER)}")
    print(f"  History:   {os.path.abspath(OUTPUT_DIR)}")
    print(f"  Retention: {HISTORY_DAYS} days")
    print("=" * 50)

    print(f"\n[Start] Generating initial results.json...")
    generate_json()

    handler  = ResultsHandler()
    observer = Observer()
    observer.schedule(handler, WATCH_FOLDER, recursive=True)
    pull_thread = threading.Thread(target=auto_pull, daemon=True)
    pull_thread.start()
    print("Auto git pull scheduled at 23:05 for stability CSV\n")
    observer.start()
    print(f"\nListening for changes... (Ctrl+C to stop)\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nWatcher stopped.")
    observer.join()
