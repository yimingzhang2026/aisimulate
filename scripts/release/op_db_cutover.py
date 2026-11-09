#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Op database cutover gate and runbook (AISIM-2342). Read-only: it checks evidence and prints steps.

Nothing here edits files, runs a step, uploads, or changes a default; ``steps`` prints commands for a human to
review and run. Two phases, released separately so a rollback is always possible:

* ``flip``: the release ships the Hugging Face pin as the default op data source and still ships the packaged data.
  Rollback is unsetting the pin (the packaged path is still in the wheel).
* ``remove``: a later release drops production op data from the wheel (test fixtures stay). The packaged path no
  longer exists, so rollback is the previous release or the previous immutable dataset revision.

    python scripts/release/op_db_cutover.py preflight --phase flip --parity parity.json --drill drill.json \\
        --dataset-root /path/to/snapshot --revision <40-hex> --previous-release 0.13.0
    python scripts/release/op_db_cutover.py steps --phase flip --revision <40-hex> --previous-release 0.13.0

``preflight`` exits 0 only when every go/no-go criterion holds. Evidence comes from
``python/aisimulate/tools/perf_database/op_database_parity.py`` (``run`` and ``drill``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEMS_DATA = ROOT / "python/aisimulate/src/aisimulate_core/systems/data"
RELEASE_DOC = ROOT / "docs/ci/release.md"
NOTES_MARKER = "## Operation data cutover"
MIN_SCENARIOS = 10
PARITY_SCHEMA = "aisim-op-parity-report/v1"
DRILL_SCHEMA = "aisim-op-rollback-drill/v1"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+([.\-+][0-9A-Za-z.\-+]+)?$")


def _load(path: Path | None) -> dict | None:
    try:
        return json.loads(Path(path).read_text()) if path else None
    except (OSError, ValueError):
        return None


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def criteria(args: argparse.Namespace) -> list[dict]:
    """Each go/no-go criterion as ``{id, ok, detail}``."""
    parity, drill = _load(args.parity), _load(args.drill)
    out: list[dict] = []

    def add(cid: str, ok: bool, detail: str) -> None:
        out.append({"id": cid, "ok": bool(ok), "detail": detail})

    p = parity or {}
    gates = p.get("gates") or {}
    add("parity-report", p.get("schema") == PARITY_SCHEMA and bool(p.get("ok")), "report present, schema ok, ok=true")
    add("parity-gates", bool(gates) and all(gates.values()), f"rows/lookup/predictions/offline = {gates}")
    pred = p.get("predictions") or {}
    add(
        "prediction-coverage",
        pred.get("usable_scenarios", 0) >= MIN_SCENARIOS and not pred.get("mismatches", ["?"]),
        f"{pred.get('usable_scenarios')} usable scenarios (need >= {MIN_SCENARIOS}), "
        f"{len(pred.get('mismatches') or [])} mismatches",
    )
    add(
        "prediction-exact",
        pred.get("max_abs_diff_ms") == 0.0 and pred.get("tree_run_used_loaded_root_only") is True,
        f"max_abs_diff_ms={pred.get('max_abs_diff_ms')}, loaded root only={pred.get('tree_run_used_loaded_root_only')}",
    )
    rows = p.get("rows") or {}
    add("rows-equal", bool(rows.get("ok")) and rows.get("row_equal_tables", 0) > 0, f"{rows.get('rows')} rows hashed")
    add("rollback-drill", bool(drill) and drill.get("schema") == DRILL_SCHEMA and drill.get("ok") is True, "drill ok")

    add("pin-is-full-sha", bool(_SHA.match(args.revision or "")) and set(args.revision) != {"0"}, args.revision or "")
    root = Path(args.dataset_root) if args.dataset_root else None
    catalog = _sha256(root / "catalog/dataset.json") if root else None
    index = _sha256(root / "catalog/op-latency.json") if root else None
    add(
        "published-equals-validated",
        catalog is not None and catalog == p.get("tree_catalog_sha256") and index == p.get("tree_op_index_sha256"),
        "catalog and op-latency index of the pinned snapshot equal the ones the parity run validated",
    )
    add("previous-release-named", bool(_VERSION.match(args.previous_release or "")), args.previous_release or "")
    notes = RELEASE_DOC.read_text() if RELEASE_DOC.is_file() else ""
    add("release-notes-written", NOTES_MARKER in notes, f"'{NOTES_MARKER}' section in docs/ci/release.md")

    packaged = any(SYSTEMS_DATA.rglob("*.parquet")) if SYSTEMS_DATA.is_dir() else False
    if args.phase == "flip":
        add("flip-keeps-packaged-data", packaged, "packaged op data still in the tree (rollback = unset the pin)")
    else:
        soak = Path(args.soak_evidence) if args.soak_evidence else None
        add("flip-release-named", bool(_VERSION.match(args.flip_release or "")), args.flip_release or "")
        add("soak-evidence", bool(soak and soak.is_file()), str(soak) if soak else "no --soak-evidence file")
        add(
            "previous-release-keeps-data",
            bool(args.flip_release) and args.previous_release == args.flip_release,
            "--previous-release is the flip release, which still ships packaged data and stays installable",
        )
    return out


def steps(phase: str, revision: str, previous: str, flip_release: str | None) -> list[str]:
    pin = f"ai-dynamo/aisim-data@{revision}"
    if phase == "flip":
        return [
            "# Cutover phase 1 (flip). NOT EXECUTED by this script; review, then run by hand.",
            "# 0. Go/no-go: preflight --phase flip must exit 0.",
            "# 1. Publish the audited tree (human, protected credentials). The harness validated this exact catalog:",
            "python python/aisimulate/tools/perf_database/publish_op_latency_tree.py audit --out <tree>",
            f"#    Upload <tree> to ai-dynamo/aisim-data and record the commit SHA = {revision}.",
            "# 2. Soak the opt-in pin on CI and a pilot host before changing any default:",
            f"export AISIM_DATASET={pin} AISIM_DATA_CATEGORIES=fpm,op-latency",
            "# 3. Release PR (one reviewed change, no data removal): make that pin the shipped default",
            "#    (packaged pin file + pin_from_environment fallback), keep systems/data, add release notes.",
            "# 4. After release: run op_database_parity.py run and drill against the PUBLISHED revision.",
            "# ROLLBACK (instant, no reinstall): unset the pin.",
            "unset AISIM_DATASET AISIM_DATA_LOCAL AISIM_DATA_CATEGORIES AISIM_DATA_OFFLINE",
            "#    or set the shipped-default opt-out; predictions return to the packaged path bit-identically (drill).",
            f"#    Last resort: pip install aisimulate=={previous}  (never delete or yank {previous}).",
        ]
    return [
        "# Cutover phase 2 (remove). NOT EXECUTED by this script; review, then run by hand.",
        f"# 0. Go/no-go: preflight --phase remove must exit 0; {flip_release or '<flip release>'} soaked.",
        "# 1. Release PR: drop production op data from the wheel (maturin include of systems/data/**), keep the small",
        "#    test fixtures and specs/profiles, run scripts/ci/measure_wheel_data.py --wheel to confirm the size drop.",
        "# 2. The default pin must be a full SHA; offline hosts: aisimulate data fetch ..., then copy the cache.",
        "# ROLLBACK: the packaged path is gone from this release, so choose one:",
        f"#    a) pip install aisimulate=={previous}  (still ships packaged data; keep it on the index),",
        "#    b) pin the previous immutable dataset revision: AISIM_DATASET=ai-dynamo/aisim-data@<previous-sha>.",
        f"#    The git tag for {previous} and the dataset revision {revision} are never force-moved or deleted.",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "steps"):
        p = sub.add_parser(name)
        p.add_argument("--phase", choices=("flip", "remove"), required=True)
        p.add_argument("--revision", required=True, help="full commit SHA of the published dataset")
        p.add_argument("--previous-release", required=True, help="release kept available for rollback")
        p.add_argument("--flip-release", help="remove phase: the release that made the pin the default")
        if name == "preflight":
            p.add_argument("--parity", type=Path, required=True)
            p.add_argument("--drill", type=Path, required=True)
            p.add_argument("--dataset-root", type=Path, required=True, help="local snapshot of the pinned revision")
            p.add_argument("--soak-evidence", type=Path)
    args = parser.parse_args(argv)
    if args.command == "steps":
        print("\n".join(steps(args.phase, args.revision, args.previous_release, args.flip_release)))
        return 0
    results = criteria(args)
    go = all(r["ok"] for r in results)
    print(json.dumps({"phase": args.phase, "go": go, "criteria": results}, indent=2))
    return 0 if go else 1


if __name__ == "__main__":
    sys.exit(main())
