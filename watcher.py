# -*- coding: utf-8 -*-
"""
watcher.py — Detects changes in test result files by client and suite,
generates a JSON per day and keeps 30 days of history.

Expected folder structure:
    test_results/
    ├── telus/
    │   ├── sanity/output.xml
    │   ├── smoke/output.xml
    │   └── sw_version.txt
    ├── mega/
    │   └── sanity/output.xml
    ├── stability/
    │   ├── uiw/ (version.txt, longevity.csv, performance.csv, resource_contention.csv)
    │   └── vip/ (version.txt, longevity.csv, performance.csv, resource_contention.csv)
    ├── sbs/
    │   └── Device-Comparison-Report.csv
    └── memory_leaks/
        ├── Test_Summary_Report_Memory_Monitor_maple_uiw4001.csv
        ├── Test_Summary_Report_Memory_Monitor_maple_vip56x2.csv
        └── Device_Comparison_Report_maple_uiw4001_vs_maple_vip56x2.csv

Install dependencies:
    pip install watchdog

Usage:
    python watcher.py
"""

import json
import os
import re
import time
import csv
import subprocess
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ─── CONFIGURATION ────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
WATCH_FOLDER = os.path.join(BASE_DIR, "test_results")
OUTPUT_DIR   = os.path.join(BASE_DIR, "docs", "history")
LATEST_JSON  = os.path.join(BASE_DIR, "docs", "results.json")
HISTORY_DAYS = 30

CLIENTS = {
    "telus": ["sanity", "smoke"],
    "mega":  ["sanity"],
}

STABILITY_MODELS = ["uiw", "vip"]
STABILITY_FOLDER = os.path.join(WATCH_FOLDER, "stability")
SBS_FILE         = os.path.join(WATCH_FOLDER, "sbs", "Device-Comparison-Report.csv")
MEMORY_LEAKS_DIR = os.path.join(WATCH_FOLDER, "memory_leaks")
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
    if not os.path.exists(filepath):
        return None
    try:
        total = 0
        hangs = 0
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total += 1
                if (row.get("result") or "").strip().upper() == "HANG":
                    hangs += 1
        return {
            "total_iterations": total,
            "hangs":            hangs,
            "success_rate":     round((total - hangs) / total * 100, 1) if total > 0 else 0,
        }
    except Exception as e:
        print(f"  [!] Error parsing longevity.csv: {e}")
        return None


