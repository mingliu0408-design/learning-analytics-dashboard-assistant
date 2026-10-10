"""Render the four authorized figures from hash-bound aggregate results only.

Python/Matplotlib is the exclusive drawing and export backend. No restricted
identity table, response, rationale, or Human rating is read by this script.
PDF/SVG remain vector with editable text; PNG is 300 dpi and TIFF is 600 dpi.
"""
from __future__ import annotations

import io
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.spines import Spine
from matplotlib.text import Text
import numpy as np

from f1_common import HERE, CRITERIA, PRIMARY_OUTCOME, read_json, sha, sha_bytes, write_json, write_once_bytes
from f1_controlled_unblinding_guard import verify_entry

SKILL_SCRIPTS = Path("/Users/liuming/.codex/skills/nature-figure/scripts")
FIGURE_DIR = HERE / "figures"
DATA_NAME = "F1_FIGURE_SOURCE_DATA_V1.json"
AGGREGATE_FILES = ["C4_REAL_F1_PRIMARY_CONTRAST_RESULTS_V1.json",
                   "C4_REAL_F1_MODE_SUMMARIES_V1.json",
                   "C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1.json"]
FIGURE_IDS = ["figure_1_primary_forest", "figure_2_mode_mean_median",
              "figure_3_criterion_profile", "figure_4_mechanism_outcomes"]
width_mm = 180
EXPORT_SUFFIXES = [".pdf", ".svg", ".png", ".tiff"]
MODE_LABELS = ["C0 · Original", "C1 · Evidence", "C2 · Evidence + RAG",
               "C3 · Evidence + Memory", "C4 · Evidence + Planning", "C5 · Full C4",
               "C5 − RAG", "C5 − Memory", "C5 − Planning"]
SHORT_LABELS = ["C0", "C1", "C2", "C3", "C4", "C5", "C5\n− RAG", "C5\n− Mem", "C5\n− Plan"]
CONTRAST_LABELS = ["C1 − C0", "C2 − C1", "C3 − C1", "C4 − C1", "C5 − C1",
                   "C5 − (C5 − RAG)", "C5 − (C5 − Memory)", "C5 − (C5 − Planning)"]
CRITERION_LABELS = ["Clarity", "Personalisation", "Actionability", "Context awareness",
                    "Motivation and engagement", "Reliability", "Multi-page cohesiveness", "Error handling"]
BLUE = "#0072B2"
PURPLE = "#7B4F99"
GREY = "#C6CCD2"
GOLD = "#E69F00"


def style():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "font.size": 7.5,
        "axes.labelsize": 8, "axes.titlesize": 8.5,
        "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
        "legend.fontsize": 7, "axes.linewidth": 0.6,
        "lines.linewidth": 1.1, "pdf.fonttype": 42, "ps.fonttype": 42,
        "svg.fonttype": "none", "svg.hashsalt": "RQ3-REAL-C4-F1-20260831",
        "savefig.facecolor": "white", "figure.facecolor": "white",
        "figure.dpi": 150, "savefig.dpi": 300,
        "axes.unicode_minus": True,
    })


def source_data():
    primary, summaries, mechanism = [read_json(HERE / name) for name in AGGREGATE_FILES]
    modes = read_json(HERE / "C4_REAL_F1_PREDECLARED_ANALYSIS_PLAN_V1.json")["mode_identities"]
    return {"schema_version": "F1_FIGURE_SOURCE_DATA_V1",
            "aggregate_only": True,
            "source_hashes": {name: sha(HERE / name) for name in AGGREGATE_FILES},
            "mode_order": modes,
            "primary_contrasts": primary["records"],
            "mode_summaries": summaries["records"],
            "mechanism_modes": mechanism["modes"],
            "raw_condition_or_scenario_identities": False,
            "new_statistical_calculations": False}


def clean_axes(ax, grid=True):
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0, pad=7)
    ax.tick_params(axis="x", length=3, width=0.6)
    if grid:
        ax.grid(axis="x", color="#E7EBEF", linewidth=0.5, zorder=0)
        ax.set_axisbelow(True)


def heading(fig, title, subtitle):
    fig.text(0.035, 0.965, title, ha="left", va="top", fontsize=10, fontweight="bold")
    fig.text(0.035, 0.913, subtitle, ha="left", va="top", fontsize=7.5, color="#404850")


