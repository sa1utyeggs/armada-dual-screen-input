# Integration with this project

Read only when the user requests program integration or changes to an existing marker. Inspect the current files before editing; this map describes the current architecture, not an immutable design.

## Source map

| Repository path | Responsibility |
| --- | --- |
| `src/armada_dual_screen_input/marker_appearance.py` | Stable style IDs, actual appearance kinds, state sprites, canvas size, common hotspot, preview bounds, mode policy, optional-artwork fallback and bounded startup caches. |
| `src/armada_dual_screen_input/marker_gpu.py` | Ring and positioning atlases, shared prepared pixels, dimensions/origin uniforms and full-buffer clearing. |
| `src/armada_dual_screen_input/marker_paint.py` | Cairo drawing and old/new damage extents for movement, pose, style and mode changes. |
| `src/armada_dual_screen_input/marker_worker.py`, `marker_native_worker.py`, `marker_gtk_worker.py`, `marker_overlay.py` | Startup argument propagation, one resolved fallback appearance, preparation and worker lifecycle. |
| `src/armada_dual_screen_input/input_settings.py`, `settings_view.py`, `panel_app.py` | Validation/persistence, draft selection, shared visible/hit geometry, preview cache, save/discard/reset. |
| `src/armada_dual_screen_input/ui_catalogs.py` | Stable English/Chinese keys and matching named placeholders; UI language remains independent of keyboard input. |
| `assets/markers/`, `tools/release.py`, `tests/test_installation.py` | Runtime assets, explicit package allowlist, and exclusion of drafts/other local data. |
| `tests/test_marker_appearance.py`, `test_marker_native.py`, `test_marker_paint.py`, `test_marker_overlay.py` | Appearance policy, atlas choice, cleanup, routing/lifecycle and damage behavior. |
| `tests/test_input_settings.py`, `test_panel_preferences.py`, `test_panel_layout.py`, `test_i18n.py`, `test_i18n_render.py`, `test_marker_colors.py` | Direct selection, persistence, bilingual layout and actual preview pixels. |

## Keep the runtime contract coherent

Add a stable configuration ID and translated choice metadata, then carry it through validation, worker arguments and appearance resolution. The ID may differ from the resolved appearance kind: both ring presets currently resolve to kind `ring`. A missing optional sprite pair must fall back coherently before activation; the selector must not present a fallback ring as a valid illustrated preview.

For each final style define its state sources or procedural geometry, canvas size, common runtime hotspot, actual per-state preview bounds and filter. Keep required values in packaged code/data. Never rely on a JSON file that exists only in ignored design evidence.

Preserve existing input coordinates, smoothing, frame caps and mode behavior. Currently, non-ring positioning styles revert to the default blue/orange rings in direct/legacy touch, while ring presets apply in both modes. Follow this policy unless the user requests another one; do not infer a mode from the number of contacts.

GPU and GTK must receive the same prepared pixels and resolved startup fallback. Prepare the selected positioning pair and its mode fallback before drawing. Keep file reads, image decoding, rescaling and texture uploads out of the frame loop; use bounded caches. New non-ring kinds must select the proper atlas and dimensions, not accidentally reuse ring textures.

Use old and new extents when pose/style changes. Clear on release and include mode-only changes even if contact coordinates did not move. At screen boundaries, clip the artwork rather than moving the logical touch point. Preserve texture cleanup and the established behavior for live renderer/target failures.

## Selector behavior

Use shared draw/hit rectangles; card gaps and headings must not select a style. Directly selecting an existing choice is idempotent. Keep changes in the draft until Save succeeds; preserve Discard, Reset and unrelated settings.

Preview centering uses visible artwork, not runtime origin. Apply one scale for both poses, computed from their common maximum visible extent, then center each visible shape. Pixel art needs nearest sampling in both phase preparation and preview scaling. Keep localized text caches correct, and check both languages for clipping and collisions.

## Validation and evidence

For asset-only work, inspect format/alpha/bounds and the visual pair. For application changes, run the project checks from the repository root:

```bash
python3 -B tools/run_tests.py --with-node
```

Report actual totals and skips. Mac skips of Linux Cairo/GTK checks are not handheld passes. Use an available Linux environment for the relevant pixel/layout checks; if it is unavailable, state that limit instead of manufacturing success. Keep generated test scenes and helper windows owned by the test. Do not automate real input against a game.

Meaningful regression coverage includes both states, the existing subpixel phases, actual bounds/hotspots, missing/corrupt artwork fallback, direct/legacy mode behavior, stationary pose changes, edges/overlap/release, correct atlas selection and resource cleanup. Check translated catalogs and bilingual layouts when changing UI text or geometry.

When native rendering changes, compare the native output with Cairo through owned hidden buffers if the target environment is available. Check channels and exact clearing in reference-transparent regions. Do not weaken a comparison just to pass: inspect the actual error and justify any tolerance. This comparison does not validate physical input or the artistic alignment of two source poses.

For anti-aliased previews, a single sample can land between stroke and background after a fractional-center resize. Verify core colors within the expected stroke region with sufficient spatial coverage and a strict color tolerance; check transparent centers separately. For symmetric geometry, inspect meaningful visible/core masks, center and endpoints as appropriate: Cairo edge-coverage quantization can differ between mirrored boundary pixels without moving the geometry. Do not replace a real defect with a loose global threshold.

State performance scope separately. Startup preparation and an unchanged frame cap are design properties, not CPU/GPU measurements. Owned-process CPU, DRM engine time, compositor costs, frame cadence, power and whole-application impact are different quantities. Never reuse a historical frame count, benchmark result or device outcome as evidence for a newly changed style.

## Packaging and delivery

If a bundle is requested, use `python3 -B tools/build_release.py --offline` when the pinned dependency is cached, or the normal project build path when it is not. Verify the archive checksum and manifest and confirm packaged production code/assets match the tested candidate. Extend the explicit marker allowlist for real runtime files only; procedural geometry needs no placeholder PNG.

Keep source sheets, rejected variants, prompts, local diagnostics, configuration, credentials, caches, Git data and kernel experiments outside application bundles. Update provenance, relevant release/usage notes and their aligned Chinese editions when the implementation changes them. Preserve historical anchors and validation scope.

Installation or service changes require authorization from the current request/session, not from this skill. When authorized, use the per-user project installer and its verification/rollback path, preserving configuration and autostart. Follow `AGENTS.md`; do not manage official Armada/Steam/Gamescope services. Do not encode device endpoints, passwords, one-off temporary directories or prior installation approval here.