def parse_performance(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        times = []
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    times.append(float(row.get("response_time_sec") or 0))
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
    if not os.path.exists(filepath):
        return None
    try:
        drifts = []
        out_of_baseline = 0
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    drift = float(row.get("drift_pct") or 0)
                    drifts.append(drift)
                    if abs(drift) > drift_threshold:
                        out_of_baseline += 1
                except ValueError:
                    pass
        if not drifts:
            return None
        return {
            "avg_drift_pct":       round(sum(drifts) / len(drifts), 2),
            "max_drift_pct":       round(max(drifts, key=abs), 2),
            "out_of_baseline":     out_of_baseline,
            "total_iterations":    len(drifts),
            "drift_threshold_pct": drift_threshold,
        }
    except Exception as e:
        print(f"  [!] Error parsing resource_contention.csv: {e}")
        return None


def parse_memory_leak_summary(filepath):
    """Parses Test_Summary_Report_Memory_Monitor_*.csv"""
    if not os.path.exists(filepath):
        return None
    try:
        result = {}
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                iteration = (row.get("iteration") or "").strip()
                status    = (row.get("status") or "").strip().upper()
                message   = (row.get("message") or "").strip()
                pct_match = re.search(r'([+-]?\d+\.?\d*)%', message)
                pct = float(pct_match.group(1)) if pct_match else None
                if iteration == "avg":
                    result["avg_growth_pct"] = pct
                    result["avg_status"]     = status
                elif "Latest checkpoint" in message:
                    result["latest_growth_pct"] = pct
                    result["latest_status"]      = status
                elif "Minimum growth" in message:
                    result["min_growth_pct"] = pct
                    result["min_status"]     = status
                elif "Maximum growth" in message:
                    result["max_growth_pct"] = pct
                    result["max_status"]     = status
        return result if result else None
    except Exception as e:
        print(f"  [!] Error parsing memory leak summary {filepath}: {e}")
        return None


def parse_memory_comparison(filepath):
    """Parses Device_Comparison_Report_*.csv"""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            lines = f.readlines()

        result   = {"devices": {}, "table1": [], "table2": [], "verdict": None}
        section  = None
        headers1 = headers2 = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if "Identity" in line:
                device_name = line.replace(" Identity", "").strip()
                section = ("identity", device_name)
                result["devices"][device_name] = {}
                continue
            if "Table 1" in line:
                section = "table1"
                continue
            if "Table 2" in line:
                section = "table2"
                continue
            if "Table 3" in line or "Table 4" in line or "Figure" in line or "Evaluation" in line:
                section = "other"
                continue
            if line.startswith("Verdict"):
                parts = line.split(",", 1)
                result["verdict"] = parts[1].strip() if len(parts) > 1 else ""
                continue

            if isinstance(section, tuple) and section[0] == "identity":
                parts = line.split(",", 1)
                if len(parts) == 2:
                    result["devices"][section[1]][parts[0].strip()] = parts[1].strip()

            elif section == "table1":
                parts = [p.strip() for p in line.split(",")]
                if parts[0] == "Component":
                    headers1 = parts
                elif headers1 and len(parts) >= 7:
                    try:
                        result["table1"].append({
                            "component": parts[0],
                            "uiw_min":   float(parts[1]) if parts[1] else None,
                            "uiw_max":   float(parts[2]) if parts[2] else None,
                            "uiw_avg":   float(parts[3]) if parts[3] else None,
                            "vip_min":   float(parts[4]) if parts[4] else None,
                            "vip_max":   float(parts[5]) if parts[5] else None,
                            "vip_avg":   float(parts[6]) if parts[6] else None,
                        })
                    except ValueError:
                        pass

            elif section == "table2":
                parts = [p.strip() for p in line.split(",")]
                if parts[0] == "Component":
                    headers2 = parts
                elif headers2 and len(parts) >= 4:
                    try:
                        result["table2"].append({
                            "component":  parts[0],
                            "uiw_growth": float(parts[1].replace("+", "")) if parts[1] else None,
                            "vip_growth": float(parts[2].replace("+", "")) if parts[2] else None,
                            "gap":        float(parts[3].replace("+", "")) if parts[3] else None,
                        })
                    except ValueError:
                        pass

        return result if result["table1"] else None
    except Exception as e:
        print(f"  [!] Error parsing memory comparison: {e}")
        return None


def find_memory_leak_files(folder):
    """Finds memory leak CSV files in the folder."""
    if not os.path.exists(folder):
        return None, None, None, None, None
    uiw_summary  = None
    vip_summary  = None
    comparison   = None
    uiw_lxc      = None
    vip_lxc      = None
    for fname in os.listdir(folder):
        fpath = os.path.join(folder, fname)
        if fname.startswith("Test_Summary") and "uiw" in fname.lower():
            uiw_summary = fpath
        elif fname.startswith("Test_Summary") and "vip" in fname.lower():
            vip_summary = fpath
        elif fname.startswith("Device_Comparison"):
            comparison = fpath
        elif fname.startswith("LXC_Memory_Monitor") and "uiw" in fname.lower():
            uiw_lxc = fpath
        elif fname.startswith("LXC_Memory_Monitor") and "vip" in fname.lower():
            vip_lxc = fpath
    return uiw_summary, vip_summary, comparison, uiw_lxc, vip_lxc
    
def parse_lxc_monitor(filepath):
    """Parses LXC_Memory_Monitor_*.csv"""
    if not os.path.exists(filepath):
        return None
    try:
        iterations = []
        times      = []
        totals     = []
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            # First line starts with # so skip it and use as header
            first_line = f.readline().strip().lstrip('#').strip()
            headers    = [h.strip() for h in first_line.split(',')]
            reader     = csv.DictReader(f, fieldnames=headers)
            for row in reader:
                try:
                    iterations.append(int(row.get("Iteration", 0)))
                    times.append((row.get("Time") or "").strip())
                    totals.append(float(row.get("Total (MiB)", 0) or 0))
                except (ValueError, TypeError):
                    pass
        if not iterations:
            return None
        return {
            "iterations": iterations,
            "times":      times,
            "totals":     totals,
        }
    except Exception as e:
        print(f"  [!] Error parsing LXC monitor {filepath}: {e}")
        return None


def parse_sbs_report(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        rows = []
        sw_version_uiw = None
        sw_version_vip = None
        mw_version_uiw = None
        mw_version_vip = None

        with open(filepath, newline="", encoding="utf-8-sig") as f:
            first_line = f.readline().strip()
            if first_line.startswith("Software Version"):
                parts = first_line.split(",")
                for part in parts:
                    part = part.strip()
                    if part.startswith("Software Version - UIW:"):
                        sw_version_uiw = part.replace("Software Version - UIW:", "").strip()
                    elif part.startswith("VIP:") and sw_version_vip is None:
                        sw_version_vip = part.replace("VIP:", "").strip()
                    elif part.startswith("MW Version - UIW:"):
                        mw_version_uiw = part.replace("MW Version - UIW:", "").strip()
                    elif part.startswith("VIP:") and mw_version_vip is None:
                        mw_version_vip = part.replace("VIP:", "").strip()
            else:
                f.seek(0)

            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "test_case":  (row.get("Test Case") or "").strip(),
                    "uiw_result": (row.get("UIW Result") or "").strip(),
                    "uiw_reason": (row.get("UIW Reason") or "").strip(),
                    "uiw_time":   (row.get("UIW Time (s)") or "").strip(),
                    "vip_result": (row.get("VIP Result") or "").strip(),
                    "vip_reason": (row.get("VIP Reason") or "").strip(),
                    "vip_time":   (row.get("VIP Time (s)") or "").strip(),
                    "time_diff":  (row.get("Time Diff (VIP vs UIW)") or "").strip(),
                    "verdict":    (row.get("Verdict") or "").strip(),
                })

        if not rows:
            return None

        total      = len(rows)
        uiw_pass   = sum(1 for r in rows if r["uiw_result"].upper() == "PASS")
        uiw_fail   = sum(1 for r in rows if r["uiw_result"].upper() == "FAIL")
        vip_pass   = sum(1 for r in rows if r["vip_result"].upper() == "PASS")
        vip_fail   = sum(1 for r in rows if r["vip_result"].upper() == "FAIL")
        comparable = sum(1 for r in rows if "NOT COMPARABLE" not in r["verdict"].upper())
        ok         = sum(1 for r in rows if r["verdict"].upper() == "OK")
        warn       = sum(1 for r in rows if "WARN" in r["verdict"].upper())
        vip_faster = sum(1 for r in rows if "NOTE" in r["verdict"].upper() and "FASTER" in r["verdict"].upper())
        not_comp   = sum(1 for r in rows if "NOT COMPARABLE" in r["verdict"].upper())

        return {
            "last_updated":   get_file_mtime(filepath),
            "sw_version_uiw": sw_version_uiw,
            "sw_version_vip": sw_version_vip,
            "mw_version_uiw": mw_version_uiw,
            "mw_version_vip": mw_version_vip,
            "summary": {
                "total": total, "comparable": comparable, "not_comparable": not_comp,
                "uiw_pass": uiw_pass, "uiw_fail": uiw_fail,
                "vip_pass": vip_pass, "vip_fail": vip_fail,
                "ok": ok, "warn": warn, "vip_faster": vip_faster,
            },
            "rows": rows,
        }
    except Exception as e:
        print(f"  [!] Error parsing Device-Comparison-Report.csv: {e}")
        return None


