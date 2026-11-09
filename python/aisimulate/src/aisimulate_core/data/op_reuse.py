# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Resolve operation-table reuse relationships from published catalog files only.

Reads ``catalog/op-latency-reuse.parquet`` (declared per-version reuse, donors already resolved to manifests),
``data/op-latency/perf_data_reuse_manifest.parquet`` (cross-backend kernel-source sharing) and
``data/op-latency/query_versions.parquet`` (queryable version slots). No payload tables are opened, so it works
on a download that holds only these small files. Offline; no network access.
"""

from pathlib import Path

from aisimulate_core.data.op_publish import (
    DATA_PREFIX,
    DECLARED_REUSE_PATH,
    OP_DECLARED_REUSE_SCHEMA_ID,
    OP_QUERY_VERSIONS_SCHEMA_ID,
    OP_REUSE_MANIFEST_SCHEMA_ID,
    QUERY_VERSIONS_NAME,
    REUSE_MANIFEST_NAME,
)
from aisimulate_core.data.parquet import read_parquet


class OpReuseCatalog:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def declared(
        self,
        hardware: str,
        framework: str,
        version: str,
        *,
        family: str | None = None,
        table: str | None = None,
    ) -> list[dict]:
        """Reuse declarations of a consumer version: which donor version/manifest supplies each table."""
        rows = read_parquet(self.root / DECLARED_REUSE_PATH, OP_DECLARED_REUSE_SCHEMA_ID).to_pylist()
        return [
            r
            for r in rows
            if (r["hardware"], r["framework"], r["version"]) == (hardware, framework, version)
            and (family is None or r["family"] == family)
            and (table is None or r["table"] == table)
        ]

    def unresolved(self) -> list[dict]:
        """Declarations whose donor manifest or donor table is not published."""
        rows = read_parquet(self.root / DECLARED_REUSE_PATH, OP_DECLARED_REUSE_SCHEMA_ID).to_pylist()
        return [r for r in rows if r["status"] != "resolved"]

    def kernel_groups(self, op_file: str, kernel_source: str | None = None) -> list[dict]:
        """Cross-backend sharing groups: systems and frameworks that produce rows for a kernel source."""
        path = self.root / DATA_PREFIX / f"{REUSE_MANIFEST_NAME}.parquet"
        rows = read_parquet(path, OP_REUSE_MANIFEST_SCHEMA_ID).to_pylist()
        return [
            r
            for r in rows
            if r["op_file"] == op_file and (kernel_source is None or r["kernel_source"] == kernel_source)
        ]

    def version_slots(self, system: str, framework: str) -> dict[str, str | None]:
        """``{"current": ..., "previous": ...}`` for a system and framework (system override wins)."""
        path = self.root / DATA_PREFIX / f"{QUERY_VERSIONS_NAME}.parquet"
        rows = read_parquet(path, OP_QUERY_VERSIONS_SCHEMA_ID).to_pylist()
        for scope, want_system in (("overrides", system), ("defaults", None)):
            for r in rows:
                if r["scope"] == scope and r["framework"] == framework and r["system"] == want_system:
                    return {"current": r["current"], "previous": r["previous"]}
        raise KeyError(f"no queryable version slots for {system}/{framework}")
