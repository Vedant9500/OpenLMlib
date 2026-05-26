#!/usr/bin/env python3
"""
OpenLMlib Benchmark Report Generator
Parses all benchmark JSON files in results/ and generates a single standalone HTML report
matching the classic, clean Windows Diagnostic (Battery Report) styling.
Uses offline-compatible native SVG for timeline graphing, eliminating CDN script dependencies.
Refined filtering logic to sync sidebar checklist changes immediately with graph rendering.
"""

import os
import re
import json
import glob
import datetime
import platform


def load_report_config(results_dir="results"):
    config_path = os.path.join(results_dir, "benchmark_report_config.json")
    default_config = {
        "exclude_files": [],
        "exclude_comparisons": [],
        "comparison_metric": "mean_ms",
    }
    if not os.path.exists(config_path):
        return default_config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception as e:
        print(f"Warning: Failed to parse {config_path}: {e}")
        return default_config

    if not isinstance(loaded, dict):
        print(f"Warning: {config_path} must contain a JSON object.")
        return default_config

    config = dict(default_config)
    config.update(loaded)
    if not isinstance(config.get("exclude_files"), list):
        config["exclude_files"] = []
    if not isinstance(config.get("exclude_comparisons"), list):
        config["exclude_comparisons"] = []
    return config


def get_benchmark_files(results_dir="results", report_config=None):
    pattern = os.path.join(results_dir, "benchmark_*.json")
    files = glob.glob(pattern)
    excluded = set(report_config.get("exclude_files", [])) if report_config else set()
    files = [
        f for f in files
        if re.fullmatch(r"benchmark_\d{8}_\d{6}\.json", os.path.basename(f))
        and os.path.basename(f) not in excluded
    ]
    # Sort files chronologically based on filename timestamp
    def extract_time(fpath):
        fname = os.path.basename(fpath)
        match = re.search(r"benchmark_(\d{8}_\d{6})", fname)
        if match:
            try:
                return datetime.datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
            except ValueError:
                pass
        return datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
    
    files.sort(key=extract_time)
    return files

def parse_benchmark_data(files):
    runs = []
    
    for idx, filepath in enumerate(files):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Extract timestamp
            timestamp_str = data.get("timestamp")
            if timestamp_str:
                try:
                    dt = datetime.datetime.fromisoformat(timestamp_str)
                    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    formatted_time = timestamp_str
            else:
                fname = os.path.basename(filepath)
                match = re.search(r"benchmark_(\d{8}_\d{6})", fname)
                if match:
                    dt = datetime.datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
                    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    formatted_time = f"Run {idx + 1}"
            
            runs.append({
                "filepath": filepath,
                "filename": os.path.basename(filepath),
                "timestamp": formatted_time,
                "config": data.get("config", {}),
                "environment": data.get("environment", {}),
                "results": data.get("results", [])
            })
        except Exception as e:
            print(f"Warning: Failed to parse {filepath}: {e}")
            
    return runs

def process_metrics(runs):
    if not runs:
        return {}
    
    tool_metrics = {}
    all_runs_timestamps = [run["timestamp"] for run in runs]
    
    for run in runs:
        ts = run["timestamp"]
        for res in run["results"]:
            tool = res.get("tool")
            mode = res.get("mode", "warm")
            if not tool:
                continue
                
            if tool not in tool_metrics:
                tool_metrics[tool] = {"warm": {}, "cold": {}}
            
            tool_metrics[tool][mode][ts] = {
                "mean_ms": res.get("mean_ms", 0.0),
                "median_ms": res.get("median_ms", 0.0),
                "p95_ms": res.get("p95_ms", 0.0),
                "p99_ms": res.get("p99_ms", 0.0),
                "min_ms": res.get("min_ms", 0.0),
                "max_ms": res.get("max_ms", 0.0),
                "success_rate": float(res.get("success_rate", "100.0%").replace("%", "")),
                "errors": res.get("errors", 0),
                "iterations": res.get("iterations", 0)
            }
            
    structured_data = {}
    for tool, modes in tool_metrics.items():
        structured_data[tool] = {}
        for mode, run_data in modes.items():
            if not run_data:
                continue
                
            structured_data[tool][mode] = {
                "mean_ms": [run_data.get(ts, {}).get("mean_ms", None) for ts in all_runs_timestamps],
                "median_ms": [run_data.get(ts, {}).get("median_ms", None) for ts in all_runs_timestamps],
                "p95_ms": [run_data.get(ts, {}).get("p95_ms", None) for ts in all_runs_timestamps],
                "p99_ms": [run_data.get(ts, {}).get("p99_ms", None) for ts in all_runs_timestamps],
                "min_ms": [run_data.get(ts, {}).get("min_ms", None) for ts in all_runs_timestamps],
                "max_ms": [run_data.get(ts, {}).get("max_ms", None) for ts in all_runs_timestamps],
                "success_rate": [run_data.get(ts, {}).get("success_rate", None) for ts in all_runs_timestamps],
                "errors": [run_data.get(ts, {}).get("errors", None) for ts in all_runs_timestamps],
            }
            
    return {
        "runs": all_runs_timestamps,
        "run_details": [
            {
                "timestamp": run["timestamp"],
                "filename": run["filename"],
                "config": run.get("config", {}),
                "environment": run.get("environment", {}),
            }
            for run in runs
        ],
        "tools": structured_data
    }

def _build_excluded_comparison_map(report_config):
    excluded = {}
    for item in report_config.get("exclude_comparisons", []):
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        mode = item.get("mode")
        if not tool or not mode:
            continue
        excluded[(tool, mode)] = item.get("reason", "")
    return excluded


def generate_comparison_summary(processed_data, report_config=None):
    runs = processed_data.get("runs", [])
    tools = processed_data.get("tools", {})
    report_config = report_config or {}
    excluded_map = _build_excluded_comparison_map(report_config)
    comparison_metric = report_config.get("comparison_metric", "mean_ms")
    
    if len(runs) < 2:
        return {
            "improvements": [],
            "regressions": [],
            "overall_warm_change_pct": 0.0,
            "overall_cold_change_pct": 0.0,
            "excluded_comparisons": [],
        }
        
    first_run = runs[0]
    last_run = runs[-1]
    
    comparisons = []
    
    for tool, modes in tools.items():
        for mode, metrics in modes.items():
            excluded_reason = excluded_map.get((tool, mode))
            if excluded_reason is not None:
                continue
            series = metrics.get(comparison_metric) or metrics.get("mean_ms") or []
            if not series:
                continue
            first_val = series[0]
            last_val = series[-1]
            
            if first_val is None or last_val is None:
                continue
                
            if first_val == 0:
                pct_change = 0.0
            else:
                pct_change = ((last_val - first_val) / first_val) * 100.0
                
            diff = last_val - first_val
            
            comparisons.append({
                "tool": tool,
                "mode": mode,
                "first_val": first_val,
                "last_val": last_val,
                "diff": diff,
                "pct_change": pct_change
            })
            
    improvements = [c for c in comparisons if c["pct_change"] < -1.0]
    improvements.sort(key=lambda x: x["pct_change"])
    
    regressions = [c for c in comparisons if c["pct_change"] > 1.0]
    regressions.sort(key=lambda x: x["pct_change"], reverse=True)
    
    warm_first_total = 0.0
    warm_last_total = 0.0
    warm_count = 0
    
    cold_first_total = 0.0
    cold_last_total = 0.0
    cold_count = 0
    
    for c in comparisons:
        if c["mode"] == "warm":
            warm_first_total += c["first_val"]
            warm_last_total += c["last_val"]
            warm_count += 1
        elif c["mode"] == "cold":
            cold_first_total += c["first_val"]
            cold_last_total += c["last_val"]
            cold_count += 1
            
    overall_warm_change = 0.0
    if warm_count > 0 and warm_first_total > 0:
        overall_warm_change = ((warm_last_total - warm_first_total) / warm_first_total) * 100.0
        
    overall_cold_change = 0.0
    if cold_count > 0 and cold_first_total > 0:
        overall_cold_change = ((cold_last_total - cold_first_total) / cold_first_total) * 100.0
        
    return {
        "improvements": improvements[:10],
        "regressions": regressions[:10],
        "overall_warm_change_pct": overall_warm_change,
        "overall_cold_change_pct": overall_cold_change,
        "all_comparisons": comparisons,
        "excluded_comparisons": [
            {"tool": tool, "mode": mode, "reason": reason}
            for (tool, mode), reason in sorted(excluded_map.items())
        ],
        "comparison_window": {
            "first_run": first_run,
            "last_run": last_run,
        },
        "comparison_metric": comparison_metric,
    }