def forest(data):
    fig = plt.figure(figsize=(width_mm / 25.4, 118 / 25.4))
    ax = fig.add_axes([0.30, 0.15, 0.47, 0.67])
    heading(fig, "Paired response-quality comparisons", "All eight predeclared contrasts · 62 paired scenarios per contrast")
    y = np.array([8, 7, 6, 5, 4, 2, 1, 0])
    for index, (row, yy) in enumerate(zip(data["primary_contrasts"], y)):
        value = row["paired_mean_difference"]
        lo, hi = row["bootstrap"]["ci_low"], row["bootstrap"]["ci_high"]
        color = BLUE if index < 5 else PURPLE
        ax.errorbar(value, yy, xerr=[[value - lo], [hi - value]], fmt="o", markersize=4,
                    color=color, ecolor=color, capsize=3, elinewidth=1.2, zorder=3)
        ax.text(1.065, yy, f'{row["holm_adjusted_p_value"]:.4f}',
                transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=7.5)
    ax.axvline(0, color="#6A737D", linewidth=0.85, linestyle=(0, (3, 3)), zorder=1)
    ax.set(yticks=y, yticklabels=CONTRAST_LABELS, ylim=(-0.6, 9.1),
           xlim=(-0.16, 0.22), xticks=[-0.1, 0, 0.1, 0.2],
           xlabel="Paired mean difference (left − right)")
    clean_axes(ax)
    ax.text(-0.56, 8.95, "Primary add-one (m = 5)", transform=ax.get_yaxis_transform(),
            color=BLUE, fontsize=7.5, fontweight="bold", va="center")
    ax.text(-0.56, 2.9, "Targeted remove-one (m = 3)", transform=ax.get_yaxis_transform(),
            color=PURPLE, fontsize=7.5, fontweight="bold", va="center")
    ax.text(1.065, 8.95, "Holm p", transform=ax.get_yaxis_transform(),
            fontsize=7.5, fontweight="bold", va="center")
    fig.text(0.035, 0.032, "Intervals: pointwise 95% family-cluster bootstrap; 10,000 replicates, seed 20260831.",
             fontsize=7, color="#404850")
    return fig


def mode_levels(data):
    fig = plt.figure(figsize=(width_mm / 25.4, 105 / 25.4))
    ax = fig.add_axes([0.31, 0.18, 0.63, 0.62])
    heading(fig, "Nine-mode primary-outcome levels", "Mean and median of OVERALL_APPLICABLE_MEAN · n = 62 per mode")
    by_mode = {r["mode_id"]: r for r in data["mode_summaries"] if r["outcome"] == PRIMARY_OUTCOME}
    rows = [by_mode[m] for m in data["mode_order"]]
    y = np.arange(9)[::-1]
    ax.scatter([r["mean"] for r in rows], y, s=26, marker="o", color=BLUE, label="Mean", zorder=3)
    ax.scatter([r["median"] for r in rows], y, s=38, marker="|", color="#24292E", label="Median", zorder=3)
    ax.set(yticks=y, yticklabels=MODE_LABELS, ylim=(-0.6, 8.6), xlim=(4.30, 4.90),
           xticks=np.arange(4.3, 4.91, 0.1), xlabel="Judge-rated outcome (descriptive; expanded score range)")
    clean_axes(ax)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.01), ncol=2, frameon=False,
              handletextpad=0.4, columnspacing=1.3)
    fig.text(0.035, 0.035, "No inferential intervals or ranking claim. Absolute scores require the Human–Judge bias qualification.",
             fontsize=7, color="#404850")
    return fig


