# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import pytest
from pydantic import ValidationError

from aisimulate_core.data.gpu_time import (
    GpuTime,
    SlurmParseError,
    check_gpu_time,
    gpu_time_from_sacct,
    gpu_time_ok,
    parse_sacct,
)

pytestmark = pytest.mark.unit

HEADER = "JobID|JobName|State|Submit|Start|End|ElapsedRaw|Elapsed|NNodes|AllocTRES"


def _sacct(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


MAIN = (
    "100|bench|COMPLETED|2026-01-01T00:00:00|2026-01-01T01:00:00|2026-01-01T02:00:00"
    "|3600|01:00:00|2|billing=16,gres/gpu:h100=16,node=2"
)


def test_missing_is_not_zero():
    zero = GpuTime(authority="measured", gpu_type="h100", gpu_count=8, wall_seconds=0)
    assert zero.gpu_seconds == 0 and zero.is_recorded
    assert check_gpu_time(zero, "qualification") == []
    for missing in (None, GpuTime.unknown()):
        assert check_gpu_time(missing, "archival")[0].severity == "warn"
        assert check_gpu_time(missing, "qualification")[0].severity == "error"
        assert gpu_time_ok(check_gpu_time(missing, "archival"))
        assert not gpu_time_ok(check_gpu_time(missing, "qualification"))


def test_unknown_cannot_carry_zero():
    with pytest.raises(ValidationError):
        GpuTime(authority="unknown", wall_seconds=0)
    with pytest.raises(ValidationError):
        GpuTime(authority="measured", gpu_count=8)


def test_gpu_seconds_derived_and_checked():
    t = GpuTime(authority="declared", gpu_type="b200", gpu_count=4, wall_seconds=10)
    assert t.gpu_seconds == 40
    with pytest.raises(ValidationError):
        GpuTime(authority="declared", gpu_count=4, wall_seconds=10, gpu_seconds=39)


def test_declared_warns_at_qualification_only():
    t = GpuTime(authority="declared", gpu_type="b200", gpu_count=1, wall_seconds=5)
    assert [f.code for f in check_gpu_time(t, "qualification")] == ["gpu_time.declared"]
    assert check_gpu_time(t, "archival") == []


def test_json_round_trip():
    t = gpu_time_from_sacct(_sacct(MAIN))
    assert GpuTime.model_validate_json(t.model_dump_json(by_alias=True)) == t


def test_slurm_job_record_populates_gpu_time():
    t = gpu_time_from_sacct(_sacct(MAIN, "100.batch|batch|COMPLETED||||3600|01:00:00|2|gres/gpu=16"))
    assert t.authority == "measured"
    assert (t.gpu_type, t.gpu_count, t.wall_seconds) == ("h100", 16, 3600)
    assert t.gpu_seconds == 3600 * 16
    assert t.node_hours == 2.0
    assert t.failed is None and t.retried is None
    assert t.source["job_ids"] == "100"


def test_queue_wait_excluded():
    # Submitted 1 day before start; only elapsed counts.
    row = "7|b|COMPLETED|2025-12-30T00:00:00|2026-01-01T00:00:00|2026-01-01T00:10:00|600|00:10:00|1|gres/gpu=8"
    t = gpu_time_from_sacct(_sacct(row), gpu_type="b200")
    assert t.wall_seconds == 600 and t.gpu_type == "b200"


def test_failed_and_retried_kept_separate():
    rows = [
        "1|b|FAILED||||100|00:01:40|1|gres/gpu=8",
        "2|b|REQUEUED||||50|00:00:50|1|gres/gpu=8",
        "3|b|COMPLETED||||200|00:03:20|1|gres/gpu=8",
    ]
    t = gpu_time_from_sacct(_sacct(*rows))
    assert t.wall_seconds == 200 and t.gpu_seconds == 1600
    assert (t.failed.count, t.failed.gpu_seconds) == (1, 800)
    assert (t.retried.count, t.retried.gpu_seconds) == (1, 400)


def test_elapsed_fallback_and_days():
    text = "JobID|State|Elapsed|NNodes|AllocTRES\n9|COMPLETED|1-02:00:30|1|gres/gpu=1\n"
    assert parse_sacct(text)[0].elapsed_seconds == 26 * 3600 + 30


def test_no_gpu_in_tres_is_zero_but_empty_tres_is_error():
    t = gpu_time_from_sacct(_sacct("5|b|COMPLETED||||60|00:01:00|1|cpu=4,node=1"))
    assert t.gpu_count == 0 and t.gpu_seconds == 0
    with pytest.raises(SlurmParseError, match="AllocTRES"):
        parse_sacct(_sacct("5|b|COMPLETED||||60|00:01:00|1|"))


@pytest.mark.parametrize("state", ["RUNNING", "PENDING"])
def test_unfinished_job_rejected(state):
    with pytest.raises(SlurmParseError, match=state):
        parse_sacct(_sacct(f"5|b|{state}||||60|00:01:00|1|gres/gpu=1"))


def test_only_failed_jobs_rejected():
    with pytest.raises(SlurmParseError, match="COMPLETED"):
        gpu_time_from_sacct(_sacct("5|b|FAILED||||60|00:01:00|1|gres/gpu=1"))


def test_headerless_needs_fields():
    row = "5|COMPLETED|60|1|gres/gpu=2"
    with pytest.raises(SlurmParseError):
        parse_sacct(row)
    jobs = parse_sacct(row, fields=["JobID", "State", "ElapsedRaw", "NNodes", "AllocTRES"])
    assert jobs[0].gpu_count == 2


def test_tres_untyped_and_typed_not_double_counted():
    row = "5|b|COMPLETED||||60|00:01:00|1|gres/gpu=8,gres/gpu:b200=8,node=1"
    t = gpu_time_from_sacct(_sacct(row))
    assert (t.gpu_count, t.gpu_type) == (8, "b200")
