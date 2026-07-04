"""
Automated rubric scorer + report generator for DeepResearch Benchmark.

Usage:
    python score_and_report.py --jsonl outputs/raw/run_XXXX.jsonl
    python score_and_report.py --jsonl outputs/raw/run_XXXX.jsonl --rescore-nulls
    python score_and_report.py --jsonl outputs/raw/run_XXXX.jsonl --rescore-long

Output structure (model-specific):
    outputs/models/<model_slug>/
        scores/scores_<run_id>.jsonl
        scores/scores_<run_id>.csv
        report/report_<run_id>.md
        plots/plots_<run_id>/  (PNG plots)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv()

DIMENSIONS = ["Coverage", "Accuracy", "Reasoning", "Use of Evidence", "Clarity and Structure"]
MAX_DIM_SCORE = 2
MAX_TOTAL_SCORE = len(DIMENSIONS) * MAX_DIM_SCORE  # 10

SCORE_PROMPT_TEMPLATE = """\
You are a strict benchmark evaluator. Score the following model response against the provided rubric.

## Task prompt shown to the model
{prompt}

## Model response
{response}

## Rubric (each dimension scored 0, 1, or 2)
{rubric}

## Instructions
For each dimension listed in the rubric, output EXACTLY one line in this format:
DimensionName: <score>