def criterion_profile(data):
    fig = plt.figure(figsize=(width_mm / 25.4, 125 / 25.4))
    ax = fig.add_axes([0.32, 0.245, 0.65, 0.625])
    heading(fig, "Descriptive criterion profile", "Cell: mean and applicable count · NA remains unscored · no criterion-level inference")
    lookup = {(r["mode_id"], r["outcome"]): r for r in data["mode_summaries"]}
    values = np.array([[lookup[(m, c)]["mean"] if lookup[(m, c)]["mean"] is not None else np.nan
                        for m in data["mode_order"]] for c in CRITERIA])
    cmap = plt.colormaps["Blues"].copy()
    cmap.set_bad("#ECEFF2")
    im = ax.imshow(values, vmin=1, vmax=5, cmap=cmap, aspect="auto", interpolation="nearest")
    for i, criterion in enumerate(CRITERIA):
        for j, mode in enumerate(data["mode_order"]):
            row = lookup[(mode, criterion)]
            value = row["mean"]
            label = "NA\n(n = 0)" if value is None else f'{value:.2f}\n(n = {row["applicable_score_count"]})'
            ax.text(j, i, label, ha="center", va="center", fontsize=7,
                    color="white" if value is not None and value >= 3.7 else "#202A34",
                    linespacing=1.35)
    ax.set(xticks=range(9), xticklabels=SHORT_LABELS,
           yticks=range(8), yticklabels=CRITERION_LABELS)
    ax.tick_params(axis="both", length=0, pad=7)
    ax.spines[:].set_visible(False)
    cax = fig.add_axes([0.40, 0.112, 0.49, 0.025])
    colorbar = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=[1, 2, 3, 4, 5])
    colorbar.set_label("Mean applicable criterion score", fontsize=7.5, labelpad=4)
    colorbar.outline.set_linewidth(0.5)
    cax.tick_params(labelsize=7, length=2)
    fig.text(0.035, 0.025, "Applicable counts differ across criteria and modes; secondary audits are excluded from the primary mean.",
             fontsize=7, color="#404850")
    return fig


def mechanism_outcomes(data):
    fig, axes = plt.subplots(1, 3, figsize=(width_mm / 25.4, 120 / 25.4), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.17, right=0.98, bottom=0.32, top=0.82, wspace=0.22)
    heading(fig, "Availability does not imply substantive component output",
            "Frozen replay outcomes · 62 conditions per mode · inactive conditions are outside the bars")
    rows_by_mode = {r["mode_id"]: r for r in data["mechanism_modes"]}
    rows = [rows_by_mode[m] for m in data["mode_order"]]
    y = np.arange(9)[::-1]
    specs = [
        ("a", "RAG", "rag_status_counts", [("SUPPORTED", "Supported", BLUE),
                                             ("LIMITED_EVIDENCE", "Limited evidence", GOLD),
                                             ("NO_RESULT", "No result", GREY)]),
        ("b", "Memory", "memory_status_counts", [("AVAILABLE", "Available", BLUE),
                                                   ("NO_MATCH", "No match", GREY)]),
        ("c", "Planner", "planner_status_counts", [("USED", "Used", BLUE),
                                                     ("INSUFFICIENT_EVIDENCE", "Insufficient evidence", GREY)]),
    ]
    for ax, (letter, title, field, statuses) in zip(axes, specs):
        left = np.zeros(9)
        for status, label, color in statuses:
            count = np.array([r[field].get(status, 0) for r in rows])
            ax.barh(y, count, left=left, height=0.58, color=color, edgecolor="none", label=label, zorder=2)
            left += count
        for yy, count in zip(y, left):
            ax.text(count + 0.5, yy, str(int(count)), fontsize=7, ha="left", va="center")
        ax.text(0.0, 1.055, letter, transform=ax.transAxes, fontsize=9, fontweight="bold", va="bottom")
        ax.text(0.14, 1.055, title, transform=ax.transAxes, fontsize=8.5, fontweight="bold", va="bottom")
        ax.set(xlim=(0, 25), xticks=[0, 10, 20], ylim=(-0.65, 8.65),
               xlabel="Activated conditions", yticks=y,
               yticklabels=[x.replace("\n", " ") for x in SHORT_LABELS])
        clean_axes(ax, grid=False)
        ax.legend(loc="upper left", bbox_to_anchor=(0, -0.21), frameon=False, fontsize=6.7,
                  handlelength=1.2, handletextpad=0.5, borderaxespad=0, labelspacing=0.65)
    fig.text(0.035, 0.024, "Counts describe frozen component states, not independently verified response or step correctness.",
             fontsize=7, color="#404850")
    return fig


def make_figures(data):
    style()
    return dict(zip(FIGURE_IDS, [forest(data), mode_levels(data), criterion_profile(data), mechanism_outcomes(data)]))


