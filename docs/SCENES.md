# Scenes and Blender — M39 foundation

**Complete within documented scope.** Geometry, persistence, CLI, GUI, task artifacts and local
rendering are implemented. CI #25 verifies a real render using official Blender 4.2 `bpy` and
Cycles CPU through the documented adapter (`scripts/blender_real_check.py`). The standalone
desktop Blender binary and other versions/engines have not been validated. Native libraries are
installed on the CI runner; this sandbox itself lacks those libraries and cannot load bpy.

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
Remote rendering, asynchronous render jobs, materials, animation, arbitrary imported geometry,
other renderer versions and platform compatibility remain follow-up work.

## Checkpoint evidence

- `tests/features/test_scenes_m39.py`: **58 passed** (geometry, topology, export bytes/hashes, drift, duplicate
  paths, refusal recording, no-PNG zero-exit failure, CLI, binary dry run and root escape refusal).
- Full suite after task linkage: **1926 passed in 463.12 seconds**.
- Focused M38/tool/scene regression run before four additional scene tests: **151 passed**.
- `bash scripts/acceptance_m39.sh`: **59 checks passed, 0 failed**, using the shipped CLI,
  reading export bytes independently, corrupting a file and recording a stand-in's argv.
- GUI smoke: **19 tabs**, including scene list, add, wireframe image and render refusal.
- CI run #23 on `17a4253`: **21 steps green**, **1921 tests**, **49 scene checks**.
  This predates task linkage. CI #25 subsequently verifies a real Blender render.

## GUI and API

The **Scenes** tab lists scenes, creates a named scene, adds/removes primitive objects, displays
measured geometry and recorded outputs, exports files, verifies hashes and requests a local render.
The measurement button explicitly accepts the document as a new baseline. The preview is displayed
in an image context rather than injecting SVG into the page DOM. Parameters are JSON; transforms
are available through the CLI/API rather than dedicated GUI controls.

Authenticated routes share `SceneService` and its tool permissions:

- `GET /api/scenes`: scene list and stats.
- `POST /api/scenes`: create with `name`.
- `GET /api/scenes/{scene_id}`: document, measurements, object detail and outputs.
- `POST /api/scenes/{scene_id}/{action}`: `add`, `remove`, `export`, `preview`, `verify`,
  `measure` or `render`. Add accepts `primitive`, optional `name`, object-valued `params` and
  `transform`; export accepts `kind`; remove accepts `name`.

A render refusal is an application result, not a transport error. Its recorded reason is displayed
in the status area. The GUI does not auto-enable execution or bypass capability approval.


## Document validation

Both persisted JSON reads and candidate writes validate scene format, units, names, primitive
parameters, transforms, camera, resolution, light and engine. Malformed externally edited JSON
returns a domain validation error rather than reaching geometry generation or producing a GUI 500.
Numeric fields must be actual finite numbers (not booleans or numeric strings), with magnitude at
most 1,000,000. Camera field of view is 1–179 degrees and resolution is two integers of 64–4096.
The camera must have distinct location/target and a nonzero, nonparallel up-vector.

A document permits at most 128 objects, with a conservative aggregate budget of 200,000 vertices
and 400,000 triangles, checked without allocating those meshes. Bad candidate additions are
rejected before file writes or object-row insertion. These limits bound the built-in workflow;
they do not make a Blender subprocess a security sandbox. Zero scale remains allowed as a
degenerate mesh; the topology flag alone does not imply useful solid geometry.


## Task artifacts and execution scope

`scene create NAME --task TASK_ID` links a scene to an existing task. The API accepts `task_id`
on scene creation; the GUI offers an optional existing-task field. Unknown task IDs are rejected
before scene file creation. The document is attached as a `scene` artifact; subsequent exports
attach as `scene.obj`, `scene.stl`, `scene.svg` or `scene.script`, with hashes and content versions
provided by the existing task/artifact service. Outputs return `artifact_id`; attachment errors
return `artifact_error` while retaining the file and scene output ledger row.

Renders inherit the scene task unless the service caller explicitly supplies another task ID.
Execution runs receive that task ID; render attempts append `scene.render` timeline events, and
successful output is attached as a render artifact. Finishing or refusing a render never changes
the parent task's status: the task may contain other work, so the caller owns its lifecycle.
Render input exports use the scene's task association. Files remain at their original paths;
artifacts are references with versions, not an immutable render-input bundle.

Job integration review: rendering is currently synchronous, locally executed, with a 600-second
execution timeout. It does not register a background scheduler job and does not promise restart
recovery or queued rendering. Those features are explicitly deferred rather than exposing a job
row that cannot resume. Blender compatibility is verified for official bpy 4.2 / Cycles CPU in CI; desktop binaries and other versions remain outside the verified matrix.


## Real renderer evidence

CI #25 (`385d386`) passed the actual renderer check, in addition to the stand-in acceptance.
Official bpy 4.2 renders the exported OBJ using Cycles CPU at 64×64. The recorded output is 4897
bytes with SHA-256 `c157d34edbb959f8194117dc220b515b6bd5f750154ea5cb39337c34cd509570`.
The adapter imports Blender and executes the generated script; it does not fabricate an image.
A renderer is still optional and is never installed as an Archx Agent runtime dependency.

Final combined CI #26 repeats the real-render check successfully on the M41 tip (`48dd607`):
64×64, 4883 PNG bytes, SHA-256
`ffe179acb67b8ab98b66feee3e6012151ea3a03292fa2e394e82ec87ea215e1f`. The render hash is evidence
of that run's bytes, not a promise of byte-identical images across machines or Blender runs.


### How the real-render check works

1. The CI runner installs native libraries and official `bpy==4.2.0` in an isolated
   Python environment, not into the dependency-free Archx core.
2. `scripts/blender_real_check.py` creates a real workspace and grants file read,
   file write and command execution. It creates a cube scene, selects Cycles CPU
   and a 64×64 resolution, and writes the OBJ plus generated Blender script.
3. A small executable adapter imports `bpy` and runs that script. This exercises
   Blender's actual rendering engine; it is not the argv-recording stand-in used
   by the ordinary acceptance script.
4. Archx records the execution attempt, requires a fresh PNG, and hashes the output.
   The check independently reads the file and verifies the PNG dimensions and bytes.

This validates the official Python Blender runtime on the recorded Linux runner.
It does **not** validate a standalone desktop Blender installation, every version,
Eevee, GPU rendering or animation. The fresh repository-audit environment did not
install bpy; its renderer tests use the documented stand-in and the historical
CI evidence above remains the real-render proof.
