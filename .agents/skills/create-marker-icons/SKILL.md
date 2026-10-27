---
name: create-marker-icons
description: "Design, refine and prepare positioning/held touch-marker icons for this repository, and integrate selected styles when requested. Use for cursor skins, two-state comparisons, transparent sprite pairs and their selector/rendering integration; not application launcher icons or logos."
---

# Create marker icons

Create readable two-state markers for Armada Dual Screen Input: **positioning** moves the indicator; **held** indicates an active upper-screen contact. Work only on the stage the user requested: inspiration, refinement, production assets, or application integration.

The repository root is three directories above this skill folder. Read its `AGENTS.md`; paths in the supporting references are repository-relative. This is a project skill, not a personal installation or an application runtime resource.

## Choose the relevant workflow

- **Ideas or visual refinement:** read [art direction](references/art-direction.md). Show paired states together, including a small actual-size view when judging legibility. Keep unselected alternatives outside runtime assets.
- **Production raster pair:** use the export guidance in that reference, then run the read-only inspector below. Record generation prompts and provenance with the local design evidence.
- **Requested program integration:** also read [project integration](references/project-integration.md). Preserve configuration, input routing and the renderer lifecycle while adding the visual style.

Do not introduce a new approval gate when the user has already selected a design and authorized the next stage. A request for previews alone does not authorize installation, service changes or publication; follow the current request and existing session authorization.

## Decisions that matter

1. **Use the right source.** Use built-in image generation for illustrated raster creation or editing; inspect local references before editing. Prefer deterministic Cairo/SVG geometry for simple geometric markers such as reticles, especially when symmetry and a precise center matter. Follow the available image-generation instructions; do not silently switch to a credentialed API or a different requested model/tool.
2. **Refine the pair, not two unrelated pictures.** Keep orientation, scale and a shared anatomical or structural anchor. The held state must remain distinguishable at runtime size through pose, silhouette or clear contrast. Preserve the user's selected direction; change one troublesome feature at a time.
3. **Separate three coordinate systems.** Source-sheet placement, runtime hotspot, and static-preview centering serve different purposes. Align both poses before the common resize; use one runtime hotspot for the pair. Center preview thumbnails from their visible bounds without changing input coordinates.
4. **Inspect final pixels.** Re-measure after the final crop/resize. Check true transparency, complete outlines, state distinction, stable palm/wrist or target center, and light/dark-background readability. Nearest sampling suits pixel art; smooth artwork keeps its appropriate filter.
5. **Keep rendering bounded.** Decode, prepare subpixel sprites and upload textures before active drawing. Do not add per-frame image generation, disk reads, resizing, uploads, unbounded caches or a continuous idle animation just to support a new style.

## Inspect a production pair

Run from the repository root with a Python environment providing Pillow:

```bash
python3 -B .agents/skills/create-marker-icons/scripts/inspect_marker_pair.py \
  assets/markers/pixel_hand/idle.png \
  assets/markers/pixel_hand/pressed.png --size 64 --hotspot 15 5
```

These arguments describe the existing pixel hand, not defaults for a new design. Supply the new pair's intended canvas and common hotspot. The script checks PNG/RGBA format, size, transparency, padding, distinct states and hotspot range; it reports visible bounds using the current project's default alpha threshold of 15. Adjust that threshold when the artwork/rendering contract requires it. Bounds use inclusive left/top and exclusive right/bottom.

The inspector does **not** prove visual alignment, input accuracy or GPU behavior. If Pillow is missing, use an available workspace Python environment with Pillow and report any checks that could not run.

## Deliver the requested result

- Show final comparisons with positioning on the left and held on the right unless the user asks otherwise.
- For project-bound raster assets, provide their saved paths, the prompt/provenance record, and the generation method. Keep runtime-required metadata in packaged code/data, not only under ignored `outputs/`.
- For integration, report the relevant checks, actual passes/skips and remaining validation scope. Distinguish offscreen layout, owned-buffer pixels, physical input acceptance and performance measurements. A correct preview or unchanged frame cap does not establish CPU/GPU cost.
