# Art direction and production pairs

Read for concept generation, visual refinement, or raster export. Keep the user's chosen subject and requested stage; the number of concepts and the order of iterations are flexible.

## Compare states at a useful scale

Use a consistent background and paired presentation. Label comparison columns in the user's language when useful; these labels are not part of a runtime sprite. Concept numbers can help selection. Do not assume that concept names should appear in the application's selector.

Positioning and held should look like the same object performing an action. For a hand, keep palm/wrist placement while articulating the finger. For a reticle, keep its target center while the corners contract. Check anatomy and the visible number of digits when relevant, rather than using a shorter finger or a disappearing digit as a substitute for a natural bend.

Evaluate both enlarged and actual-size views. Useful questions are whether the state change survives shrinking or grayscale, whether the contact location remains understandable, and whether the outline reads against both bright and dark content. Avoid relying on a slight same-hue variation or details that disappear at small sizes.

The current project uses compact, directly selectable, unnamed previews with both states visible. Preserve that product choice unless the user requests a change; do not freeze today's card count, coordinates or thumbnail scale into future designs.

## Illustrated raster or procedural geometry

For illustrated hands or other raster subjects, use the built-in image-generation tool and its available skill. A local reference must first be inspected. For an edit, specify the edit target and the properties that must remain unchanged. When refining an approved image, request extraction/refinement rather than a fresh redesign.

Simple rings, brackets and reticles usually benefit from native geometry. Inspect the current marker implementation before choosing Cairo/SVG: precise symmetry, a stable center and deterministic state changes are easier to maintain there than in generated images. Do not add raster assets merely because an inspiration board was rasterized.

Do not silently fall back to an API requiring credentials if the requested generation path is unavailable. Explain the unavailable capability and offer a suitable alternative within the user's scope.

## Prompt patterns

Use only the fields needed by the chosen design. These are starting points, not a mandatory schema or a fixed style.

```text
Purpose: a readable small touchscreen positioning/held marker pair.
Reference: the selected image; preserve its subject, palette and outline style.
Presentation: two equal cells, positioning left and held right, same scale.
Positioning pose: describe the relaxed/open/aiming state.
Held pose: describe a specific natural bend, contraction or press.
Invariants: common wrist/palm or geometric center, same tilt and proportions.
Readability: a clear small-size silhouette and contrast on light/dark content.
Avoid: only the actual defects or unwanted additions relevant to this design.
```

For a production extraction, explicitly request true transparent alpha, no labels or separator, complete silhouettes, no baked checkerboard/matte, and preservation of opaque black outlines/interior creases. Keep both states at the same source scale and anchor; shorten the moving part without rescaling the whole object.

If a generated result fails an invariant, inspect it and make a targeted correction. Do not declare an invariant satisfied from the prompt alone. Preserve previous versions so a revision does not overwrite the user's selected reference.

## Normalize without changing the design

Inspect the renderer's current size and format contract first. Current non-ring styles use 64×64 canvases and 8-bit RGBA PNGs for raster artwork; these are existing integration constraints, not universal icon dimensions.

Find a meaningful shared source anchor, such as the cuff, before applying a common crop/scale. Independently trimming each pose and fitting it to the same rectangle will move the palm when the finger bends. A pressed fingertip can move within the canvas while the pair keeps the same logical input hotspot.

Use nearest sampling for deliberate pixel art. Preserve smooth filtering and partial alpha for ordinary illustrations; do not threshold every artwork into a binary silhouette. Remove disconnected extraction noise only after inspecting it, and retain legitimate details and the outer readability outline. Keep this normalization reproducible in local design evidence.

After normalization, run `scripts/inspect_marker_pair.py` from the skill. Compare its measured bounds with the actual runtime metadata. Review the paired image visually as well: the script cannot infer which point should be the hotspot or prove that wrists match.

Production files belong under `assets/markers/<stable-style-key>/idle.png` and `pressed.png` when following the current raster layout. Put source sheets, rejected variants, prompts, normalization records and review previews under a task-specific ignored `outputs/` directory. A useful record includes repository-relative production paths, tool/source, prompt, dimensions, shared hotspot, measured per-state bounds and sampling choice. Do not embed personal-machine paths or credentials into reusable skill instructions.

Preserve relevant provenance and licenses in the project's paired `THIRD_PARTY` records. Existing glove and pixel-hand evidence can be consulted when available, but ignored historical `outputs/` are optional evidence, not a required dependency of this skill.
