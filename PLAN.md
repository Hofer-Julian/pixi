# Plan: restore backend dependency introspection after conditional deps (PR #6269)

Working document for the implementation; this change is not meant to be pushed as part of the
final PR. Status: design fully agreed on 2026-06-12. Ready to implement.

## Problem

Commit 206b59f4f (jj `ulqxvzvq`, PR #6269) made the backend dependency getters
(`Targets::{dependencies,run_dependencies,host_dependencies,build_dependencies}` in
`crates/pixi_build_backend/src/traits/targets.rs:102-115`) return the **default target only**.
Conditional `if(...)` entries live in `pbt::Targets::conditional` and are passed through verbatim
for rattler-build to evaluate during `render_recipe`. Backends that *inspect* dependencies to make
decisions are now blind to conditional deps.

Scope amplifier: `[package.target.<platform>]` tables are lowered to conditional expressions at
parse time (`crates/pixi_manifest/src/toml/package.rs:630`, producing e.g.
`host_platform == 'linux-64'`, or bare `unix`/`win` for those selectors). So **all existing
manifests with target-specific deps** lost backend introspection, not just users of the new
`if()` syntax. This is a regression, not a new-feature edge case.

Note: the originally suspected case (maturin in host deps of pixi-build-python) does not exist;
maturin detection reads pyproject `build-system.requires`
(`crates/pixi_build_python/src/pypi_mapping.rs:563`) and is unaffected. The real casualties are
below.

## Affected sites

Class A - boolean decisions baked into the build script (real breakage, IN SCOPE):

- `crates/pixi_build_rust/src/main.rs:107` `has_openssl` from host deps -> `OPENSSL_DIR` in script
- `crates/pixi_build_cmake/src/main.rs:129` `has_host_python` -> `-DPython_EXECUTABLE` cmake arg
- `crates/pixi_build_python/src/main.rs:192` uv-vs-pip installer choice for the script
- `crates/pixi_build_python/src/main.rs:178` `has_cython_dependency`

Class B - requirement injection with blind dedup (OUT OF SCOPE, intentional):

- python: installer pkg + python pushed to host/run (`pixi_build_python/src/main.rs:198,215`)
- cmake/ninja (`pixi_build_cmake/src/main.rs:118`), r-base (`pixi_build_r/src/main.rs:123`),
  compilers (`pixi_build_backend/src/compilers.rs:146`)
- Decision: blind dedup against the default target is CORRECT for injection. Suppressing
  injection because a dep is declared conditionally would break platforms where the condition is
  false; the duplicate spec is benign (solver intersects). Add a comment at these sites
  documenting that this is intentional.

Class C - latent API (IN SCOPE, small fix):

- `used_variants()` (`crates/pixi_build_backend/src/traits/project.rs:54`) only unions
  default-target dep names; variant keys appearing solely under conditionals are dropped.
- `compute_variants` (`crates/pixi_build_backend/src/common/variants.rs`) has no in-repo callers
  but is `pub` exported (`common/mod.rs:8`) for out-of-tree backends. Keep it.

## Design

1. **Post-render hook.** Add a method to the `GenerateRecipe` trait
   (`crates/pixi_build_backend/src/generated_recipe.rs:79`), e.g.
   `finalize_build_script(...) -> Option<Script>`, with a no-op default impl (return `None` =
   keep the script from `generate_recipe`). Called in `conda_build_v2`
   (`crates/pixi_build_backend/src/intermediate_backend.rs`) after `find_matching_output`
   (line ~767), receiving the **rendered** recipe (concrete, condition-evaluated requirements)
   plus the `GeneratedRecipe` and whatever config/params the backends need (config, editable,
   manifest root, host_platform - reconstruct per backend needs; exact signature is an
   implementation judgment call). The returned script replaces the one on
   `discovered_output.recipe` before `Output` construction (line ~839, `Output` takes the recipe
   by value, so mutation before that point is mechanically fine).
2. **`generate_recipe` keeps producing a best-effort (possibly wrong) script** as a placeholder.
   Verified: the script never leaves the backend via `conda_outputs` (`CondaOutput` carries only
   metadata + dependencies), so only `conda_build_v2` matters. Extend the debug dump
   (`intermediate_backend.rs:788-825`) so dumped artifacts show the finalized script, not just
   the placeholder.
3. **Provenance threading to defeat self-contamination.** Rendered requirements include the
   backend's own injections (e.g. injected `uv`), which would corrupt post-render introspection:
   conditional `pip` on linux renders to host = pip(user) + uv(injected), and the current
   tie-break "uv wins" (`pixi_build_python/src/build_script.rs:52`) would pick uv against user
   intent. Fix: `GeneratedRecipe` records what the backend injected (e.g.
   `injected_host_packages: Vec<SourcePackageName>`); the hook subtracts those from the rendered
   requirements before deciding. openssl/cython/host-python are not self-contaminated (backends
   never inject what they probe) but the mechanism is general.
4. **Class C fix:** make `used_variants` union dep names from `Targets::conditional` as well
   (may need a small trait addition since the getters stay default-only by design). Document it
   as a may-use over-approximation across all conditions: spurious keys are harmless because
   rattler-build's hash only incorporates actually-used variables.
5. Backends implementing the hook: rust, cmake, python. mojo/r don't introspect for the script.

## Test plan (failing tests FIRST)

1. Backend-level Rust tests in each backend crate (rust backend already has model-driven tests
   at `crates/pixi_build_rust/src/main.rs:872,959` to extend): build a project model with a
   `conditional` target entry, run generate -> render -> finalize, assert script content
   (OPENSSL_DIR present, -DPython_EXECUTABLE arg, pip vs uv, cython). Inline insta snapshots.
   These fail today because the booleans read the blind getters.
2. One protocol-level test in `crates/pixi_build_backend/tests/integration/protocol.rs` driving
   `conda_build_v2` end-to-end (passthrough or python backend) covering provenance subtraction:
   conditional pip + injected uv -> script picks pip.
3. One e2e test in `tests/integration_python/pixi_build/test_conditional_dependencies.py` (file
   added by PR #6269) using an OLD-STYLE `[package.target.<platform>]` manifest with the python
   installer case (cheap; no cargo toolchain). This is the only layer that exercises the
   parse-time lowering in `pixi_manifest`. Platform-dependence: copy whatever convention the
   existing tests in that file use (parametrize platform into the manifest); do not invent one.
4. Unit test for the `used_variants` union (conditional-only dep name is reported).
   No e2e per Class A site - one is enough; the rest is covered at backend level.

## Conventions

- jj, not git: `jj new --message "..."` before starting; describe intent immediately.
- Failing test first, confirm it fails for the right reason, then fix.
- `cargo nextest run --workspace --no-fail-fast`; never `-p`/`--package`, use
  `-E 'package(pixi_build_rust)'` filters. `cargo clippy --workspace -- -D warnings`.
- Inline insta snapshots (except parameterized tests). Error messages lowercase, no trailing
  punctuation. No em/en dashes anywhere. Imports at top of module.
- Pixi manifest exists in this repo: use `pixi run` tasks for python integration tests (check
  the manifest for the task name before suggesting/running).
- Comments describe what is there, not what changed.
