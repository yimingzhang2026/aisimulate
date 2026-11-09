# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The evaluator's dataset library is used even when the wheel under test predates it (AISIM-2338)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_data_library_comes_from_the_evaluator_when_the_wheel_lacks_it(tmp_path: Path) -> None:
    wheel = tmp_path / "site-packages/aisimulate_core"
    wheel.mkdir(parents=True)
    (wheel / "__init__.py").write_text("WHEEL = True\n")  # an old wheel: no aisimulate_core.data at all
    (wheel / "sdk.py").write_text("NATIVE = 'from the wheel'\n")
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); sys.path.insert(1, sys.argv[2])\n"
        "import scripts.fpm_accuracy.evaluator_library\n"
        "import aisimulate_core, aisimulate_core.data.fetch as fetch, aisimulate_core.sdk as sdk\n"
        "assert aisimulate_core.WHEEL and sdk.NATIVE == 'from the wheel'\n"
        "assert fetch.__file__.startswith(sys.argv[2]), fetch.__file__\n"
        "print('ok')\n"
    )
    # sys.argv[1]: the fake wheel; sys.argv[2]: not a path entry for aisimulate_core, only the repo root
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(tmp_path / "site-packages"), str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONHASHSEED": "0"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
