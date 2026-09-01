# QA Test Dashboard

A web-based dashboard that automatically aggregates and displays QA test results from multiple PCs, clients, and test suites in real time. Hosted on GitHub Pages.

**Live URL:** https://josebarba-bit.github.io/Parser/

---

## Project Structure

```
Parser/
├── watcher.py                  # Monitors test_results/ and generates results.json
├── publisher.py                # Automatically pushes results.json to GitHub
├── stability_publisher.py      # Runs on PC 2 — pushes stability CSVs at 11:00 PM
├── sbs_publisher.py            # Runs on PC 3 — pushes Side-by-Side CSV on change
├── memory_leaks_publisher.py   # Runs on Memory Leaks PC — pushes CSVs on change
├── test_results/
│   ├── telus/
│   │   ├── sanity/output.xml
│   │   ├── smoke/output.xml
│   │   └── sw_version.txt          # JSON with current SW build info
│   ├── mega/
│   │   └── sanity/output.xml
│   ├── stability/
│   │   ├── uiw/
│   │   │   ├── version.txt
│   │   │   ├── longevity.csv
│   │   │   ├── performance.csv
│   │   │   └── resource_contention.csv
│   │   └── vip/
│   │       ├── version.txt
│   │       ├── longevity.csv
│   │       ├── performance.csv
│   │       └── resource_contention.csv
│   ├── sbs/
│   │   └── Device-Comparison-Report.csv
│   └── memory_leaks/
│       ├── Test_Summary_Report_Memory_Monitor_maple_uiw4001.csv
│       ├── Test_Summary_Report_Memory_Monitor_maple_vip56x2.csv
│       ├── Device_Comparison_Report_maple_uiw4001_vs_maple_vip56x2.csv
│       └── LXC_Memory_Monitor_*.csv
└── docs/
    ├── index.html              # Dashboard UI
    ├── results.json            # Generated automatically — do not edit
    └── history/
        ├── index.json
        └── results_YYYY-MM-DD.json   # 30-day history
```

---

## How It Works

| Time | Action |
|------|--------|
| On change | `watcher.py` detects new/updated result files and regenerates `results.json` |
| On change | `publisher.py` detects `results.json` update and pushes to GitHub |
| On change | `sbs_publisher.py` detects SBS CSV change and pushes to GitHub |
| 11:00 PM | `stability_publisher.py` copies stability CSVs and pushes to GitHub |
| 11:05 PM | `watcher.py` auto `git pull` to fetch stability data from PC 2 |
| ~15 sec | Dashboard auto-refreshes to show latest results |

---

## Setup

### Dependencies

```bash
pip install watchdog
```

### PC 1 — Main Orchestrator

1. Clone the repository:
   ```bash
   git clone https://github.com/josebarba-bit/Parser.git
   cd Parser
   ```

2. Configure Git:
   ```bash
   git config user.name "Your Name"
   git config user.email "your@email.com"
   ```

3. Start publisher first, then watcher (order matters):
   ```bash
   # Terminal 1
   python3 publisher.py

   # Terminal 2
   python3 watcher.py
   ```

4. Optionally, add `start_dashboard.bat` to Windows Startup for auto-launch on boot.

### PC 2 — Stability Results

```bash
C:\Users\Auto-KPI\Desktop\Repos\test\Scripts\python.exe stability_publisher.py
```

Runs automatically at 11:00 PM daily. Copies UIW and VIP CSVs to the repo and pushes to GitHub.

### PC 3 — Side-by-Side Results

```bash
python3 sbs_publisher.py
```

Watches `Device-Comparison-Report.csv` for changes and pushes immediately on update.

### Memory Leaks PC

```bash
python3 memory_leaks_publisher.py
```

Watches the memory leaks folder for changes and pushes immediately on update.

---

## Dashboard Sections

### 🤖 Automation
- Clients: Telus (Sanity + Smoke), Mega (Sanity)
- Filters by client and suite
- Pass rate trend — last 7 days
- Full test table with search and status filter
- SW version shown on suite cards (Telus)
- PDF export

### 🔬 Stability

#### 📊 Metrics Tab
- UIW and VIP model cards
- Longevity: iterations, HANGs, success rate
- Performance: avg/max/min response time
- Resource Contention: avg drift %, OOB rate with status (Stable / Acceptable / Concerning / Critical)
- Memory Leaks: growth % per checkpoint
- LXC Memory Monitor chart — Total MiB per iteration
- Memory Comparison tables and charts (UIW vs VIP)
- Stability trend and Memory Leaks trend — last 7 days
- Built-in help modal (?) for metric interpretation

#### ⚡ Side-by-Side Tab
- UIW vs VIP running the same test cases simultaneously
- Verdict per test: OK / WARN / VIP faster / Not Comparable
- SW and MW version shown per device
- Filterable table by test name and verdict
- PDF export

### 📄 PDF Export
All sections support one-click PDF export with Oregan Networks branding. Reports are client-specific — safe to share without exposing other clients' data.

### 📅 History
30-day history with date navigation. Useful for regression analysis and SW build comparisons.

---

## Configuration

| File | Variable | Description |
|------|----------|-------------|
| `watcher.py` | `CLIENTS` | Clients and suites to parse |
| `watcher.py` | `STABILITY_MODELS` | Stability models (uiw, vip) |
| `watcher.py` | `HISTORY_DAYS` | Days of history to keep (default: 30) |
| `publisher.py` | `GIT_BRANCH` | Git branch to push to (default: master) |
| `stability_publisher.py` | `PUBLISH_TIME` | Daily publish time (default: 23:00) |
| `docs/index.html` | `REFRESH_MS` | Dashboard auto-refresh interval in ms (default: 15000) |

---

## Expected CSV Formats

### Automation (Python CSV)
The parser auto-detects columns. Recommended column names:

| Column | Accepted alternatives |
|--------|-----------------------|
| `test_name` | `name`, `prueba`, `caso` |
| `status` | `estado`, `result`, `resultado` |
| `error_message` | `message`, `msg`, `falla`, `error` |
| `module` | `suite`, `clase`, `class`, `archivo` |
| `timestamp` | `time`, `fecha`, `date`, `hora` |

Accepted `status` values: `PASS`, `OK`, `1`, `TRUE` → PASS / `FAIL`, `ERROR`, `0`, `FALSE` → FAIL

### Stability CSVs
- `longevity.csv` — columns: `iteration`, `timestamp`, `uptime_sec`, `command`, `result`, `notes`
- `performance.csv` — columns: `iteration`, `timestamp`, `command`, `response_time_sec`
- `resource_contention.csv` — columns: `iteration`, `timestamp`, `command`, `drift_pct`

### Memory Leaks CSVs
- `Test_Summary_Report_Memory_Monitor_*.csv` — columns: `iteration`, `status`, `message`, `timestamp`
- `LXC_Memory_Monitor_*.csv` — columns: `# Iteration`, `LXC (MiB)`, `kmem (MiB)`, `Malloc (MiB)`, `zids (MiB)`, `cobalt (MiB)`, `Total (MiB)`, `Time`
- `Device_Comparison_Report_*.csv` — custom format parsed by section headers

---

## Built With

- **Python** — `watchdog`, `csv`, `xml.etree.ElementTree`
- **JavaScript** — Chart.js, jsPDF
- **GitHub Pages** — hosting
- **Git** — automated publishing pipeline
