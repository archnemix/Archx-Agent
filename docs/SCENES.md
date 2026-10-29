# Scenes and Blender — M39 foundation

**In progress, not milestone-complete.** This checkpoint adds the geometry engine, persistence,
service and CLI. There is no scene GUI yet, no M39 acceptance script in CI, and no real Blender
render has been validated in this environment.

## CLI

Run in a configured tool root. File operations require `fs.read` / `fs.write` grants from the
permission centre; creating a scene does not implicitly grant either capability.

```sh
archx-agent scene create demo
archx-agent scene add demo cube --name box --params '{"size":2}' --location 0 0 1
archx-agent scene add demo plane --params '{"size":6}'
archx-agent scene show demo
archx-agent scene measure demo
archx-agent scene preview demo                 # SVG text, explicitly a wireframe
archx-agent scene export demo obj
archx-agent scene export demo stl
archx-agent scene export demo svg
archx-agent scene export demo script
archx-agent scene outputs demo
archx-agent scene verify demo
archx-agent scene render demo
archx-agent scene remove demo plane
archx-agent scene list
archx-agent scene stats
```

`--json` is supported on leaf commands. Non-preview commands currently emit JSON even without
that flag. Exports live in `scenes/` under the first tool root. Scene names that resolve to an
existing scene file are refused before overwriting it.

## What the geometry means

Six deterministic generators: cube, plane, UV sphere, cylinder, cone and torus. Parameters are
checked by name; dimensions must be positive and finite; subdivision counts must be integers from
3 to 256. Transforms apply scale, then X/Y/Z rotations in degrees, then translation. Coordinates
are Z-up; document units are meters.

Measurements come from generated vertices and faces: bounding box, triangle count, surface area,
signed tetrahedron volume, vertex centroid and edge-incidence closure. A cube of side 2 has area
24 and volume 8. Curved primitives are polygonal approximations, not analytic solids. A plane is
open. Closure means each undirected edge has two incident faces; it does **not** prove consistent
orientation, absence of self-intersection or printability. Scene volume is a sum, not a boolean
union: overlapping objects count twice. Open-mesh volume is not a physical enclosed volume.

OBJ writes one group per object, with face normals. Binary STL is 84 header/count bytes plus 50
bytes per triangle. SVG is a perspective wireframe: no lighting or hidden-surface removal. It is
not a render. `fs.write_bytes` is a new tool sharing the existing `fs.write` capability and root,
size and dry-run restrictions; binary output is base64-carried in JSON, never UTF-8 round-tripped.

Schema v29 stores `scenes`, `scene_objects` and `scene_outputs`. Scene mutations write the document
through tools and record derived totals. These disk/database operations are not one atomic
transaction. Object rows are snapshots taken on addition; externally edited documents are not
silently synchronized back into those rows.

## Verification

`scene verify` hashes the document and the latest recorded output per path, compares stored versus
current triangle counts, and returns exit 3 on disagreement. It does not regenerate and compare
all exports or compare every cached measurement. `scene measure` explicitly accepts the current
document as the measurement baseline; use `verify` first to detect edits. Exports are overwritten
at their named paths; old ledger rows remain history, not immutable file versions.

## Blender boundary

Generated scripts import OBJ with Blender's `bpy.ops.wm.obj_import` API, set a camera, area light,
engine and resolution, and request one PNG. They target a modern Blender exposing that API and
`BLENDER_EEVEE_NEXT`; other Blender versions have not been tested. Standalone `export script`
requires an accompanying OBJ export; `render` creates both inputs automatically.

Rendering currently supports **only local execution**. It requires a configured `blender.executable`,
`execution.enabled=true` and a `shell.run` grant. It runs through M38's execution ledger with
`--background --factory-startup --python`, using quoted absolute script paths. Every attempt uses
a unique PNG destination so an old render cannot pass as a new one. A zero process exit without
an output with the PNG signature is a failure; that check is not full PNG integrity validation.
Successful output records its byte count and SHA-256. Missing configuration and disabled execution
produce a recorded refusal and exit 3, not a fabricated preview/render.

A local Blender script is code with your machine's authority. The local target is not a sandbox.
Remote rendering, task/job lifecycle integration, materials, animation, arbitrary imported geometry,
GUI integration and actual renderer compatibility validation remain follow-up work.

## Checkpoint evidence

- `tests/test_scenes_m39.py`: **24 passed** (geometry, topology, export bytes/hashes, drift, duplicate
  paths, refusal recording, no-PNG zero-exit failure, CLI, binary dry run and root escape refusal).
- Full suite after implementation: **1892 passed in 520.79 seconds**.
- Focused M38/tool/scene regression run before four additional scene tests: **151 passed**.
- No real Blender render and no new CI result claimed for this checkpoint.
