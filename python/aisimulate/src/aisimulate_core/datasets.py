# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compatibility shim; the implementation lives in :mod:`aisimulate_core.data`."""

from aisimulate_core.data import (
    Artifact,
    Category,
    CategoryIndex,
    CategoryReference,
    DatasetIndex,
    Digest,
    Entry,
    Identity,
    Manifest,
    check_dataset,
    check_manifest,
    configuration_id,
    prepare_execution_profile,
)

__all__ = [
    "Artifact",
    "Category",
    "CategoryIndex",
    "CategoryReference",
    "DatasetIndex",
    "Digest",
    "Entry",
    "Identity",
    "Manifest",
    "check_dataset",
    "check_manifest",
    "configuration_id",
    "prepare_execution_profile",
]