def write_llm_json_report(processed_data, comparison_summary, output_path, report_config=None):
    payload = {
        "report_type": "openlmlib_benchmark_llm_summary",
        "generated_at": datetime.datetime.now().isoformat(),
        "included_runs": processed_data.get("runs", []),
        "run_details": processed_data.get("run_details", []),
        "excluded_files": (report_config or {}).get("exclude_files", []),
        "comparison_metric": comparison_summary.get("comparison_metric", "mean_ms"),
        "comparison_window": comparison_summary.get("comparison_window", {}),
        "overall_warm_change_pct": comparison_summary.get("overall_warm_change_pct", 0.0),
        "overall_cold_change_pct": comparison_summary.get("overall_cold_change_pct", 0.0),
        "top_improvements": comparison_summary.get("improvements", []),
        "top_regressions": comparison_summary.get("regressions", []),
        "excluded_comparisons": comparison_summary.get("excluded_comparisons", []),
        "all_comparisons": comparison_summary.get("all_comparisons", []),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def write_markdown_report(processed_data, comparison_summary, output_path, report_config=None):
    runs = processed_data.get("runs", [])
    window = comparison_summary.get("comparison_window", {})

    lines = []
    lines.append("# OpenLMlib Benchmark Summary")
    lines.append("")
    lines.append(f"- Included runs: {len(runs)}")
    if window:
        lines.append(
            f"- Comparison window: {window.get('first_run', 'N/A')} -> {window.get('last_run', 'N/A')}"
        )
    lines.append(
        f"- Comparison metric: {comparison_summary.get('comparison_metric', 'mean_ms')}"
    )
    excluded_files = (report_config or {}).get("exclude_files", [])
    if excluded_files:
        lines.append("- Excluded files: " + ", ".join(excluded_files))
    lines.append(
        f"- Overall warm change: {comparison_summary.get('overall_warm_change_pct', 0.0):+.1f}%"
    )
    lines.append(
        f"- Overall cold change: {comparison_summary.get('overall_cold_change_pct', 0.0):+.1f}%"
    )
    lines.append("")

    run_details = processed_data.get("run_details", [])
    if run_details:
        lines.append("## Runs")
        lines.append("")
        for run in run_details:
            cfg = run.get("config", {})
            env = run.get("environment", {})
            commit = env.get("commit") or "unknown"
            lines.append(
                f"- `{run.get('timestamp', 'N/A')}`: warm={cfg.get('iterations', '?')}, cold={cfg.get('cold_iterations', '?')}, warmup={cfg.get('warmup', '?')}, commit={commit}"
            )
        lines.append("")

    excluded_comparisons = comparison_summary.get("excluded_comparisons", [])
    if excluded_comparisons:
        lines.append("## Excluded Comparisons")
        lines.append("")
        for item in excluded_comparisons:
            lines.append(
                f"- `{item['tool']}` ({item['mode']}): {item.get('reason', 'excluded')}"
            )
        lines.append("")

    lines.append("## Top Improvements")
    lines.append("")
    for item in comparison_summary.get("improvements", []):
        lines.append(
            f"- `{item['tool']}` ({item['mode']}): {item['first_val']:.2f}ms -> {item['last_val']:.2f}ms ({item['pct_change']:+.1f}%)"
        )
    if not comparison_summary.get("improvements"):
        lines.append("- None")
    lines.append("")

    lines.append("## Top Regressions")
    lines.append("")
    for item in comparison_summary.get("regressions", []):
        lines.append(
            f"- `{item['tool']}` ({item['mode']}): {item['first_val']:.2f}ms -> {item['last_val']:.2f}ms ({item['pct_change']:+.1f}%)"
        )
    if not comparison_summary.get("regressions"):
        lines.append("- None")
    lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def build_html_report(processed_data, comparison_summary, output_path):
    import json
    data_json = json.dumps(processed_data)
    summary_json = json.dumps(comparison_summary)
    
    # Library and Configuration Metadata
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    try:
        import openlmlib
        from openlmlib.settings import resolve_hybrid_settings_path, load_settings
        
        openlmlib_version = getattr(openlmlib, "__version__", "Unknown")
        settings_path = resolve_hybrid_settings_path()
        settings = load_settings(settings_path)
        
        embedding_model = settings.embedding_model
        rerank_enabled = settings.phase4.reranking.enabled
        rerank_model = settings.phase4.reranking.model_name if rerank_enabled else "Disabled"
        db_file = os.path.basename(settings.db_path)
    except Exception:
        openlmlib_version = "Unknown"
        embedding_model = "Unknown"
        rerank_model = "Unknown"
        db_file = "Unknown"
        
    python_version = platform.python_version()
    report_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    runs_count = len(processed_data["runs"])
    
    html_content = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
    <title>OpenLMlib Benchmark report</title>
    <style type="text/css">
        body {{
            font-family: Segoe UI Light, Segoe UI, Tahoma, Arial;
            letter-spacing: 0.02em;
            background-color: #181818;
            color: #F0F0F0;
            margin-left: 5.5em;
            margin-right: 5.5em;
            padding-bottom: 6em;
        }}

        h1 {{
            color: #11D8E8;
            font-size: 42pt;
            font-weight: 300;
            margin-top: 1em;
            margin-bottom: 0.5em;
        }}

        h2 {{
            font-size: 15pt;
            color: #11EEF4;
            margin-top: 4em;
            margin-bottom: 0.2em;
            letter-spacing: 0.08em;
            font-weight: 400;
        }}

        .explanation {{
            color: #777777;
            font-size: 12pt;
            margin-bottom: 1.5rem;
        }}

        table {{
            border-width: 0;
            border-collapse: collapse;
            table-layout: fixed;
            font-family: Segoe UI Light, Segoe UI;
            letter-spacing: 0.02em;
            background-color: #181818;
            color: #f0f0f0;
            margin-bottom: 2em;
        }}

        td {{
            padding: 0.4em 0.8em;
            vertical-align: middle;
        }}

        .even {{ background: #272727; }}
        .odd {{ background: #1E1E1E; }}

        thead {{
            font-family: Segoe UI Semibold;
            font-size: 85%;
            color: #BCBCBC;
            text-align: left;
        }}

        thead th {{
            padding: 0.5em 0.8em;
            border-bottom: 1px solid #555555;
            font-weight: 600;
        }}

        .label {{
            font-family: Segoe UI Semibold;
            font-size: 85%;
            color: #BCBCBC;
        }}

        .numeric-cell {{
            font-family: Segoe UI Symbol, monospace;
            text-align: right;
        }}

        .badge-improvement {{
            color: #11EEF4;
            font-family: Segoe UI Semibold;
        }}

        .badge-regression {{
            color: #B82830;
            font-family: Segoe UI Semibold;
        }}

        .badge-neutral {{
            color: #888888;
        }}

        /* Controls Panel styled to match Windows Diagnostic Settings */
        .controls-row {{
            display: flex;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
            align-items: flex-end;
        }}

        .control-group {{
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
        }}

        .control-label {{
            font-family: Segoe UI Semibold;
            font-size: 85%;
            color: #BCBCBC;
            text-transform: uppercase;
        }}

        select, input[type="text"] {{
            background-color: #272727;
            color: #F0F0F0;
            border: 1px solid #555555;
            font-family: Segoe UI Light;
            font-size: 11pt;
            padding: 4px 8px;
            min-width: 180px;
            outline: none;
        }}

        select:focus, input[type="text"]:focus {{
            border-color: #11D8E8;
        }}

        .checkbox-container {{
            background-color: #1E1E1E;
            border: 1px solid #333333;
            padding: 8px;
            max-height: 220px;
            overflow-y: auto;
            width: 320px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}

        .checkbox-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-family: Segoe UI Light;
            font-size: 10pt;
            color: #F0F0F0;
            cursor: pointer;
            user-select: none;
            padding: 2px 4px;
        }}

        .checkbox-item:hover {{
            background: #272727;
        }}

        .checkbox-item input {{
            accent-color: #11D8E8;
            cursor: pointer;
        }}

        .tool-mode-tag {{
            font-family: Segoe UI Semibold;
            font-size: 80%;
            padding: 1px 4px;
            border-radius: 2px;
            margin-left: auto;
        }}

        .tag-warm {{
            color: #eb9036;
            background-color: rgba(235, 144, 54, 0.1);
            border: 1px solid rgba(235, 144, 54, 0.2);
        }}

        .tag-cold {{
            color: #4faef7;
            background-color: rgba(54, 162, 235, 0.1);
            border: 1px solid rgba(54, 162, 235, 0.2);
        }}

        /* Timeline Graph Wrapper */
        .graph-section {{
            display: grid;
            grid-template-columns: 340px 1fr;
            gap: 2rem;
            margin-top: 1em;
            margin-bottom: 2em;
        }}

        @media (max-width: 900px) {{
            .graph-section {{
                grid-template-columns: 1fr;
            }}
        }}

        .chart-box {{
            background-color: #181818;
            border: 1px solid #333333;
            padding: 1em;
            height: 480px;
            position: relative;
        }}

        .chart-wrapper {{
            position: relative;
            width: 100%;
            height: 100%;
        }}

        /* Table scroll limits */
        .table-scroll-container {{
            max-height: 550px;
            overflow-y: auto;
            border: 1px solid #333333;
        }}

        .table-scroll-container th {{
            position: sticky;
            top: 0;
            z-index: 10;
            background-color: #1E1E1E;
        }}

        .quick-btn-row {{
            display: flex;
            gap: 6px;
            margin-top: 6px;
        }}

        .btn-action {{
            background: #272727;
            border: 1px solid #555555;
            color: #BCBCBC;
            font-family: Segoe UI Light;
            font-size: 85%;
            padding: 2px 6px;
            cursor: pointer;
        }}

        .btn-action:hover {{
            background: #333333;
            color: #F0F0F0;
            border-color: #777777;
        }}

        .summary-pill-container {{
            display: flex;
            gap: 2rem;
            margin-bottom: 2rem;
            flex-wrap: wrap;
        }}

        .summary-pill {{
            border-left: 3px solid #777777;
            padding-left: 0.8em;
        }}

        .summary-pill.improved {{
            border-color: #11EEF4;
        }}

        .summary-pill.regressed {{
            border-color: #B82830;
        }}

        .summary-pill-title {{
            font-size: 9pt;
            color: #777777;
            text-transform: uppercase;
        }}

        .summary-pill-value {{
            font-size: 20pt;
            color: #F0F0F0;
        }}
    </style>
</head>
<body>
    <h1>OpenLMlib Benchmark Report</h1>
    
    <!-- Metadata Table -->
    <table style="margin-bottom: 4em;">
        <colgroup>
            <col style="width: 20em;" />
            <col style="width: 35em;" />
        </colgroup>
        <tr>
            <td class="label">OPENLMLIB VERSION</td>
            <td>{openlmlib_version}</td>
        </tr>
        <tr>
            <td class="label">EMBEDDING MODEL</td>
            <td style="font-family: monospace; font-size: 95%;">{embedding_model}</td>
        </tr>
        <tr>
            <td class="label">RERANKING MODEL</td>
            <td style="font-family: monospace; font-size: 95%;">{rerank_model}</td>
        </tr>
        <tr>
            <td class="label">DATABASE FILE</td>
            <td style="font-family: monospace; font-size: 95%;">{db_file}</td>
        </tr>
        <tr>
            <td class="label">PYTHON VERSION</td>
            <td>{python_version}</td>
        </tr>
        <tr>
            <td class="label">TOTAL PARSED BENCHMARKS</td>
            <td>{runs_count} runs</td>
        </tr>
        <tr>
            <td class="label">REPORT DATE</td>
            <td class="dateTime">{report_time}</td>
        </tr>
    </table>

    <h2>Benchmark summary</h2>
    <div class="explanation">
        Overall performance trends from the initial run to the latest execution
    </div>

    <div class="summary-pill-container">
        <div class="summary-pill" id="summary-pill-runs">
            <div class="summary-pill-title">Parsed Runs</div>
            <div class="summary-pill-value" style="color: #11D8E8;">{runs_count}</div>
        </div>
        <div class="summary-pill" id="summary-pill-warm">
            <div class="summary-pill-title">Warm Start Trend</div>
            <div class="summary-pill-value" id="val-warm-change">-</div>
        </div>
        <div class="summary-pill" id="summary-pill-cold">
            <div class="summary-pill-title">Cold Start Trend</div>
            <div class="summary-pill-value" id="val-cold-change">-</div>
        </div>
        <div class="summary-pill">
            <div class="summary-pill-title">Latest Success Rate</div>
            <div class="summary-pill-value" id="val-success-rate">-</div>
        </div>
    </div>

    <h2>Recent runs</h2>
    <div class="explanation">
        Summary of the chronological benchmark executions
    </div>
    <table style="width: 100%;">
        <colgroup>
            <col style="width: 10%;" />
            <col style="width: 30%;" />
            <col style="width: 20%;" />
            <col style="width: 20%;" />
            <col style="width: 20%;" />
        </colgroup>
        <thead>
            <tr>
                <th>RUN ID</th>
                <th>TIMESTAMP</th>
                <th style="text-align: right;">WARM START AVG (ms)</th>
                <th style="text-align: right;">COLD START AVG (ms)</th>
                <th style="text-align: right;">SUCCESS RATE</th>
            </tr>
        </thead>
        <tbody id="runs-history-tbody">
            <!-- Dynamic Run Summary Rows -->
        </tbody>
    </table>

    <h2>Benchmark history graph</h2>
    <div class="explanation">
        Timeline graph displaying latency. Solid lines represent warm start; dashed lines represent cold start.
    </div>

    <div class="graph-section">
        <!-- Sidebar Controls -->
        <div style="display: flex; flex-direction: column; gap: 1.25rem;">
            <div class="control-group">
                <span class="control-label">Metric</span>
                <select id="control-metric" onchange="updateChart()">
                    <option value="mean_ms">Mean Latency (ms)</option>
                    <option value="median_ms">Median Latency (ms)</option>
                    <option value="p95_ms">P95 Latency (ms)</option>
                    <option value="p99_ms">P99 Latency (ms)</option>
                    <option value="min_ms">Min Latency (ms)</option>
                    <option value="max_ms">Max Latency (ms)</option>
                    <option value="success_rate">Success Rate (%)</option>
                </select>
            </div>

            <div class="control-group">
                <span class="control-label">Y-Axis Scale</span>
                <select id="control-scale" onchange="updateChart()">
                    <option value="linear">Linear Scale</option>
                    <option value="logarithmic" selected>Logarithmic Scale</option>
                </select>
            </div>

            <div class="control-group">
                <span class="control-label">Filter Checklist</span>
                <select id="filter-checkbox-mode" onchange="filterToolList()">
                    <option value="all">Show All Modes</option>
                    <option value="warm">Warm Start Only</option>
                    <option value="cold">Cold Start Only</option>
                </select>
            </div>

            <div class="control-group">
                <span class="control-label">Tools (<span id="selected-tools-count">0 selected</span>)</span>
                <input type="text" id="search-tools" placeholder="Filter list..." oninput="filterToolList()" style="min-width: unset; width: 320px;">
                <div class="checkbox-container" id="tool-checkboxes">
                    <!-- Checkboxes generated dynamically -->
                </div>
                <div class="quick-btn-row">
                    <button class="btn-action" onclick="quickFilterTools('all')">Select All</button>
                    <button class="btn-action" onclick="quickFilterTools('none')">Clear</button>
                    <button class="btn-action" onclick="quickFilterTools('slowest')">Slowest 5</button>
                    <button class="btn-action" onclick="quickFilterTools('changed')">Most Changed</button>
                </div>
            </div>
        </div>

        <!-- Graph canvas -->
        <div class="chart-box">
            <div class="chart-wrapper" id="chart-wrapper">
                <!-- SVG Chart drawn dynamically by JS -->
            </div>
        </div>
    </div>

    <h2>Top speed changes</h2>
    <div class="explanation">
        Comparison between the earliest run and the latest run, showing top speedups and regressions
    </div>
    
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-bottom: 2em;">
        <div>
            <div class="control-label" style="margin-bottom: 0.5em; color: #11D8E8;">TOP IMPROVEMENTS</div>
            <table style="width: 100%;">
                <colgroup>
                    <col style="width: 50%;" />
                    <col style="width: 15%;" />
                    <col style="width: 35%;" />
                </colgroup>
                <thead>
                    <tr>
                        <th>TOOL</th>
                        <th>MODE</th>
                        <th style="text-align: right;">CHANGE</th>
                    </tr>
                </thead>
                <tbody id="improvements-list-tbody">
                    <!-- Dynamic -->
                </tbody>
            </table>
        </div>
        <div>
            <div class="control-label" style="margin-bottom: 0.5em; color: #B82830;">TOP REGRESSIONS</div>
            <table style="width: 100%;">
                <colgroup>
                    <col style="width: 50%;" />
                    <col style="width: 15%;" />
                    <col style="width: 35%;" />
                </colgroup>
                <thead>
                    <tr>
                        <th>TOOL</th>
                        <th>MODE</th>
                        <th style="text-align: right;">CHANGE</th>
                    </tr>
                </thead>
                <tbody id="regressions-list-tbody">
                    <!-- Dynamic -->
                </tbody>
            </table>
        </div>
    </div>

    <h2>Detailed tool comparison matrix</h2>
    <div class="explanation">
        Timeline matrix of initial vs final execution parameters for all tools
    </div>

    <!-- Table toolbar -->
    <div class="controls-row" style="margin-bottom: 1em;">
        <div class="control-group">
            <span class="control-label">Search Matrix</span>
            <input type="text" id="search-table" placeholder="Filter matrix..." oninput="filterTable()">
        </div>
        <div class="control-group">
            <span class="control-label">Filter Mode</span>
            <select id="filter-table-mode" onchange="filterTable()">
                <option value="all">All Modes</option>
                <option value="warm">Warm Start</option>
                <option value="cold">Cold Start</option>
            </select>
        </div>
        <div class="control-group">
            <span class="control-label">Filter Change</span>
            <select id="filter-table-trend" onchange="filterTable()">
                <option value="all">All Statuses</option>
                <option value="improved">Speeded Up Only</option>
                <option value="regressed">Slowed Down Only</option>
                <option value="neutral">Neutral (&lt;1% Change)</option>
            </select>
        </div>
    </div>

    <!-- Segments Progress Indicator Bar -->
    <div id="table-summary-bar" style="margin-bottom: 1.5em; max-width: 800px;"></div>

    <div class="table-scroll-container">
        <table style="width: 100%; margin-bottom: 0;">
            <colgroup>
                <col style="width: 30%;" />
                <col style="width: 10%;" />
                <col style="width: 15%;" />
                <col style="width: 15%;" />
                <col style="width: 15%;" />
                <col style="width: 15%;" />
            </colgroup>
            <thead>
                <tr>
                    <th>TOOL NAME</th>
                    <th>MODE</th>
                    <th style="text-align: right;">INITIAL MEAN (ms)</th>
                    <th style="text-align: right;">LATEST MEAN (ms)</th>
                    <th style="text-align: right;">DIFF (ms)</th>
                    <th style="text-align: right;">% CHANGE</th>
                </tr>
            </thead>
            <tbody id="table-body">
                <!-- Dynamic Rows -->
            </tbody>
        </table>
    </div>
    <div id="table-empty-state" style="display: none; padding: 2em; text-align: center; color: #777777; border: 1px solid #333333; border-top: none;">
        No matching tools found. Try adjusting your search query or filters.
    </div>

    <!-- Data Injection & Client JavaScript -->
    <script>
        const processedData = {data_json};
        const summaryData = {summary_json};

        // Initialize Page
        window.addEventListener('DOMContentLoaded', () => {{
            initializeDashboard();
        }});

        function initializeDashboard() {{
            const runs = processedData.runs;
            const tools = processedData.tools;
            
            // Set Overall Summary Metrics
            const warmChange = summaryData.overall_warm_change_pct;
            const coldChange = summaryData.overall_cold_change_pct;
            
            setPillValue('val-warm-change', 'summary-pill-warm', warmChange);
            setPillValue('val-cold-change', 'summary-pill-cold', coldChange);

            // Latest Success Rate
            let latestSuccess = 100.0;
            let successSum = 0;
            let successCount = 0;
            for (const tool in tools) {{
                for (const mode in tools[tool]) {{
                    const successRates = tools[tool][mode].success_rate;
                    if (successRates && successRates.length > 0) {{
                        const val = successRates[successRates.length - 1];
                        if (val !== null) {{
                            successSum += val;
                            successCount++;
                        }}
                    }}
                }}
            }}
            if (successCount > 0) {{
                latestSuccess = (successSum / successCount).toFixed(1);
            }}
            document.getElementById('val-success-rate').textContent = `${{latestSuccess}}%`;

            // Populate Tables & UI Checklist
            populateRunsHistory();
            populateHighlights();
            populateToolCheckboxes(); // Sets up elements and triggers filterToolList() -> updateSelectedCount() -> updateChart()
            populateTable();
            populateTableStats();
            selectDefaultTools(); // Triggers default selection, updating selected count and redrawing chart
            filterTable();
        }}

        function setPillValue(elementId, pillId, value) {{
            const el = document.getElementById(elementId);
            const pill = document.getElementById(pillId);
            
            if (processedData.runs.length < 2) {{
                el.textContent = "N/A";
                return;
            }}

            const formattedVal = Math.abs(value).toFixed(1) + '%';
            if (value < -1.0) {{
                el.textContent = `-${{formattedVal}}`;
                el.className = "summary-pill-value badge-improvement";
                pill.className = "summary-pill improved";
            }} else if (value > 1.0) {{
                el.textContent = `+${{formattedVal}}`;
                el.className = "summary-pill-value badge-regression";
                pill.className = "summary-pill regressed";
            }} else {{
                el.textContent = "No Change";
                el.className = "summary-pill-value badge-neutral";
                pill.className = "summary-pill";
            }}
        }}

        function populateRunsHistory() {{
            const tbody = document.getElementById('runs-history-tbody');
            tbody.innerHTML = '';
            
            const runs = processedData.runs;
            const tools = processedData.tools;
            
            runs.forEach((runTs, runIdx) => {{
                let warmSum = 0, warmCount = 0;
                let coldSum = 0, coldCount = 0;
                let successSum = 0, successCount = 0;
                
                for (const tool in tools) {{
                    ['warm', 'cold'].forEach(mode => {{
                        if (tools[tool][mode]) {{
                            const meanVal = tools[tool][mode].mean_ms[runIdx];
                            const succVal = tools[tool][mode].success_rate[runIdx];
                            
                            if (meanVal !== null) {{
                                if (mode === 'warm') {{
                                    warmSum += meanVal;
                                    warmCount++;
                                }} else {{
                                    coldSum += meanVal;
                                    coldCount++;
                                }}
                            }}
                            if (succVal !== null) {{
                                successSum += succVal;
                                successCount++;
                            }}
                        }}
                    }});
                }}
                
                const avgWarm = warmCount > 0 ? (warmSum / warmCount).toFixed(2) : '-';
                const avgCold = coldCount > 0 ? (coldSum / coldCount).toFixed(2) : '-';
                const avgSucc = successCount > 0 ? (successSum / successCount).toFixed(1) + '%' : '-';
                
                const tr = document.createElement('tr');
                tr.className = runIdx % 2 === 0 ? 'even' : 'odd';
                tr.innerHTML = `
                    <td>${{runIdx + 1}}</td>
                    <td class="dateTime">${{runTs}}</td>
                    <td class="numeric-cell">${{avgWarm}}</td>
                    <td class="numeric-cell">${{avgCold}}</td>
                    <td class="numeric-cell">${{avgSucc}}</td>
                `;
                tbody.appendChild(tr);
            }});
        }}

        function populateHighlights() {{
            const impTbody = document.getElementById('improvements-list-tbody');
            const regTbody = document.getElementById('regressions-list-tbody');
            
            impTbody.innerHTML = '';
            regTbody.innerHTML = '';

            const imps = summaryData.improvements || [];
            const regs = summaryData.regressions || [];

            if (imps.length === 0) {{
                impTbody.innerHTML = '<tr><td colspan="3" class="centered" style="color: #777777;">No significant speedups</td></tr>';
            }} else {{
                imps.slice(0, 5).forEach((item, idx) => {{
                    const tr = document.createElement('tr');
                    tr.className = idx % 2 === 0 ? 'even' : 'odd';
                    tr.innerHTML = `
                        <td style="font-family: monospace;">${{item.tool}}</td>
                        <td>${{item.mode}}</td>
                        <td class="numeric-cell badge-improvement">${{item.pct_change.toFixed(1)}}% (${{item.first_val.toFixed(2)}}ms → ${{item.last_val.toFixed(2)}}ms)</td>
                    `;
                    impTbody.appendChild(tr);
                }});
            }}

            if (regs.length === 0) {{
                regTbody.innerHTML = '<tr><td colspan="3" class="centered" style="color: #777777;">No significant slowdowns</td></tr>';
            }} else {{
                regs.slice(0, 5).forEach((item, idx) => {{
                    const tr = document.createElement('tr');
                    tr.className = idx % 2 === 0 ? 'even' : 'odd';
                    tr.innerHTML = `
                        <td style="font-family: monospace;">${{item.tool}}</td>
                        <td>${{item.mode}}</td>
                        <td class="numeric-cell badge-regression">+${{item.pct_change.toFixed(1)}}% (${{item.first_val.toFixed(2)}}ms → ${{item.last_val.toFixed(2)}}ms)</td>
                    `;
                    regTbody.appendChild(tr);
                }});
            }}
        }}

        function populateToolCheckboxes() {{
            const container = document.getElementById('tool-checkboxes');
            container.innerHTML = '';
            
            const tools = Object.keys(processedData.tools).sort();
            
            tools.forEach(tool => {{
                ['warm', 'cold'].forEach(mode => {{
                    if (processedData.tools[tool][mode]) {{
                        const label = document.createElement('label');
                        label.className = 'checkbox-item';
                        label.setAttribute('data-tool-name', tool);
                        label.setAttribute('data-tool-mode', mode);
                        
                        const checkbox = document.createElement('input');
                        checkbox.type = 'checkbox';
                        checkbox.value = `${{tool}}||${{mode}}`;
                        checkbox.id = `chk-${{tool}}-${{mode}}`;
                        checkbox.onchange = updateSelectedCount;
                        
                        const nameSpan = document.createElement('span');
                        nameSpan.className = 'tool-name-text';
                        nameSpan.textContent = tool;
                        
                        const badgeSpan = document.createElement('span');
                        badgeSpan.className = `tool-mode-tag tag-${{mode}}`;
                        badgeSpan.textContent = mode;
                        
                        label.appendChild(checkbox);
                        label.appendChild(nameSpan);
                        label.appendChild(badgeSpan);
                        container.appendChild(label);
                    }}
                }});
            }});
            
            filterToolList();
        }}

        function filterToolList() {{
            const query = document.getElementById('search-tools').value.toLowerCase();
            const modeFilter = document.getElementById('filter-checkbox-mode').value;
            const items = document.querySelectorAll('#tool-checkboxes .checkbox-item');
            
            items.forEach(item => {{
                const toolName = item.getAttribute('data-tool-name').toLowerCase();
                const toolMode = item.getAttribute('data-tool-mode');
                
                const matchesQuery = toolName.includes(query);
                const matchesMode = (modeFilter === 'all' || toolMode === modeFilter);
                
                if (matchesQuery && matchesMode) {{
                    item.style.display = 'flex';
                }} else {{
                    item.style.display = 'none';
                }}
            }});
            
            updateSelectedCount(); // Sync graph immediately with current filter state
        }}

        function updateSelectedCount() {{
            // Count all selected elements that match the active mode filter (warm/cold/all)
            const modeFilter = document.getElementById('filter-checkbox-mode').value;
            const checkboxes = document.querySelectorAll('#tool-checkboxes input[type="checkbox"]');
            let checkedCount = 0;
            
            checkboxes.forEach(chk => {{
                const [tool, toolMode] = chk.value.split('||');
                const matchesMode = (modeFilter === 'all' || toolMode === modeFilter);
                if (chk.checked && matchesMode) {{
                    checkedCount++;
                }}
            }});
            
            const countEl = document.getElementById('selected-tools-count');
            if (countEl) {{
                countEl.textContent = `${{checkedCount}} selected`;
            }}
            
            // Draw SVG
            updateChart();
        }}

        function selectDefaultTools() {{
            const checkboxes = document.querySelectorAll('#tool-checkboxes input[type="checkbox"]');
            checkboxes.forEach(c => c.checked = false);
            
            const candidates = [
                'retrieve_findings', 'search_knowledge', 'save_finding', 'query_memory'
            ];
            
            let checkedCount = 0;
            checkboxes.forEach(chk => {{
                const [tool, mode] = chk.value.split('||');
                if (candidates.includes(tool)) {{
                    chk.checked = true;
                    checkedCount++;
                }}
            }});
            
            if (checkedCount === 0 && checkboxes.length > 0) {{
                for (let i = 0; i < Math.min(4, checkboxes.length); i++) {{
                    checkboxes[i].checked = true;
                }}
            }}
            
            updateSelectedCount();
        }}

        function quickFilterTools(filterType) {{
            // Select labels visible under current filter state
            const checkboxLabels = Array.from(document.querySelectorAll('#tool-checkboxes .checkbox-item'));
            const visibleLabels = checkboxLabels.filter(lbl => lbl.style.display !== 'none');
            const visibleCheckboxes = visibleLabels.map(lbl => lbl.querySelector('input[type="checkbox"]'));
            
            if (filterType === 'all') {{
                visibleCheckboxes.forEach(c => c.checked = true);
            }} else if (filterType === 'none') {{
                // Clear ALL checkboxes, not just visible ones, to avoid hidden checked elements plotting lines
                const allCheckboxes = document.querySelectorAll('#tool-checkboxes input[type="checkbox"]');
                allCheckboxes.forEach(c => c.checked = false);
            }} else if (filterType === 'slowest') {{
                // Clear ALL first, to show exactly slowest 5
                const allCheckboxes = document.querySelectorAll('#tool-checkboxes input[type="checkbox"]');
                allCheckboxes.forEach(c => c.checked = false);
                
                const toolLatencies = [];
                visibleCheckboxes.forEach(c => {{
                    const [tool, mode] = c.value.split('||');
                    const means = processedData.tools[tool][mode].mean_ms;
                    const latestVal = means[means.length - 1];
                    if (latestVal !== null) {{
                        toolLatencies.push({{ val: latestVal, chk: c }});
                    }}
                }});
                toolLatencies.sort((a, b) => b.val - a.val); // slowest first
                toolLatencies.slice(0, 5).forEach(item => item.chk.checked = true);
            }} else if (filterType === 'changed') {{
                // Clear ALL first, to show exactly most changed 5
                const allCheckboxes = document.querySelectorAll('#tool-checkboxes input[type="checkbox"]');
                allCheckboxes.forEach(c => c.checked = false);
                
                const toolChanges = [];
                visibleCheckboxes.forEach(c => {{
                    const [tool, mode] = c.value.split('||');
                    const means = processedData.tools[tool][mode].mean_ms;
                    const firstVal = means[0];
                    const latestVal = means[means.length - 1];
                    if (firstVal !== null && latestVal !== null && firstVal > 0) {{
                        const pct = Math.abs(((latestVal - firstVal) / firstVal) * 100);
                        toolChanges.push({{ val: pct, chk: c }});
                    }}
                }});
                toolChanges.sort((a, b) => b.val - a.val); // most changed first
                toolChanges.slice(0, 5).forEach(item => item.chk.checked = true);
            }}
            
            updateSelectedCount();
        }}

        function getHSLColor(index, total) {{
            const hue = (index * (360 / Math.max(1, total))) % 360;
            return `hsl(${{hue}}, 85%, 60%)`;
        }}

        // Native SVG Graph Drawer (Zero CDNs, 100% Offline-First)
        function updateChart() {{
            const container = document.getElementById('chart-wrapper');
            if (!container) return;
            
            const metric = document.getElementById('control-metric').value;
            const scaleSelect = document.getElementById('control-scale');
            
            if (metric === 'success_rate') {{
                scaleSelect.value = 'linear';
                scaleSelect.disabled = true;
            }} else {{
                scaleSelect.disabled = false;
            }}
            
            const scaleType = scaleSelect.value;
            
            // Plot checkboxes that are checked AND match the active mode filter (independent of search text)
            const visibleCheckedItems = [];
            const checkboxes = document.querySelectorAll('#tool-checkboxes input[type="checkbox"]');
            const modeFilter = document.getElementById('filter-checkbox-mode').value;
            
            checkboxes.forEach(chk => {{
                const [tool, toolMode] = chk.value.split('||');
                const matchesMode = (modeFilter === 'all' || toolMode === modeFilter);
                if (chk.checked && matchesMode) {{
                    visibleCheckedItems.push(chk.value);
                }}
            }});
            
            if (visibleCheckedItems.length === 0) {{
                container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#777777;font-family:Segoe UI Light;">No tools selected</div>';
                return;
            }}
            
            const runs = processedData.runs;
            const selectedTools = Array.from(new Set(visibleCheckedItems.map(item => item.split('||')[0])));
            
            // Fixed SVG coordinate boundaries for hardware responsive scaling
            const width = 850;
            const height = 480;
            const padLeft = 80;
            const padRight = 200; // room for legend
            const padTop = 30;
            const padBottom = 80;
            
            const plotWidth = width - padLeft - padRight;
            const plotHeight = height - padTop - padBottom;
            
            // Collect visible plotted values to establish axis scale limits
            let allValues = [];
            visibleCheckedItems.forEach(item => {{
                const [tool, mode] = item.split('||');
                if (processedData.tools[tool] && processedData.tools[tool][mode]) {{
                    const vals = processedData.tools[tool][mode][metric];
                    vals.forEach(v => {{
                        if (v !== null) allValues.push(v);
                    }});
                }}
            }});
            
            if (allValues.length === 0) {{
                container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#777777;font-family:Segoe UI Light;">No data points available</div>';
                return;
            }}
            
            let yMin = 0;
            let yMax = Math.max(...allValues) * 1.1; // 10% ceiling padding
            if (yMax === 0) yMax = 10;
            
            if (scaleType === 'logarithmic') {{
                const positiveValues = allValues.filter(v => v > 0);
                const minPosVal = positiveValues.length > 0 ? Math.min(...positiveValues) : 0.001;
                yMin = Math.pow(10, Math.floor(Math.log10(minPosVal)));
                yMax = Math.pow(10, Math.ceil(Math.log10(yMax)));
                if (yMin === yMax) {{
                    yMin /= 10;
                    yMax *= 10;
                }}
            }}
            
            let svg = `<svg width="100%" height="100%" viewBox="0 0 ${{width}} ${{height}}" xmlns="http://www.w3.org/2000/svg" style="background-color:#181818; font-family:Segoe UI Light, Segoe UI, sans-serif;">`;
            
            // Draw horizontal grid lines
            let yGridPoints = [];
            if (scaleType === 'linear') {{
                const step = yMax / 5;
                for (let i = 0; i <= 5; i++) {{
                    yGridPoints.push(step * i);
                }}
            }} else {{
                let val = yMin;
                let limit = 0;
                while (val <= yMax && limit < 15) {{
                    yGridPoints.push(val);
                    val *= 10;
                    limit++;
                }}
            }}
            
            yGridPoints.forEach(val => {{
                let yPct;
                if (scaleType === 'linear') {{
                    yPct = val / yMax;
                }} else {{
                    yPct = (Math.log10(val) - Math.log10(yMin)) / (Math.log10(yMax) - Math.log10(yMin));
                }}
                const y = padTop + plotHeight - (yPct * plotHeight);
                
                svg += `<line x1="${{padLeft}}" y1="${{y}}" x2="${{padLeft + plotWidth}}" y2="${{y}}" stroke="#272727" stroke-width="1" />`;
                
                let labelText = val >= 1 ? val.toFixed(1) : val.toFixed(3);
                if (metric === 'success_rate') labelText += '%';
                else labelText += ' ms';
                svg += `<text x="${{padLeft - 12}}" y="${{y + 4}}" fill="#BCBCBC" font-size="9.5pt" text-anchor="end" font-family="Segoe UI Symbol">${{labelText}}</text>`;
            }});
            
            // Draw vertical grid lines (X runs)
            const numRuns = runs.length;
            const xStep = numRuns > 1 ? plotWidth / (numRuns - 1) : 0;
            
            runs.forEach((run, idx) => {{
                const x = numRuns > 1 ? (padLeft + idx * xStep) : (padLeft + plotWidth / 2);
                
                svg += `<line x1="${{x}}" y1="${{padTop}}" x2="${{x}}" y2="${{padTop + plotHeight}}" stroke="#272727" stroke-dasharray="2,2" stroke-width="1" />`;
                
                const dateParts = run.split(' ');
                const dateStr = dateParts[0].substring(5); // e.g. 05-25
                const timeStr = dateParts[1] ? dateParts[1].substring(0, 5) : ''; // e.g. 19:05
                
                svg += `<g transform="translate(${{x}}, ${{padTop + plotHeight + 18}})">`;
                svg += `<text fill="#BCBCBC" font-size="8.5pt" text-anchor="middle" transform="rotate(30)" font-family="Segoe UI Symbol">${{dateStr}} ${{timeStr}}</text>`;
                svg += `</g>`;
            }});
            
            // Draw axes
            svg += `<line x1="${{padLeft}}" y1="${{padTop}}" x2="${{padLeft}}" y2="${{padTop + plotHeight}}" stroke="#555555" stroke-width="1" />`;
            svg += `<line x1="${{padLeft}}" y1="${{padTop + plotHeight}}" x2="${{padLeft + plotWidth}}" y2="${{padTop + plotHeight}}" stroke="#555555" stroke-width="1" />`;
            
            // Plot Data Series
            visibleCheckedItems.forEach((item) => {{
                const [tool, mode] = item.split('||');
                const toolData = processedData.tools[tool][mode];
                if (!toolData) return;
                
                const rawPoints = toolData[metric];
                const colorIdx = selectedTools.indexOf(tool);
                const baseColor = getHSLColor(colorIdx, selectedTools.length);
                
                let pathPoints = [];
                
                rawPoints.forEach((v, runIdx) => {{
                    if (v === null) return;
                    const x = numRuns > 1 ? (padLeft + runIdx * xStep) : (padLeft + plotWidth / 2);
                    
                    let yVal = v;
                    if (scaleType === 'logarithmic') {{
                        yVal = v <= 0 ? 0.001 : v;
                    }}
                    
                    let yPct;
                    if (scaleType === 'linear') {{
                        yPct = yVal / yMax;
                    }} else {{
                        yPct = (Math.log10(yVal) - Math.log10(yMin)) / (Math.log10(yMax) - Math.log10(yMin));
                    }}
                    yPct = Math.max(0, Math.min(1, yPct));
                    const y = padTop + plotHeight - (yPct * plotHeight);
                    
                    pathPoints.push({{ x, y, val: v, run: runs[runIdx] }});
                }});
                
                // Line Path
                if (pathPoints.length > 1) {{
                    let pointsStr = pathPoints.map(p => `${{p.x}},${{p.y}}`).join(' ');
                    const strokeDash = mode === 'cold' ? 'stroke-dasharray="6,4"' : '';
                    svg += `<polyline points="${{pointsStr}}" fill="none" stroke="${{baseColor}}" stroke-width="1.8" ${{strokeDash}} />`;
                }}
                
                // Markers
                pathPoints.forEach(p => {{
                    let markerSvg = '';
                    const tooltipText = `${{tool}} (${{mode}})\\nRun: ${{p.run}}\\nValue: ${{p.val.toFixed(3)}} ${{metric === 'success_rate' ? '%' : 'ms'}}`;
                    
                    if (mode === 'warm') {{
                        markerSvg = `<circle cx="${{p.x}}" cy="${{p.y}}" r="4" fill="${{baseColor}}" stroke="#181818" stroke-width="1">`;
                    }} else {{
                        markerSvg = `<polygon points="${{p.x}},${{p.y-5}} ${{p.x-5}},${{p.y+4}} ${{p.x+5}},${{p.y+4}}" fill="${{baseColor}}" stroke="#181818" stroke-width="1">`;
                    }}
                    markerSvg += `<title>${{tooltipText}}</title>`;
                    markerSvg += mode === 'warm' ? `</circle>` : `</polygon>`;
                    
                    svg += markerSvg;
                }});
            }});
            
            // Draw Legend (Right Side)
            const legendLeft = padLeft + plotWidth + 20;
            visibleCheckedItems.forEach((item, idx) => {{
                const [tool, mode] = item.split('||');
                const colorIdx = selectedTools.indexOf(tool);
                const baseColor = getHSLColor(colorIdx, selectedTools.length);
                const y = padTop + idx * 22;
                
                if (y < height - 20) {{
                    const strokeDash = mode === 'cold' ? 'stroke-dasharray="3,2"' : '';
                    svg += `<line x1="${{legendLeft}}" y1="${{y + 6}}" x2="${{legendLeft + 25}}" y2="${{y + 6}}" stroke="${{baseColor}}" stroke-width="2" ${{strokeDash}} />`;
                    
                    if (mode === 'warm') {{
                        svg += `<circle cx="${{legendLeft + 12.5}}" cy="${{y + 6}}" r="3.5" fill="${{baseColor}}" />`;
                    }} else {{
                        svg += `<polygon points="${{legendLeft + 12.5}},${{y + 2}} ${{legendLeft + 9.5}},${{y + 9}} ${{legendLeft + 15.5}},${{y + 9}}" fill="${{baseColor}}" />`;
                    }}
                    
                    const toolShortName = tool.length > 20 ? tool.substring(0, 18) + '...' : tool;
                    svg += `<text x="${{legendLeft + 32}}" y="${{y + 10}}" fill="#F0F0F0" font-size="9pt" font-family="Segoe UI Symbol">${{toolShortName}} (${{mode}})</text>`;
                }}
            }});
            
            svg += `</svg>`;
            container.innerHTML = svg;
        }}

        function populateTable() {{
            const tbody = document.getElementById('table-body');
            tbody.innerHTML = '';
            
            const comparisons = summaryData.all_comparisons || [];
            comparisons.sort((a, b) => a.tool.localeCompare(b.tool) || a.mode.localeCompare(b.mode));
            
            comparisons.forEach((c, idx) => {{
                const tr = document.createElement('tr');
                tr.setAttribute('data-tool', c.tool);
                tr.setAttribute('data-mode', c.mode);
                
                let changeClass = 'badge-neutral';
                let changeSymbol = '';
                if (c.pct_change < -1.0) {{
                    changeClass = 'badge-improvement';
                    changeSymbol = '↓';
                }} else if (c.pct_change > 1.0) {{
                    changeClass = 'badge-regression';
                    changeSymbol = '↑';
                }}
                
                const pctFormatted = Math.abs(c.pct_change).toFixed(1) + '%';
                const diffFormatted = (c.diff > 0 ? '+' : '') + c.diff.toFixed(3) + ' ms';
                
                tr.innerHTML = `
                    <td class="tool-name-cell" style="font-family: monospace;">${{c.tool}}</td>
                    <td><span class="tool-mode-tag tag-${{c.mode}}">${{c.mode}}</span></td>
                    <td class="numeric-cell" style="color: #BCBCBC;">${{c.first_val.toFixed(3)}}</td>
                    <td class="numeric-cell" style="font-family: Segoe UI Semibold;">${{c.last_val.toFixed(3)}}</td>
                    <td class="numeric-cell ${{changeClass}}">${{diffFormatted}}</td>
                    <td class="numeric-cell ${{changeClass}}">
                        ${{changeSymbol}} ${{pctFormatted}}
                    </td>
                `;
                
                tbody.appendChild(tr);
            }});
            
            if (comparisons.length === 0) {{
                const tools = processedData.tools;
                const runs = processedData.runs;
                if (runs.length > 0) {{
                    const r = runs[0];
                    for (const tool in tools) {{
                        for (const mode in tools[tool]) {{
                            const means = tools[tool][mode].mean_ms;
                            const val = means[0];
                            if (val === null) continue;
                            
                            const tr = document.createElement('tr');
                            tr.setAttribute('data-tool', tool);
                            tr.setAttribute('data-mode', mode);
                            tr.innerHTML = `
                                <td class="tool-name-cell" style="font-family: monospace;">${{tool}}</td>
                                <td><span class="tool-mode-tag tag-${{mode}}">${{mode}}</span></td>
                                <td class="numeric-cell" style="color: #BCBCBC;">-</td>
                                <td class="numeric-cell" style="font-family: Segoe UI Semibold;">${{val.toFixed(3)}}</td>
                                <td class="numeric-cell badge-neutral">-</td>
                                <td class="numeric-cell badge-neutral">-</td>
                            `;
                            tbody.appendChild(tr);
                        }}
                    }}
                }}
            }}
            
            reapplyZebraStripes();
        }}

        function reapplyZebraStripes() {{
            const rows = document.querySelectorAll('#table-body tr');
            let visibleIndex = 0;
            rows.forEach(row => {{
                if (row.style.display !== 'none') {{
                    row.className = visibleIndex % 2 === 0 ? 'even' : 'odd';
                    visibleIndex++;
                }}
            }});
        }}

        function populateTableStats() {{
            const comparisons = summaryData.all_comparisons || [];
            let improvedCount = 0;
            let regressedCount = 0;
            let neutralCount = 0;
            
            comparisons.forEach(c => {{
                if (c.pct_change < -1.0) improvedCount++;
                else if (c.pct_change > 1.0) regressedCount++;
                else neutralCount++;
            }});
            
            const totalCount = comparisons.length || 1;
            const impPct = ((improvedCount / totalCount) * 100).toFixed(1);
            const regPct = ((regressedCount / totalCount) * 100).toFixed(1);
            const neuPct = (100 - parseFloat(impPct) - parseFloat(regPct)).toFixed(1);
            
            const summaryBar = document.getElementById('table-summary-bar');
            if (summaryBar) {{
                summaryBar.innerHTML = `
                    <div style="display: flex; gap: 1rem; font-size: 10pt; margin-bottom: 0.5em; justify-content: space-between; flex-wrap: wrap;">
                        <div style="display: flex; gap: 1.5rem; flex-wrap: wrap;">
                            <span style="display: flex; align-items: center; gap: 0.4rem;">
                                <span style="width: 8px; height: 8px; background-color: #11EEF4; border-radius: 50%;"></span>
                                <strong>${{improvedCount}}</strong> speeded up (${{impPct}}%)
                            </span>
                            <span style="display: flex; align-items: center; gap: 0.4rem;">
                                <span style="width: 8px; height: 8px; background-color: #B82830; border-radius: 50%;"></span>
                                <strong>${{regressedCount}}</strong> slowed down (${{regPct}}%)
                            </span>
                            <span style="display: flex; align-items: center; gap: 0.4rem;">
                                <span style="width: 8px; height: 8px; background-color: #888888; border-radius: 50%;"></span>
                                <strong>${{neutralCount}}</strong> stable (${{neuPct}}%)
                            </span>
                        </div>
                        <div style="color: #777777;">Total: <strong>${{totalCount}}</strong></div>
                    </div>
                    <div style="display: flex; height: 4px; overflow: hidden; background: #272727;">
                        <div style="width: ${{impPct}}%; background-color: #11EEF4;" title="Improved: ${{impPct}}%"></div>
                        <div style="width: ${{neuPct}}%; background-color: #888888;" title="Stable: ${{neuPct}}%"></div>
                        <div style="width: ${{regPct}}%; background-color: #B82830;" title="Regressed: ${{regPct}}%"></div>
                    </div>
                `;
            }}
        }}

        function filterTable() {{
            const query = document.getElementById('search-table').value.toLowerCase();
            const modeFilter = document.getElementById('filter-table-mode').value;
            const trendFilter = document.getElementById('filter-table-trend').value;
            
            const rows = document.querySelectorAll('#table-body tr');
            let visibleCount = 0;
            
            rows.forEach(row => {{
                const tool = row.getAttribute('data-tool').toLowerCase();
                const mode = row.getAttribute('data-mode');
                
                const cells = row.querySelectorAll('td');
                const lastCell = cells[cells.length - 1];
                let isImproved = lastCell.classList.contains('badge-improvement');
                let isRegressed = lastCell.classList.contains('badge-regression');
                let isNeutral = lastCell.classList.contains('badge-neutral');

                const matchesQuery = tool.includes(query);
                const matchesMode = (modeFilter === 'all' || mode === modeFilter);
                
                let matchesTrend = true;
                if (trendFilter === 'improved') matchesTrend = isImproved;
                else if (trendFilter === 'regressed') matchesTrend = isRegressed;
                else if (trendFilter === 'neutral') matchesTrend = isNeutral;

                if (matchesQuery && matchesMode && matchesTrend) {{
                    row.style.display = '';
                    visibleCount++;
                }} else {{
                    row.style.display = 'none';
                }}
            }});
            
            const emptyState = document.getElementById('table-empty-state');
            if (visibleCount === 0) {{
                emptyState.style.display = 'block';
            }} else {{
                emptyState.style.display = 'none';
            }}
            
            reapplyZebraStripes();
        }}
    </script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

def main():
    print("Collecting benchmark files...")
    report_config = load_report_config()
    files = get_benchmark_files(report_config=report_config)
    
    if not files:
        print("Error: No benchmark result files found matching results/benchmark_*.json.")
        return
        
    print(f"Found {len(files)} benchmark files.")
    for f in files:
        print(f" - {os.path.basename(f)}")
        
    runs = parse_benchmark_data(files)
    processed_data = process_metrics(runs)
    comparison_summary = generate_comparison_summary(processed_data, report_config=report_config)
    
    output_path = os.path.join("results", "benchmark_report.html")
    llm_json_path = os.path.join("results", "benchmark_report_llm.json")
    markdown_path = os.path.join("results", "benchmark_report.md")
    build_html_report(processed_data, comparison_summary, output_path)
    write_llm_json_report(processed_data, comparison_summary, llm_json_path, report_config=report_config)
    write_markdown_report(processed_data, comparison_summary, markdown_path, report_config=report_config)
    
    print("\n" + "="*60)
    print("Benchmark Report Successfully Generated!")
    print(f"Saved to: {os.path.abspath(output_path)}")
    print(f"Saved to: {os.path.abspath(llm_json_path)}")
    print(f"Saved to: {os.path.abspath(markdown_path)}")
    print("="*60)
    
    if len(files) >= 2:
        print(f"\nTimeline Comparison Summary ({runs[0]['timestamp']} vs {runs[-1]['timestamp']}):")
        print(f" - Overall Warm Start Latency: {comparison_summary['overall_warm_change_pct']:+.1f}%")
        print(f" - Overall Cold Start Latency: {comparison_summary['overall_cold_change_pct']:+.1f}%")
        
        print("\nTop Improvements:")
        for idx, imp in enumerate(comparison_summary["improvements"][:3]):
            print(f" {idx+1}. {imp['tool']} ({imp['mode']}): {imp['first_val']:.2f} ms -> {imp['last_val']:.2f} ms ({imp['pct_change']:.1f}%)")
            
        print("\nTop Regressions:")
        for idx, reg in enumerate(comparison_summary["regressions"][:3]):
            print(f" {idx+1}. {reg['tool']} ({reg['mode']}): {reg['first_val']:.2f} ms -> {reg['last_val']:.2f} ms ({reg['pct_change']:+.1f}%)")
    else:
        print("\nOnly one benchmark run detected. Add more benchmark runs to view comparison trends over time.")

if __name__ == "__main__":
    main()
