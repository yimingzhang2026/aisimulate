# InferenceX cache to aisim-e2e/v1: full-cohort parity (AISIM-2332)

Inputs: private cache `ai-dynamo/aisim-infx-cache` at the pinned revision
`8ec77d043d236ae92aa0cee6a9896f8195ea7718` (7,743 observations, 187,347 metric rows, `e2e-source-index/v1`);
frozen legacy cohort: InferenceX `db-dump/2026-09-28` (85,309 benchmark rows) selected with
`gym-resolved-config-v3`. Nothing was written to Hugging Face; the converted dataset is local only.
Machine-readable results: [`data-parity.json`](data-parity.json), [`cohort-parity.json`](cohort-parity.json).
Reproduce with `aisimulate_core.data.migrate_infx` and `scripts/e2e_accuracy/migrate_infx_parity.py`.

## Result in one table

| Dimension | Pinned HF path vs raw-backed aisim-e2e | Typed tables only |
| --- | --- | --- |
| Observation identities, record hashes, source config IDs | identical (7,743) | identical |
| Membership / snapshot | identical; legacy snapshot ID kept | identical |
| Metric values, units | 187,347 cached rows: max relative difference 0.0 | same |
| Provenance (run URL, image, date, raw record) | identical, raw bytes hash-linked | same |
| Selected cohort, exclusions, freshness and image decisions | identical (2,855 selected; 3,306 filter, 1,009 stale, 572 image, 1 row) | identical |
| Resolved deployment evidence (coverage) | identical for all 2,855 points (1,970 resolved) | **differs for 2,060 points; resolved falls to 1,635** |
| Reviewed MTP evidence bindings | 872 / 872 | **160 / 872** |
| Score inputs (mean TTFT/TPOT/E2EL, per-GPU throughput) | identical (0 of 14,275 differ) | identical |
| Predictions and scores | not re-executed (no wheel); inputs digest-identical, see limits | not equal (coverage differs) |

The local cache copy equals what the current HF reader downloads from that revision (`live_current_path`).

## Decisions that change the schema or identity (need acceptance)

1. **Identity rule.** Under the 2331 identity, 1,565 upstream source configurations collapse to 1,438
   `configuration_id`s because dp-attention, multinode and offload differ but are not in the identity.
   `identity_settings` now carries `is_multinode`, `dp_attention` (booleans, never degrees) and `offload_mode`.
2. **Parallelism reported under metrics.** The source reports `pp`, `pcp_size`, `dcp_size` (and per-role variants)
   inside `metrics`; they are now identity dimensions `pp`, `cp`, `dcp`. One source configuration can therefore span
   several `configuration_id`s (2 cases); `source_config_id` stays per observation.
3. **Telemetry.** 21 source configurations differ only in a GPU-telemetry list (`workers`); 4 `configuration_id`s
   merge them (explained, `source_config_id` per observation keeps upstream grouping).
4. **Result: 1,546 configurations** (cache: 1,565 source configurations).

## Differences, all explained (data level, `unexplained` is empty)

| Code | Count | Reason |
| --- | --- | --- |
| `identity.configuration_ids_new` | 1,546 | `cfg-<sha256>` replaces `hf:<sha256>` |
| `identity.configuration_merge_telemetry` | 4 | see 3 |
| `identity.configuration_split_parallelism` | 2 | see 2 |
| `metric.timing_boundary_null` | 187,347 | cache stamped "unknown"; schema stores null |
| `metric.explicit_missing_rows` | 10,942 | required statistic not reported is stored `missing`, never zero |
| `metric.interactivity_added` | 41,154 | `*_intvty` was dropped by the cache normalizer; now mapped, values verbatim |
| `metric.source_key_parallelism` | 9,081 | degrees moved to identity (see 2) |
| `metric.source_key_unmapped` | 78,402 | 93 other source keys (power, qps, token counts, hit rates, ...) have no mapping; only in the raw artifact, the cache had no row either |

Converter fixes found by the parity run: `p99.9_*` statistics were unmapped; one gb200 row reports decode tp/ep = 0
(treated as unknown, with an evidence gap).

## Findings that need a decision

1. **Typed tables are not enough for the current evaluator.** Fields without a typed home: `recipe_fingerprint`
   (1,206 observations), `workers` telemetry (21 configs), the prefill-side fields of aggregated rows (1,762 selected
   rows), unmapped metrics (1,614 selected rows) and the zero-degree row. The reviewed bindings hash the complete row,
   so a typed-only adapter loses 712 MTP bindings and 335 points change resolution status. The raw-backed adapter
   (typed tables plus the hash-linked raw-output artifact) is exact. Either keep reading the raw artifact in the
   evaluator, or add `recipe_fingerprint` and the missing mappings to the schema before cutover.
2. **File count.** One raw-output artifact per observation gives 12,401 files (447 in the cache; 58.9 MB apparent,
   105 MB on disk). Bundling raw output per configuration would cut this by about 5x.
3. **Predictions and scores were not re-executed** (no wheel build here). The 2,855 selected rows, their resolved
   deployments and evidence are digest-identical, so the deterministic predictors receive identical input; a campaign
   run on the converted data is still the final proof.

## Legacy cohort (db-dump 2026-09-28, v3: 3,320 selected)

The HF path and the migrated dataset give identical results against it (same numbers in both blocks of
`cohort-parity.json`), so none of these differences comes from the migration:

- 7,135 observations shared; 78,174 database-only (older history), 608 HF-only.
- Selected in both: 2,829 (matches the earlier review); database-only 491 (433 not in the HF current view, 58 stale
  there); HF-only 26 (9 absent from the dump, 17 where the dump superseded the image).
- 223 shared rows differ in non-transport fields: 217 have `offload_mode` `on` in the API but absent in the dump,
  6 lack producer run metadata on the HF side. These were already outside the reviewed 2,829 overlap.

## Rollback

The cache is untouched. Rollback is the previous adapter plus the existing pin
(`.github/e2e-accuracy-dataset.json`); old HF commits keep the old paths.

Converted datasets (local, not published): pinned revision 1,546 configurations, 7,743 observations, 239,443 metric
rows; current `main` (37cdb031, 8,007 observations) converts with no unexplained difference either.
