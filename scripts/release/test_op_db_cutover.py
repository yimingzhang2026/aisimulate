# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Go/no-go criteria of the op database cutover gate."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import op_db_cutover as cutover

SHA = "a" * 40


def _evidence(tmp_path, **overrides):
    root = tmp_path / "snap" / "catalog"
    root.mkdir(parents=True)
    (root / "dataset.json").write_text("{}")
    (root / "op-latency.json").write_text("[]")
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    parity = {
        "schema": cutover.PARITY_SCHEMA,
        "ok": True,
        "gates": {"rows": True, "lookup": True, "predictions": True, "offline": True},
        "predictions": {
            "usable_scenarios": 11,
            "mismatches": [],
            "max_abs_diff_ms": 0.0,
            "tree_run_used_loaded_root_only": True,
        },
        "rows": {"ok": True, "row_equal_tables": 2, "rows": 5},
        "tree_catalog_sha256": sha(root / "dataset.json"),
        "tree_op_index_sha256": sha(root / "op-latency.json"),
    }
    parity.update(overrides)
    (tmp_path / "parity.json").write_text(json.dumps(parity))
    (tmp_path / "drill.json").write_text(json.dumps({"schema": cutover.DRILL_SCHEMA, "ok": True}))
    return tmp_path


def _run(tmp_path, *extra):
    return cutover.main(
        [
            "preflight",
            "--phase",
            "flip",
            "--parity",
            str(tmp_path / "parity.json"),
            "--drill",
            str(tmp_path / "drill.json"),
            "--dataset-root",
            str(tmp_path / "snap"),
            "--revision",
            SHA,
            "--previous-release",
            "0.13.0",
            *extra,
        ]
    )


def _failed(capsys):
    out = json.loads(capsys.readouterr().out)
    return {c["id"] for c in out["criteria"] if not c["ok"]}


def test_go_when_evidence_is_complete(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cutover, "NOTES_MARKER", "# ")  # any release doc heading
    _evidence(tmp_path)
    assert _run(tmp_path) == 0
    assert _failed(capsys) == set()


def test_no_go_on_prediction_drift_and_stale_catalog(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cutover, "NOTES_MARKER", "# ")
    _evidence(tmp_path, tree_catalog_sha256="0" * 64)
    report = json.loads((tmp_path / "parity.json").read_text())
    report["predictions"]["max_abs_diff_ms"] = 1e-9
    (tmp_path / "parity.json").write_text(json.dumps(report))
    assert _run(tmp_path) == 1
    assert {"prediction-exact", "published-equals-validated"} <= _failed(capsys)


def test_no_go_without_release_notes_or_full_sha(tmp_path, capsys):
    _evidence(tmp_path)
    assert (
        cutover.main(
            [
                "preflight",
                "--phase",
                "flip",
                "--parity",
                str(tmp_path / "parity.json"),
                "--drill",
                str(tmp_path / "drill.json"),
                "--dataset-root",
                str(tmp_path / "snap"),
                "--revision",
                "0" * 40,
                "--previous-release",
                "0.13.0",
            ]
        )
        == 1
    )
    assert {"pin-is-full-sha"} <= _failed(capsys)


def test_remove_phase_requires_soak_evidence(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cutover, "NOTES_MARKER", "# ")
    _evidence(tmp_path)
    assert _run(tmp_path) == 0
    capsys.readouterr()
    args = ["--phase", "remove", "--flip-release", "0.14.0"]
    code = cutover.main(
        [
            "preflight",
            *args,
            "--parity",
            str(tmp_path / "parity.json"),
            "--drill",
            str(tmp_path / "drill.json"),
            "--dataset-root",
            str(tmp_path / "snap"),
            "--revision",
            SHA,
            "--previous-release",
            "0.14.0",
        ]
    )
    assert code == 1 and "soak-evidence" in _failed(capsys)


def test_steps_only_print(capsys):
    assert cutover.main(["steps", "--phase", "flip", "--revision", SHA, "--previous-release", "0.13.0"]) == 0
    text = capsys.readouterr().out
    assert "NOT EXECUTED" in text and "unset AISIM_DATASET" in text and "0.13.0" in text
