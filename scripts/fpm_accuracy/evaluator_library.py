# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Bind ``aisimulate_core.data`` to this checkout, whatever AISim wheel is installed.

The accuracy campaign evaluates the AISim wheel of the *evaluated* commit, which may be an older release
branch that predates the shared dataset library. Dataset access (catalog, selection, fetch, verification) is an
evaluator concern, so it always comes from the evaluator's own checkout. Everything else in ``aisimulate_core``
(the native forward-pass SDK under test) keeps coming from the installed wheel.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "python/aisimulate/src"


def bind() -> None:
    try:
        import aisimulate_core
    except ImportError:  # no wheel: use the evaluator's source tree
        sys.path.insert(0, str(SOURCE))
        import aisimulate_core
    package = SOURCE / "aisimulate_core/data"
    loaded = sys.modules.get("aisimulate_core.data")
    if loaded is not None and Path(loaded.__file__).resolve() == package / "__init__.py":
        return
    if loaded is not None:
        for name in [n for n in sys.modules if n == "aisimulate_core.data" or n.startswith("aisimulate_core.data.")]:
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        "aisimulate_core.data", package / "__init__.py", submodule_search_locations=[str(package)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["aisimulate_core.data"] = module
    spec.loader.exec_module(module)
    aisimulate_core.data = module


bind()