def read_version(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"  [!] Error reading version.txt: {e}")
        return None


def read_telus_sw_version(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        base    = data.get("ZBLD_SW_SID_BASE", "").strip()
        product = data.get("ZBLD_SW_SID_PRODUCT", "").strip()
        ver     = data.get("ZIDS_SWVER", "").strip()
        return f"{base} {product} {ver}".strip()
    except Exception as e:
        print(f"  [!] Error reading sw_version.txt: {e}")
        return None


def parse_stability_model(model):
    model_folder = os.path.join(STABILITY_FOLDER, model)
    return {
        "version":             read_version(os.path.join(model_folder, "version.txt")),
        "longevity":           parse_longevity(os.path.join(model_folder, "longevity.csv")),
        "performance":         parse_performance(os.path.join(model_folder, "performance.csv")),
        "resource_contention": parse_resource_contention(os.path.join(model_folder, "resource_contention.csv")),
        "last_updated": {
            "longevity":           get_file_mtime(os.path.join(model_folder, "longevity.csv")),
            "performance":         get_file_mtime(os.path.join(model_folder, "performance.csv")),
            "resource_contention": get_file_mtime(os.path.join(model_folder, "resource_contention.csv")),
        }
    }


def build_summary(tests):
    total   = len(tests)
    passed  = sum(1 for t in tests if t["status"] == "PASS")
    failed  = sum(1 for t in tests if t["status"] == "FAIL")
    skipped = sum(1 for t in tests if t["status"] == "SKIP")
    return {
        "total": total, "passed": passed, "failed": failed, "skipped": skipped,
        "rate": round((passed / total * 100), 1) if total > 0 else 0,
    }


def get_file_mtime(filepath):
    if os.path.exists(filepath):
        return datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d %H:%M")
    return None


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
            dates.append(fname.replace("results_", "").replace(".json", ""))
    with open(os.path.join(OUTPUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({
            "dates":            dates,
            "clients":          list(CLIENTS.keys()),
            "stability_models": STABILITY_MODELS,
        }, f)


def generate_json():
    all_tests = []

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

    summaries = {}
    for client in CLIENTS:
        client_tests = [t for t in all_tests if t["client"] == client]
        summaries[client] = {"all": build_summary(client_tests)}
        for suite_type in CLIENTS[client]:
            suite_tests = [t for t in client_tests if t["suite_type"] == suite_type]
            summaries[client][suite_type] = build_summary(suite_tests)

    last_run = {}
    for client, suites in CLIENTS.items():
        last_run[client] = {}
        for suite_type in suites:
            xml_path = os.path.join(WATCH_FOLDER, client, suite_type, "output.xml")
            last_run[client][suite_type] = get_file_mtime(xml_path)

    stability = {}
    for model in STABILITY_MODELS:
        stability[model] = parse_stability_model(model)
        version = stability[model].get('version') or 'N/A'
        print(f"  Stability {model.upper()} version:             {version}")
        print(f"  Stability {model.upper()} longevity:           {stability[model]['longevity']}")
        print(f"  Stability {model.upper()} performance:         {stability[model]['performance']}")
        print(f"  Stability {model.upper()} resource_contention: {stability[model]['resource_contention']}")

    sbs = parse_sbs_report(SBS_FILE)
    print(f"  SBS report: {sbs['summary'] if sbs else 'No data'}")

    # Memory leaks
    uiw_path, vip_path, comp_path, uiw_lxc_path, vip_lxc_path = find_memory_leak_files(MEMORY_LEAKS_DIR)
    memory_leaks = {
        "uiw":        parse_memory_leak_summary(uiw_path) if uiw_path else None,
        "vip":        parse_memory_leak_summary(vip_path) if vip_path else None,
        "comparison": parse_memory_comparison(comp_path) if comp_path else None,
        "uiw_lxc":    parse_lxc_monitor(uiw_lxc_path) if uiw_lxc_path else None,
        "vip_lxc":    parse_lxc_monitor(vip_lxc_path) if vip_lxc_path else None,
        "last_updated": {
            "uiw":        get_file_mtime(uiw_path) if uiw_path else None,
            "vip":        get_file_mtime(vip_path) if vip_path else None,
            "comparison": get_file_mtime(comp_path) if comp_path else None,
            "uiw_lxc":    get_file_mtime(uiw_lxc_path) if uiw_lxc_path else None,
            "vip_lxc":    get_file_mtime(vip_lxc_path) if vip_lxc_path else None,
        }
    }
    print(f"  Memory leaks UIW:        {memory_leaks['uiw']}")
    print(f"  Memory leaks VIP:        {memory_leaks['vip']}")
    print(f"  Memory comparison table1: {len(memory_leaks['comparison']['table1']) if memory_leaks['comparison'] else 0} rows")

    telus_sw_version = read_telus_sw_version(
        os.path.join(WATCH_FOLDER, "telus", "sw_version.txt")
    )
    print(f"  Telus SW version: {telus_sw_version}")

    payload = {
        "generated_at":     datetime.now().isoformat(),
        "date":             datetime.now().strftime("%Y-%m-%d"),
        "clients":          list(CLIENTS.keys()),
        "stability_models": STABILITY_MODELS,
        "summary":          build_summary(all_tests),
        "summaries":        summaries,
        "last_run":         last_run,
        "stability":        stability,
        "sbs":              sbs,
        "memory_leaks":     memory_leaks,
        "telus_sw_version": telus_sw_version,
        "tests":            all_tests,
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
    print(f"  [OK] results_{today}.json saved -- {total} tests ({passed} pass / {failed} fail)")

    cleanup_old_files()
    update_index()


def auto_pull():
    while True:
        now    = datetime.now()
        target = now.replace(hour=23, minute=5, second=0, microsecond=0)
        if now >= target:
            target = target.replace(day=target.day + 1)
        time.sleep((target - now).total_seconds())
        try:
            result = subprocess.run(
                ["git", "pull", "origin", "master"],
                capture_output=True, text=True,
                cwd=BASE_DIR
            )
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Auto git pull:")
            print(f"  {result.stdout.strip()}")
            if "Already up to date" not in result.stdout:
                print(f"  New data detected, regenerating JSON...")
                generate_json()
        except Exception as e:
            print(f"  [!] git pull error: {e}")


class ResultsHandler(FileSystemEventHandler):
    def __init__(self):
        self._last_run = 0

    def on_modified(self, event):
        if event.is_directory:
            return
        fname = os.path.basename(event.src_path)
        if fname.endswith(".xml") or fname.endswith(".csv") or fname in ("version.txt", "sw_version.txt"):
            now = time.time()
            if now - self._last_run < 1:
                return
            self._last_run = now
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Change detected: {fname}")
            time.sleep(3)
            generate_json()

    on_created = on_modified


if __name__ == "__main__":
    for client, suites in CLIENTS.items():
        for suite_type in suites:
            os.makedirs(os.path.join(WATCH_FOLDER, client, suite_type), exist_ok=True)
    for model in STABILITY_MODELS:
        os.makedirs(os.path.join(STABILITY_FOLDER, model), exist_ok=True)
    os.makedirs(os.path.join(WATCH_FOLDER, "sbs"), exist_ok=True)
    os.makedirs(MEMORY_LEAKS_DIR, exist_ok=True)

    print("=" * 50)
    print("  QA Dashboard Watcher")
    print(f"  Clients:          {', '.join(CLIENTS.keys())}")
    print(f"  Stability models: {', '.join(m.upper() for m in STABILITY_MODELS)}")
    print(f"  Stability folder: {os.path.abspath(STABILITY_FOLDER)}")
    print(f"  SBS report:       {os.path.abspath(SBS_FILE)}")
    print(f"  Memory leaks:     {os.path.abspath(MEMORY_LEAKS_DIR)}")
    print(f"  History:          {os.path.abspath(OUTPUT_DIR)}")
    print(f"  Retention:        {HISTORY_DAYS} days")
    print("=" * 50)

    print(f"\n[Start] Generating initial results.json...")
    generate_json()

    pull_thread = threading.Thread(target=auto_pull, daemon=True)
    pull_thread.start()
    print("Auto git pull scheduled at 23:05\n")

    handler  = ResultsHandler()
    observer = Observer()
    observer.schedule(handler, WATCH_FOLDER, recursive=True)
    observer.start()
    print(f"Listening for changes... (Ctrl+C to stop)\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nWatcher stopped.")
    observer.join()