def export_bytes(fig, name):
    result = {}
    for suffix in EXPORT_SUFFIXES:
        extension = suffix.lstrip(".")
        buffer = io.BytesIO()
        options = {"format": extension, "facecolor": "white"}
        if extension == "pdf":
            options["metadata"] = {"Creator": "RQ3-REAL-C4-F1 offline Matplotlib", "CreationDate": None,
                                   "ModDate": None, "Title": name}
        elif extension == "svg":
            options["metadata"] = {"Date": None, "Creator": "RQ3-REAL-C4-F1 offline Matplotlib", "Title": name}
        elif extension == "png":
            png_dpi = 300
            options["dpi"] = png_dpi
            options["metadata"] = {"Software": "RQ3-REAL-C4-F1 offline Matplotlib"}
        elif extension == "tiff":
            tiff_dpi = 600
            options["dpi"] = tiff_dpi
            options["pil_kwargs"] = {"compression": "tiff_lzw"}
        fig.savefig(buffer, **options)
        result[extension] = buffer.getvalue()
    return result


def load_skill_module(name):
    spec = importlib.util.spec_from_file_location(name, SKILL_SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def backend_geometry_audit(fig, collision):
    """Inspect actual Agg-rendered text/stroke geometry; explicitly not PDF geometry."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    scale = 72 / fig.dpi
    width, height = fig.get_size_inches() * 72
    page = collision.PageGeometry(page=1, bbox=(0.0, 0.0, float(width), float(height)))
    text_sizes = []
    for text_obj in fig.findobj(match=lambda x: isinstance(x, Text)):
        if not text_obj.get_visible() or not text_obj.get_text().strip():
            continue
        b = text_obj.get_window_extent(renderer)
        if b.width == 0 or b.height == 0:
            continue
        rect = tuple(float(x * scale) for x in [b.x0, b.y0, b.x1, b.y1])
        index = len(page.texts)
        page.texts.append(collision.TextBox(index, text_obj.get_text(), rect))
        page.traces.append(collision.TraceBox(index, text_obj.get_text(), rect))
        text_sizes.append(text_obj.get_fontsize())
    for item in fig.findobj(match=lambda x: isinstance(x, (Line2D, LineCollection, Spine))):
        if not item.get_visible() or item.get_alpha() == 0:
            continue
        if isinstance(item, LineCollection):
            paths = [item.get_transform().transform(x) for x in item.get_segments()]
            linewidth = float(item.get_linewidths()[0]) if len(item.get_linewidths()) else 0
        else:
            if isinstance(item, Line2D) and item.get_linestyle() in ("None", "none", "", " "):
                continue
            paths = [item.get_transform().transform_path(item.get_path()).vertices]
            linewidth = float(item.get_linewidth())
        if linewidth <= 0:
            continue
        for vertices in paths:
            points = [(float(x * scale), float(y * scale)) for x, y in vertices if np.isfinite(x) and np.isfinite(y)]
            segments = tuple(zip(points, points[1:]))
            if not segments:
                continue
            xs, ys = zip(*points)
            page.strokes.append(collision.StrokePath(len(page.strokes), (min(xs), min(ys), max(xs), max(ys)),
                                                     linewidth, segments))
    report = collision.audit_geometries([page])
    report.update({"geometry_source": "FINAL_MATPLOTLIB_AGG_RENDERER_NOT_PDF",
                   "minimum_text_size_pt": min(text_sizes),
                   "pdf_collision_validation_claimed": False,
                   "coverage": "All visible text, page clipping, Line2D, LineCollection and spine geometry; raster/vector visual review supplements marker/fill coverage."})
    assert min(text_sizes) >= 5
    return report


def main():
    verify_entry()
    contract = read_json(HERE / "F1_FIGURE_AND_WRITING_CONTRACT_V1.json")
    assert contract["recorded_before_plotting_code"] and contract["backend"] == "PYTHON_MATPLOTLIB"
    data = source_data()
    if (HERE / DATA_NAME).exists():
        assert read_json(HERE / DATA_NAME) == data, "FROZEN_AGGREGATE_FIGURE_DATA_MISMATCH"
    else:
        write_json(HERE / DATA_NAME, data)
    FIGURE_DIR.mkdir(exist_ok=True)
    source_check = subprocess.run([sys.executable, "-B", str(SKILL_SCRIPTS / "validate_figure.py"),
                                   str(Path(__file__).resolve()), "--json"], capture_output=True, text=True)
    source_report = json.loads(source_check.stdout)
    write_json(FIGURE_DIR / "figure_source_preflight.json", source_report)
    assert source_check.returncode != 1, "FIGURE_SOURCE_PREFLIGHT_FAILED"
    alignment = load_skill_module("audit_panel_alignment")
    text_audit = load_skill_module("audit_pdf_text")
    collision = load_skill_module("audit_figure_collisions")
    output = []
    figures = make_figures(data)
    for name, fig in figures.items():
        if name == "figure_4_mechanism_outcomes":
            align = alignment.require_matplotlib_panel_alignment(fig,
                json_out=FIGURE_DIR / f"{name}.alignment.json",
                overlay_svg=FIGURE_DIR / f"{name}.alignment.svg",
                tolerance_pt=1.5, gutter_tolerance_pt=1.5, require_panel_labels=True, strict=True)
            alignment_status = align["verdict"]
        else:
            alignment_status = "NOT_APPLICABLE_SINGLE_PRIMARY_PANEL"
        rendered = backend_geometry_audit(fig, collision)
        write_json(FIGURE_DIR / f"{name}.backend_geometry.json", rendered)
        assert rendered["summary"]["fail"] == 0, f"RENDERED_GEOMETRY_FAILED: {name}"
        exports = export_bytes(fig, name)
        pdf_text = text_audit.audit_pdf(exports["pdf"], minimum_pt=5.0)
        write_json(FIGURE_DIR / f"{name}.pdf_text.json", pdf_text)
        assert pdf_text["auditable"] and not pdf_text["below_minimum"], "PDF_GLYPH_SIZE_FAILED"
        svg = ET.fromstring(exports["svg"])
        editable_text_nodes = len(svg.findall(".//{http://www.w3.org/2000/svg}text"))
        assert editable_text_nodes > 0, "SVG_HAS_NO_EDITABLE_TEXT"
        files = {}
        for extension, content in exports.items():
            target = FIGURE_DIR / f"{name}.{extension}"
            write_once_bytes(target, content)
            files[target.name] = {"sha256": sha_bytes(content), "bytes": len(content)}
        pdf_collision = subprocess.run([sys.executable, "-B", str(SKILL_SCRIPTS / "audit_figure_collisions.py"),
                                        str(FIGURE_DIR / f"{name}.pdf"), "--json-out",
                                        str(FIGURE_DIR / f"{name}.pdf_collision_tool.json")], capture_output=True, text=True)
        if pdf_collision.returncode == 2:
            pdf_collision_status = {"status": "NOT_AUDITABLE_DEPENDENCY_UNAVAILABLE", "exit_code": 2,
                "diagnostic": (pdf_collision.stderr + pdf_collision.stdout).strip(),
                "runtime_dependency": "PyMuPDF", "network_installation_attempted": False,
                "reason": "User explicitly authorizes offline work only; no installed PyMuPDF runtime is available.",
                "pdf_collision_pass_claimed": False, "alternative": "Backend geometry audit plus panel-by-panel rendered visual QA."}
            write_json(FIGURE_DIR / f"{name}.pdf_collision_tool.json", pdf_collision_status)
        else:
            assert pdf_collision.returncode == 0, "PDF_COLLISION_FAILED"
            pdf_collision_status = read_json(FIGURE_DIR / f"{name}.pdf_collision_tool.json")
        output.append({"figure_id": name, "size_mm": list(fig.get_size_inches() * 25.4),
                       "alignment_status": alignment_status, "backend_geometry_status": rendered["verdict"],
                       "minimum_rendered_pdf_font_pt": pdf_text.get("minimum_found_pt"),
                       "editable_svg_text_nodes": editable_text_nodes,
                       "pdf_collision_tool_status": pdf_collision_status.get("status", pdf_collision_status.get("verdict")),
                       "files": files})
        plt.close(fig)
    write_json(HERE / "F1_FIGURE_EXPORT_MANIFEST_V1.json", {
        "schema_version": "F1_FIGURE_EXPORT_MANIFEST_V1", "source_data_sha256": sha(HERE / DATA_NAME),
        "plotting_script_sha256": sha(__file__), "backend": "Python Matplotlib",
        "runtime_versions": {"python": sys.version.split()[0], "matplotlib": matplotlib.__version__, "numpy": np.__version__},
        "tool_hashes": {name: sha(SKILL_SCRIPTS / name) for name in
                        ["validate_figure.py", "audit_panel_alignment.py", "audit_pdf_text.py", "audit_figure_collisions.py"]},
        "figures": output, "visual_review_pending": True,
        "pdf_geometry_dependency_limit_disclosed": True,
        "new_provider_or_network_calls": 0})
    print("Four complete figures exported from aggregate data; visual review remains.")


if __name__ == "__main__":
    main()
