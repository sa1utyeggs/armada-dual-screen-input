English · [简体中文](README.zh-CN.md)

# Lower FT5452 acquisition comparison

This separately licensed experiment changes only how the existing lower-only driver groups register reads. It is excluded from application bundles. The baseline driver and its provenance stay unchanged; see [UPSTREAM](UPSTREAM) and [GPL license](../LICENSE).

`read-chunks.patch` applies to the baseline module source, SHA-256 `9fdb33c22b2241a13f3a5371e01989b54f39d3fd687865d676ea6cc7875bdaba`. The root-only `read_chunk` parameter accepts:

| Value | Acquisition |
| --- | --- |
| 1 (default) | Unchanged baseline one-register reads |
| 6 | Three-byte header, then one six-byte contact per transfer |
| 33 | One complete 33-byte frame per transfer |

Each frame snapshots the parameter once. The patch retains contact parsing/coordinates/IDs, IRQ settings, power handling and matching restrictions. It adds no motion filter or additional firmware configuration. Grouped reads may be unsupported on this bus; a failed/short transfer invalidates the trial and triggers restoration, rather than silently changing or dropping coordinates.

Compile offline with the exact prepared kernel/config/compiler and audit every imported symbol, using the existing build workflow. Keep generated source, binary, manifest, audit, source hashes and compiler records outside application bundles. Compilation and a successful read-only plan do not establish load safety or correct hardware behavior. Loading this new candidate needs separate explicit authorization.

`run_trial.py PACKAGE` performs only the existing component's compatibility/manifest checks and prints a plan. A run additionally needs `--run --experimental --folder FRESH_DIRECTORY`. Stop the input panel first and use an owned, input-free native lower window. The window provides fresh `input.json` heartbeats with monotonic `at`, an integer `contacts` count and a matching list of unique positive `ids` in landing order. After 0.2 seconds with two contacts, the trial requests `1, 6, 33, 1, 33, 6, 1`, six seconds each by default, without asking the operator to change motion at mode boundaries. The oldest contact must remain held; the second may lift and return without taking over that identity. Loss of the primary contact, extra contacts, stale status, failed I2C transfers, cancellation or timeout aborts the comparison. `cancel` in the output directory requests cancellation. The expanded passive tracer now records bus payloads too, increasing capture volume; a full comparison may reach its 32 MiB bound and abort. Do not reuse a truncated run as a completed comparison.

The runner uses the existing root-managed component's exact-kernel and checksum validation, operation lock and lower-only controller. It restores that component's original pinned experimental package on exit, including trace-shutdown failures. It does not update the installed GUI component, manage official services or create boot loading. The caller preserves/restarts only its own input panel as appropriate. The original driver must already be active before the run. See the package manifest and trial logs for what was actually validated; this is not a fix acceptance.