Where <score> is 0, 1, or 2. Use the rubric level descriptions literally.
Do not add any explanation — output ONLY the score lines.
Example output:
Coverage: 2
Accuracy: 1
Reasoning: 2
Use of Evidence: 1
Clarity and Structure: 2
"""

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SCORER_MODEL = "deepseek/deepseek-v4-pro"


def model_slug_to_folder(model_slug: str) -> str:
    """Convert e.g. 'openai/gpt-5.5' -> 'openai__gpt-5.5' for safe folder names."""
    return model_slug.replace("/", "__")


def _truncate_response(response: str, head: int = 10000, tail: int = 5000) -> str:
    """For long responses take head + tail to capture both intro and conclusion."""
    if len(response) <= head + tail:
        return response
    return response[:head] + f"\n\n[... {len(response) - head - tail:,} chars omitted ...]\n\n" + response[-tail:]


def score_response(api_key: str, prompt: str, response: str, rubric: str) -> dict[str, int | None]:
    """Call DeepSeek to score one response. Returns {dimension: score}."""
    content = SCORE_PROMPT_TEMPLATE.format(
        prompt=prompt[:2000],
        response=_truncate_response(response),
        rubric=rubric[:4000],
    )
    try:
        r = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": SCORER_MODEL,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 4000,
                "temperature": 0.0,
            },
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            print(f"    [scorer error] {body['error']}", flush=True)
            return {d: None for d in DIMENSIONS}
        text = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return _parse_scores(text)
    except Exception as e:
        print(f"    [scorer exception] {e}", flush=True)
        return {d: None for d in DIMENSIONS}


def _parse_scores(text: str) -> dict[str, int | None]:
    scores: dict[str, int | None] = {d: None for d in DIMENSIONS}
    for line in text.strip().splitlines():
        for dim in DIMENSIONS:
            if line.lower().startswith(dim.lower()):
                m = re.search(r"\b([012])\b", line)
                if m:
                    scores[dim] = int(m.group(1))
    return scores


def load_results(jsonl_path: Path) -> list[dict]:
    """Load raw JSONL results and merge rubric fields from matching CSV."""
    results = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))

    run_file = jsonl_path.name
    csv_candidate = jsonl_path.parent.parent / "results" / run_file.replace(".jsonl", ".csv")

    rubric_map: dict[str, dict] = {}
    if csv_candidate.exists():
        with open(csv_candidate, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tid = row.get("task_id", "")
                rubric_map[tid] = {
                    "fixed_criteria_0_2_each": row.get("fixed_criteria_0_2_each", ""),
                    "fixed_criteria_0_2_each_ru": row.get("fixed_criteria_0_2_each_ru", ""),
                    "rubric_id": row.get("rubric_id", ""),
                }

    for r in results:
        tid = r.get("task_id", "")
        if tid in rubric_map and not r.get("fixed_criteria_0_2_each"):
            r.update(rubric_map[tid])

    return results


def run_scoring(results: list[dict], api_key: str) -> list[dict]:
    scored = []
    total = len(results)
    for i, r in enumerate(results, 1):
        print(f"  [{i}/{total}] scoring {r['task_id']} ...", flush=True)
        rubric = r.get("fixed_criteria_0_2_each") or r.get("fixed_criteria_0_2_each_ru") or ""
        dim_scores = score_response(
            api_key=api_key,
            prompt=r["prompt"],
            response=r["response_text"],
            rubric=rubric,
        )
        total_score = sum(v for v in dim_scores.values() if v is not None)
        scored.append({
            "task_id": r["task_id"],
            "domain": r["domain"],
            "task_type": r.get("task_type", ""),
            "model": r["model"],
            "status": r["status"],
            "token_usage_total": (r.get("token_usage") or {}).get("total_tokens"),
            **{f"score_{k.lower().replace(' ', '_')}": v for k, v in dim_scores.items()},
            "score_total": total_score,
            "score_pct": round(total_score / MAX_TOTAL_SCORE * 100, 1),
        })
        time.sleep(0.3)
    return scored


def get_model_dir(model_slug: str, base_dir: Path) -> Path:
    return base_dir / "outputs" / "models" / model_slug_to_folder(model_slug)


def write_outputs(scored: list[dict], run_id: str, base_dir: Path) -> tuple[Path, Path]:
    model_slug = scored[0]["model"] if scored else "unknown"
    scores_dir = get_model_dir(model_slug, base_dir) / "scores"
    scores_dir.mkdir(parents=True, exist_ok=True)

    jsonl_out = scores_dir / f"scores_{run_id}.jsonl"
    with open(jsonl_out, "w") as f:
        for row in scored:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    csv_out = scores_dir / f"scores_{run_id}.csv"
    if scored:
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(scored[0].keys()))
            writer.writeheader()
            writer.writerows(scored)
    return jsonl_out, csv_out


def make_plots(scored: list[dict], run_id: str, base_dir: Path) -> Path:
    model_slug = scored[0]["model"] if scored else "unknown"
    title_prefix = model_slug
    plot_dir = get_model_dir(model_slug, base_dir) / "plots" / f"plots_{run_id}"
    plot_dir.mkdir(parents=True, exist_ok=True)

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linestyle": "--",
        "axes.facecolor": "#F8F9FA",
        "figure.facecolor": "white",
    })

    valid = [s for s in scored if s["score_total"] is not None]
    domains = sorted(set(s["domain"] for s in valid))
    dim_keys = [f"score_{d.lower().replace(' ', '_')}" for d in DIMENSIONS]

    # ── 1. Mean + Max score by domain (horizontal lollipop) ──────────────────
    domain_totals = {d: [s["score_total"] for s in valid if s["domain"] == d] for d in domains}
    domains_sorted = sorted(domains, key=lambda d: np.mean(domain_totals[d]))
    means  = [np.mean(domain_totals[d]) for d in domains_sorted]
    maxs   = [max(domain_totals[d])     for d in domains_sorted]
    errors = [np.std(domain_totals[d]) / max(len(domain_totals[d]) ** 0.5, 1) for d in domains_sorted]
    counts = [len(domain_totals[d])     for d in domains_sorted]
    overall_mean = np.mean([s["score_total"] for s in valid])

    cmap = plt.cm.RdYlGn
    bar_colors = [cmap(m / MAX_TOTAL_SCORE) for m in means]

    fig, ax = plt.subplots(figsize=(11, 5))
    y = np.arange(len(domains_sorted))

    ax.barh(y, [MAX_TOTAL_SCORE] * len(y), height=0.55, color="#EBEBEB", zorder=1)
    bars = ax.barh(y, means, height=0.55, color=bar_colors,
                   xerr=errors, capsize=3, zorder=2,
                   error_kw={"elinewidth": 1.2, "ecolor": "#666"})

    for yi, (mn, mx, err) in enumerate(zip(means, maxs, errors)):
        ax.plot([mn + err + 0.05, mx], [yi, yi], color="#888", linewidth=0.8, linestyle=":", zorder=3)
        ax.scatter(mx, yi, marker="*", s=120, color="#E05C2A", zorder=4,
                   label="Max" if yi == 0 else "")
        ax.text(mx + 0.15, yi, str(int(mx)), va="center", ha="left",
                fontsize=9, color="#E05C2A", fontweight="bold")

    for bar, mn, err_val, c in zip(bars, means, errors, counts):
        ax.text(max(mn - 0.15, 0.1), bar.get_y() + bar.get_height() / 2,
                f"{mn:.1f}", va="center", ha="right", fontsize=9,
                color="white" if mn > 2 else "#333", fontweight="bold")
        ax.text(mn + err_val + 0.5, bar.get_y() + bar.get_height() / 2,
                f"n={c}", va="center", ha="left", fontsize=8, color="#555")

    ax.axvline(overall_mean, color="#D62728", linestyle="--", linewidth=1.4,
               label=f"Overall mean: {overall_mean:.2f}", zorder=5)
    ax.set_yticks(y)
    ax.set_yticklabels([d.replace("/", " /\n") for d in domains_sorted], fontsize=10)
    ax.set_xlim(0, MAX_TOTAL_SCORE + 2)
    ax.set_xlabel("Score (max 10)", fontsize=10)
    ax.set_title(f"{title_prefix}\nScore by Domain  (mean ± SE  ★ max) · run {run_id}",
                 fontsize=11, fontweight="bold", pad=12)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, labels, fontsize=9, loc="lower right")
    plt.tight_layout()
    fig.savefig(plot_dir / "01_score_by_domain.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 2. Per-dimension mean score ───────────────────────────────────────────
    dim_means = [np.mean([s[k] for s in valid if s[k] is not None]) for k in dim_keys]
    dim_order = np.argsort(dim_means)
    sorted_dims  = [DIMENSIONS[i] for i in dim_order]
    sorted_means = [dim_means[i]   for i in dim_order]
    d_colors = [cmap(v / MAX_DIM_SCORE) for v in sorted_means]

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.barh(sorted_dims, sorted_means, color=d_colors, edgecolor="none", height=0.5)
    ax.set_xlim(0, MAX_DIM_SCORE + 0.3)
    ax.set_xlabel("Mean score (max 2)", fontsize=10)
    ax.set_title(f"{title_prefix}\nScore by Dimension · run {run_id}",
                 fontsize=11, fontweight="bold", pad=10)
    for i, v in enumerate(sorted_means):
        ax.text(v + 0.03, i, f"{v:.2f}  ({v/MAX_DIM_SCORE*100:.0f}%)", va="center", fontsize=9)
    plt.tight_layout()
    fig.savefig(plot_dir / "02_score_by_dimension.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 3. Score distribution histogram ──────────────────────────────────────
    all_scores = [s["score_total"] for s in valid]
    hist_colors = [cmap(v / MAX_TOTAL_SCORE) for v in range(MAX_TOTAL_SCORE + 1)]

    fig, ax = plt.subplots(figsize=(9, 4))
    for v in range(MAX_TOTAL_SCORE + 1):
        cnt = all_scores.count(v)
        ax.bar(v, cnt, color=hist_colors[v], edgecolor="white", width=0.8, zorder=2)
        if cnt:
            ax.text(v, cnt + 0.3, str(cnt), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(MAX_TOTAL_SCORE + 1))
    ax.set_xlabel("Total score (max 10)", fontsize=10)
    ax.set_ylabel("Number of tasks", fontsize=10)
    mn = np.mean(all_scores)
    med = np.median(all_scores)
    ax.axvline(mn,  color="#D62728", linestyle="--", linewidth=1.4, label=f"Mean: {mn:.2f}")
    ax.axvline(med, color="#1F77B4", linestyle=":",  linewidth=1.4, label=f"Median: {med:.1f}")
    ax.set_title(f"{title_prefix}\nScore Distribution · run {run_id}",
                 fontsize=11, fontweight="bold", pad=10)
    ax.legend(fontsize=9)
    plt.tight_layout()
    fig.savefig(plot_dir / "03_score_distribution.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 4. Heatmap: domain × dimension ───────────────────────────────────────
    matrix = np.zeros((len(domains_sorted), len(DIMENSIONS)))
    for i, dom in enumerate(domains_sorted):
        for j, k in enumerate(dim_keys):
            vals = [s[k] for s in valid if s["domain"] == dom and s[k] is not None]
            matrix[i, j] = np.mean(vals) if vals else 0

    fig, ax = plt.subplots(figsize=(11, max(4, len(domains_sorted) * 0.75)))
    im = ax.imshow(matrix, cmap="RdYlGn", vmin=0, vmax=MAX_DIM_SCORE, aspect="auto")
    ax.set_xticks(range(len(DIMENSIONS)))
    ax.set_xticklabels(DIMENSIONS, fontsize=9)
    ax.set_yticks(range(len(domains_sorted)))
    ax.set_yticklabels(domains_sorted, fontsize=10)
    for i in range(len(domains_sorted)):
        for j in range(len(DIMENSIONS)):
            v = matrix[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                    color="white" if v < 0.8 or v > 1.5 else "black",
                    fontsize=9, fontweight="bold")
    plt.colorbar(im, ax=ax, label="Mean score (0–2)", shrink=0.8)
    ax.set_title(f"{title_prefix}\nDomain × Dimension Heatmap · run {run_id}",
                 fontsize=11, fontweight="bold", pad=10)
    plt.tight_layout()
    fig.savefig(plot_dir / "04_heatmap_domain_dimension.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    plt.rcParams.update(plt.rcParamsDefault)
    return plot_dir


def make_report(scored: list[dict], all_results: list[dict],
                run_id: str, plot_dir: Path, base_dir: Path) -> Path:
    model_slug = scored[0]["model"] if scored else "unknown"
    report_dir = get_model_dir(model_slug, base_dir) / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    valid = [s for s in scored if s["score_total"] is not None]
    all_ok  = [r for r in all_results if r.get("status") == "ok"]
    all_err = [r for r in all_results if r.get("status") != "ok"]
    domains = sorted(set(s["domain"] for s in valid), key=lambda d: -np.mean([s["score_total"] for s in valid if s["domain"]==d]))
    dim_keys = [f"score_{d.lower().replace(' ', '_')}" for d in DIMENSIONS]

    overall_mean = np.mean([s["score_total"] for s in valid]) if valid else 0
    overall_pct  = overall_mean / MAX_TOTAL_SCORE * 100

    lines = [
        f"# DeepResearch Benchmark — Run Report",
        f"",
        f"**Run ID:** `{run_id}`  ",
        f"**Model:** `{model_slug}`  ",
        f"**Sheet:** Core  ",
        f"**Total tasks:** {len(all_results)}  ",
        f"**Completed (ok):** {len(all_ok)}  ",
        f"**Errors:** {len(all_err)}  ",
        f"**Scored:** {len(valid)}  ",
        f"",
        f"---",
        f"",
        f"## Overall Score",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Mean total score | **{overall_mean:.2f} / {MAX_TOTAL_SCORE}** |",
        f"| Mean score % | **{overall_pct:.1f}%** |",
        f"| Median total score | {np.median([s['score_total'] for s in valid]):.1f} |",
        f"| Min / Max | {min(s['score_total'] for s in valid)} / {max(s['score_total'] for s in valid)} |",
        f"",
        f"---",
        f"",
        f"## Score by Domain",
        f"",
        f"| Domain | n | Mean | Std | Min | Max |",
        f"|--------|---|------|-----|-----|-----|",
    ]
    for dom in domains:
        vals = [s["score_total"] for s in valid if s["domain"] == dom]
        lines.append(f"| {dom} | {len(vals)} | {np.mean(vals):.2f} | {np.std(vals):.2f} | {min(vals)} | {max(vals)} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## Score by Dimension",
        f"",
        f"| Dimension | Mean (0–2) | % of max |",
        f"|-----------|-----------|---------|",
    ]
    for dim, k in zip(DIMENSIONS, dim_keys):
        vals = [s[k] for s in valid if s[k] is not None]
        mean_v = np.mean(vals) if vals else 0
        lines.append(f"| {dim} | {mean_v:.2f} | {mean_v/MAX_DIM_SCORE*100:.1f}% |")

    token_vals = [s["token_usage_total"] for s in scored if s.get("token_usage_total")]
    if token_vals:
        lines += [
            f"",
            f"---",
            f"",
            f"## Token Usage",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total tokens used | {sum(token_vals):,} |",
            f"| Mean tokens / task | {np.mean(token_vals):.0f} |",
            f"| Max tokens / task | {max(token_vals):,} |",
        ]

    lines += [
        f"",
        f"---",
        f"",
        f"## Plots",
        f"",
        f"![Score by domain]({plot_dir}/01_score_by_domain.png)",
        f"![Score by dimension]({plot_dir}/02_score_by_dimension.png)",
        f"![Score distribution]({plot_dir}/03_score_distribution.png)",
        f"![Domain × Dimension heatmap]({plot_dir}/04_heatmap_domain_dimension.png)",
        f"",
        f"---",
        f"",
        f"## Error Summary",
        f"",
    ]
    if all_err:
        from collections import Counter
        err_msgs = Counter(r.get("error_message", "unknown")[:80] for r in all_err)
        lines += [f"| Error | Count |", f"|-------|-------|"]
        for msg, cnt in err_msgs.most_common():
            lines.append(f"| `{msg}` | {cnt} |")
    else:
        lines.append("No errors.")

    report_path = report_dir / f"report_{run_id}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", required=True, type=Path)
    parser.add_argument("--skip-scoring", action="store_true")
    parser.add_argument("--rescore-nulls", action="store_true",
                        help="Re-score only tasks with all-null dimensions")
    parser.add_argument("--rescore-long", action="store_true",
                        help="Re-score tasks whose response_text > 6000 chars (old truncation limit)")
    args = parser.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key and not args.skip_scoring:
        raise SystemExit("OPENROUTER_API_KEY required")

    run_id   = args.jsonl.stem.replace("run_", "")
    base_dir = args.jsonl.parent.parent.parent  # drb_clone/

    print(f"Loading results from {args.jsonl}")
    all_results = load_results(args.jsonl)
    ok_results  = [r for r in all_results if r.get("status") == "ok" and r.get("response_text")]
    print(f"  {len(ok_results)} ok results to score (out of {len(all_results)} total)")

    model_slug  = ok_results[0]["model"] if ok_results else "unknown"
    scores_path = get_model_dir(model_slug, base_dir) / "scores" / f"scores_{run_id}.jsonl"

    if args.rescore_long and scores_path.exists():
        print("Re-scoring tasks with responses > 6000 chars...")
        existing  = [json.loads(l) for l in open(scores_path) if l.strip()]
        long_ids  = {r["task_id"] for r in ok_results if len(r.get("response_text", "")) > 6000}
        print(f"  {len(long_ids)} long-response tasks")
        rescored_map = {s["task_id"]: s for s in run_scoring([r for r in ok_results if r["task_id"] in long_ids], api_key)}
        scored = [rescored_map.get(s["task_id"], s) for s in existing]
        write_outputs(scored, run_id, base_dir)
        print(f"  Merged scores written to {scores_path}")

    elif args.rescore_nulls and scores_path.exists():
        print("Re-scoring null-dimension tasks only...")
        existing = [json.loads(l) for l in open(scores_path) if l.strip()]
        null_ids = {s["task_id"] for s in existing if s.get("score_coverage") is None}
        print(f"  {len(null_ids)} tasks with null scores")
        rescored_map = {s["task_id"]: s for s in run_scoring([r for r in ok_results if r["task_id"] in null_ids], api_key)}
        scored = [rescored_map.get(s["task_id"], s) for s in existing]
        write_outputs(scored, run_id, base_dir)
        print(f"  Merged scores written to {scores_path}")

    elif scores_path.exists() and not args.skip_scoring:
        print(f"Scores already exist — loading: {scores_path}")
        scored = [json.loads(l) for l in open(scores_path) if l.strip()]

    else:
        print("Scoring responses with DeepSeek...")
        scored = run_scoring(ok_results, api_key)
        write_outputs(scored, run_id, base_dir)
        print(f"  Scores written to {scores_path}")

    print("Generating plots...")
    plot_dir = make_plots(scored, run_id, base_dir)
    print(f"  Plots: {plot_dir}")

    print("Writing report...")
    report_path = make_report(scored, all_results, run_id, plot_dir, base_dir)
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
