A Pixi workspace can support several operating systems and, within one operating system, several hardware variants such as CPU-only and CUDA machines.

## Supporting several operating systems

List the conda subdirs your workspace supports in `workspace.platforms`:

```toml title="pixi.toml"
[workspace]
channels = ["conda-forge"]
platforms = ["linux-64", "osx-arm64", "win-64"]

[dependencies]
python = "3.15.*"

[tasks]
version = "python --version"
```

The environment is resolved separately for each platform, and `pixi.lock` stores one package set per platform.
Pixi resolves all of them on any machine, so a Linux machine also locks the macOS and Windows package sets.
`pixi install` and `pixi run` install the package set that fits the current machine.
[Target specifiers](#target-specifier) add dependencies, tasks, or activation scripts for individual platforms.

## Declared, detected, and required virtual packages

Some packages need features of the machine instead of other packages, for example a CUDA driver.
These are described via [virtual packages](../conda_ecosystem.md#virtual-packages-describing-the-host-system) such as `__cuda`.
Pixi uses them in three separate roles:

| Role | Example | Purpose |
|---|---|---|
| Declared | `cuda = "12.0"` in `workspace.platforms` | Adds exactly `__cuda=12.0` to the solve of that platform |
| Detected | `__cuda=12.9=0` reported by the machine | Describes what the current machine provides |
| Required | `__cuda >=12` in a locked package | States what a resolved package needs |

Pixi solves each platform with its declared virtual packages, not the detected values, so a CPU-only CI runner can lock a CUDA platform.
`pixi.lock` stores platform declarations and package requirements, never detected values.
At installation, Pixi checks whether the locked packages fit the machine; see [platform selection](#which-platform-gets-installed).

`cuda = "12.0"` declares the CUDA capability of the NVIDIA driver.
It does not install a driver, and it is not the CUDA toolkit.
Toolkit and runtime packages such as `cuda-version` or `cuda-runtime` are ordinary dependencies.
Virtual packages are never downloaded, and Pixi does not export their values as environment variables.

Host-oriented commands such as `pixi exec` and native `pixi global install` don't have declared workspace platforms, so they solve against the detected values.

## CPU and CUDA variants of one subdir

To support both CPU-only and CUDA machines on `linux-64`, declare two named platforms with the same subdir and give each its own dependencies:

```toml title="pixi.toml"
[workspace]
channels = ["conda-forge"]
platforms = [
  { name = "linux-64-cuda", platform = "linux-64", cuda = "12.0" },
  { name = "linux-64-cpu", platform = "linux-64" },
  "osx-arm64",
]

[dependencies]
python = "3.14.*"

[target.linux-64-cuda.dependencies]
pytorch-gpu = "*"

[target.linux-64-cpu.dependencies]
pytorch-cpu = "*"

[target.osx-arm64.dependencies]
pytorch = "*"
```

`pixi lock` resolves three package sets for the `default` environment, including the CUDA one on a machine without a GPU.

The CPU platform selects `pytorch-cpu` explicitly.
Leaving out the CUDA declaration only means that the solver can't use packages that require `__cuda`; it does not request a CPU build.

Target selectors match in two ways:

- A platform name such as `[target.linux-64-cuda]` matches exactly that platform.
- A subdir such as `[target.linux-64]` matches every platform with that subdir.
  Here it would apply to both `linux-64-cuda` and `linux-64-cpu`, and adding `pytorch-cpu` to the CUDA solve would conflict with `pytorch-gpu`.

Put the CUDA platform first so Pixi prefers it on compatible machines; otherwise it tries the CPU platform.
`pixi run` keeps the installed platform. After adding a driver, run `pixi install` to [select again](#which-platform-gets-installed).

The [PyTorch guide](../python/pytorch.md) covers pinning the CUDA version with `cuda-version` and installing PyTorch from PyPI.

## Target specifier

Target specifiers override configuration for matching platforms.
The selector is a platform name, a subdir, a [wildcard pattern](#wildcard-platform-selectors), or one of `unix`, `linux`, `win`, and `osx`.
A selector that doesn't match any platform in `workspace.platforms` produces a warning.

### Dependencies

```toml title="pixi.toml"
[dependencies]
python = ">=3.12"

[target.win-64.dependencies]
msmpi = "*"
python = "3.12.*"
```

This installs `msmpi` and pins Python to `3.12` only on `win-64`.
To add a platform-specific dependency from the CLI:

```bash
pixi add --platform win-64 posix
```

Use `--host` or `--build` for host and build dependencies:

```bash
pixi add --host --platform win-64 posix
pixi add --build --platform osx-64 clang
```

### Activation

Activation scripts are often specific to a shell, for example `bash` on Unix and `bat` on Windows.
Define them per target:

```toml title="pixi.toml"
[activation]
scripts = ["setup.sh", "local_setup.bash"]

[target.win-64.activation]
scripts = ["setup.bat", "local_setup.bat"]
```

On `win-64`, Pixi runs only the target scripts, not the scripts in the default `activation.scripts`.

### Wildcard platform selectors

When several [workspace platforms](#declaring-virtual-packages-per-platform) share configuration, you can match them with a `*` wildcard in the target selector instead of repeating each block.
The pattern is matched against the platform *name*, so it is most useful together with custom platform names:

```toml title="pixi.toml"
[workspace]
platforms = [
  { name = "cuda-win-64", platform = "win-64", cuda = "12" },
  { name = "cuda-linux-64", platform = "linux-64", cuda = "12" },
  "win-64",
  "linux-64",
]

[target."cuda-*".tasks]
test = "python test.py --cuda"
train = "python train.py --cuda"
```

Here both `cuda-win-64` and `cuda-linux-64` pick up the `test` and `train` tasks, while the bare `win-64` and `linux-64` platforms do not.

- `*` is the only metacharacter and matches any run of characters. Patterns are matched in full and are case-sensitive (`cuda-*`, `*-64`, `*cuda*`).
- When multiple selectors match, the one defined **later** in the manifest wins. Place specific overrides after wildcard blocks.
- Wildcards are only allowed on workspace and feature targets. They are rejected in `[package.target]` and `[package.build.target]`, which resolve by subdir.

## Declaring virtual packages per platform

A bare-string entry like `"linux-64"` is shorthand for "the conda subdir `linux-64` with Pixi's [default declared virtual packages](#default-declared-virtual-packages)".
An inline table declares additional [virtual packages](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-virtual.html) for the solve, for example a CUDA driver capability or a glibc version.

!!! info "Replaces `[system-requirements]`"
    These inline-table entries are the recommended way to declare CUDA, glibc, macOS, archspec, and similar constraints. The older `[system-requirements]` table still parses but is deprecated; see [Migrating from `[system-requirements]`](./system_requirements.md) for the equivalent forms.

```toml title="pixi.toml"
[workspace]
platforms = [
  "osx-arm64",
  { platform = "linux-64", cuda = "12.0", glibc = "2.28" },
  { name = "jetson-nano", platform = "linux-aarch64", cuda = "12.8" },
]
```

Each inline-table entry has:

- `platform`: the conda subdir the entry targets (e.g. `linux-64`, `osx-arm64`). Required.
- `name`: optional identifier used in target selectors, features, the lock file, and CLI commands. When omitted, Pixi derives a stable name from the subdir and declared virtual packages.
- Friendly keys for the common virtual packages: `cuda`, `amdgpu`, `archspec`, `glibc`, `linux`, `macos` (alias `osx`), `windows`.
  Each maps onto the matching `__name` conda virtual package (`cuda` -> `__cuda`, `amdgpu` -> `__amdgpu`, `glibc` -> `__glibc`, `macos` -> `__osx`, etc.).
- `archspec`: a CPU microarchitecture from the bundled [archspec database](https://github.com/archspec/archspec), such as `x86_64_v3`, `skylake`, or `m1`.
  Use underscores and dots, not hyphens: `x86_64_v3`, not `x86-64-v3`.
  A host matches if its microarchitecture is the declared one or a superset according to the database.
  Unknown host microarchitectures are accepted; `archspec = "0"` explicitly declares an unknown microarchitecture.
- `cuda` also accepts a `{ driver, arch }` table that declares the CUDA driver
  version (`__cuda`) together with the GPU compute capability (`__cuda_arch`):

  ```toml title="pixi.toml"
  platforms = [
    { name = "gpu", platform = "linux-64", cuda = { driver = "12.0", arch = "8.6" } },
  ]
  ```

  `driver` is equivalent to the bare `cuda = "12.0"` form and is required when declaring `arch`.

- `amdgpu = true` declares `__amdgpu`, which only states that an AMD GPU is
  present. An AMDGPU target name (`gfx90a`, `gfx1100`, ...) additionally
  declares the GPU architecture as `__amdgpu_arch`, which conda stores as an
  ISA version (`gfx90a` is `9.0.10`):

  ```toml title="pixi.toml"
  platforms = [
    { name = "rocm", platform = "linux-64", amdgpu = true },
    { name = "mi250", platform = "linux-64", amdgpu = "gfx90a" },
  ]
  ```

  A raw `__amdgpu_arch` takes the ISA version and is rejected without
  `__amdgpu`.
  AMD GPU ISAs are not generally backward compatible.
  Packages targeting a specific ISA must require it exactly, for example
  `__amdgpu_arch ==9.0.10` for `gfx90a`.
  Pixi compares the declaration as a minimum version when ordering candidates;
  the locked package requirement enforces the exact match.

- For virtual packages without a friendly key, use a raw `__name = "version"` entry, such as `__username_length = "3"` in the [detector tutorial](../advanced/virtual_package_detectors.md).
  The value is a concrete version, not a dependency expression such as `">=3"`.
  Use `"version=build_string"` to specify a build; the default build is `0`.
  Custom host capabilities come from a registered detector or a recognized [host override](#environment-variable-overrides), not from declaring the name in the manifest.

A feature's `platforms` list references workspace platform names or bare subdirs:

```toml title="pixi.toml"
[workspace]
platforms = [
  "osx-arm64",
  { platform = "linux-64", cuda = "12.0" },
]

[feature.gpu]
platforms = ["linux-64-cuda-12-0"]  # the synthesized name for the entry above
```

!!! note "Platform names in `pixi.lock`"
    A platform rename can reuse the locked resolution if its definition and effective dependencies are unchanged and the match is unambiguous.
    Changing target selectors can change dependencies and require a new resolution.

### Adding the current machine

`--auto-detect` writes the subdir and the virtual packages detected on the current machine (macOS version, glibc, archspec, CUDA, ...) into a platform entry:

```shell
pixi workspace platform add --auto-detect
```

This captures one known machine, which is usually more specific than your packages need.
The entry is inserted **first** in `platforms`, giving it priority within its [subdir](#which-platform-gets-installed).
It is a normal entry in the manifest, so everyone using the workspace solves for it, and machines that don't match it fall back to later entries of the same subdir.

```shell
# Give the detected platform a custom name instead of the synthesized one.
pixi workspace platform add my-laptop --auto-detect

# Override individual virtual packages on top of what was detected.
pixi workspace platform add --auto-detect --cuda 12.4
```

An existing platform with the same subdir and virtual packages is reused and moved to the front.
Giving the same definition a different name is rejected.

!!! tip "Trim it for portability"
    After installing, `pixi info` reports each environment's **Minimum platform**, derived from locked conda package requirements.
    Use it to review declarations, not as proof that a requirement is safe to remove: the locked-requirement check excludes `__archspec` and does not establish that every binary can run.
    A future resolution can also select packages with different requirements.

## Managing platforms from the CLI

Use [`pixi workspace platform`](../reference/cli/pixi/workspace/platform/index.md) to `add`, `edit`, `list`, or `remove` platforms.
Use `move --to-top`, `--to-bottom`, `--before <NAME>`, or `--after <NAME>` to change selection priority within a subdir.

The mutating subcommands keep `pixi.lock` in sync.

## Which platform gets installed?

For a fresh automatic installation, Pixi tries platforms in runnable subdirs in two groups:

1. Platforms whose built-in virtual package declarations match the machine.
2. The remaining platforms, even if their declarations do not match.

When comparing built-in declarations, the detected package must have the same name and build string, with a version at least as high as declared.
[`archspec`](#declaring-virtual-packages-per-platform) uses CPU microarchitecture compatibility instead of version ordering.

Within each group, native subdirs come before supported fallbacks such as `osx-64` on `osx-arm64`, then declaration order applies within each subdir.
Pixi selects the first candidate whose locked conda virtual package requirements (except `__archspec`) and PyPI packages are compatible with the machine.
If none fit, installation fails.
Without a lock file, only declarations guide preselection.

A declaration match does not guarantee compatible packages.
For example, CUDA `13.0` matches a `cuda = "12.0"` declaration, but locked packages requiring `__cuda <13` make Pixi skip that platform and try the next one.
Run `pixi info` to see skipped platforms and their unmet requirements.

When Pixi selects a platform despite mismatched declarations, `pixi run` warns once.
The current locked packages may fit, but a future resolution can require the declared capabilities.

For GPU-enabled PyPI packages without a locked `__cuda` requirement, a CUDA declaration affects preference but does not prevent installation on a machine without CUDA.

### Installed environments and explicit selection

`pixi run` keeps the installed platform.
After changing drivers or other machine capabilities, run `pixi install` to reconsider platform selection.
If no declaration-matching platform has compatible locked packages, Pixi keeps the existing platform if it is still declared.

Use `pixi install --platform <NAME>` or `pixi run --platform <NAME>` to select a platform explicitly.
These commands skip host compatibility checks, so installation can succeed even if the environment cannot run locally.
Later runs without `--platform` remain subject to host compatibility checks.

## Default declared virtual packages

Bare subdir entries and inline-table entries both include subdir defaults.
Explicit values take precedence by virtual-package name.
The version floors are:

| Subdir | Version floors |
|---|---|
| Linux, except `linux-riscv64` | `__linux = "4.18"`, `__glibc = "2.28"` |
| `linux-riscv64` | `__linux = "4.18"`, `__glibc = "2.39"` |
| `osx-64`, `osx-arm64` | `__osx = "13.0"` |

This table is not the complete virtual-package set.
Unix subdirs also include `__unix`, Windows includes `__win`, and an `__archspec` baseline is included where available.
CUDA is not a default.
Declaring `__musl` or `__eglibc` replaces the default `__glibc` rather than adding a second libc family.

## Environment-variable overrides

`CONDA_OVERRIDE_*` variables change Pixi's view of the host.
They do not change the virtual packages supplied to a declared workspace solve.
To change the solve target, edit its platform declaration.

Overrides are useful for deliberately mocking host capabilities, for example to see which dependencies a CUDA machine would get:

```nushell
with-env { CONDA_OVERRIDE_CUDA: "12.0" } {
    pixi info
}
```

This reports a claimed CUDA capability, and the `Dependencies` of each environment come from the platform such a machine would select.
It does not install a driver or make a GPU-dependent application runnable.

| Override | Host capability |
|---|---|
| `CONDA_OVERRIDE_CUDA` | `__cuda` driver capability, for example `12` |
| `CONDA_OVERRIDE_CUDA_ARCH` | `__cuda_arch` compute capability, for example `8.6`; requires CUDA presence |
| `CONDA_OVERRIDE_AMDGPU` | `__amdgpu` presence; the only valid version is `0` |
| `CONDA_OVERRIDE_AMDGPU_ARCH` | `__amdgpu_arch` ISA version, for example `11.0.0`; requires AMDGPU presence |
| `CONDA_OVERRIDE_GLIBC` | `__glibc` version, for example `2.28` |
| `CONDA_OVERRIDE_OSX` | `__osx` version, for example `13.0` |
| `CONDA_OVERRIDE_LINUX` | `__linux` version, for example `4.18` |
| `CONDA_OVERRIDE_WIN` | `__win` version, for example `0` |
| `CONDA_OVERRIDE_ARCHSPEC` | CPU microarchitecture, for example `skylake`; `0` marks it unknown |

For example, mocking an AMD GPU architecture requires both `CONDA_OVERRIDE_AMDGPU=0` and `CONDA_OVERRIDE_AMDGPU_ARCH=11.0.0`.
Built-in overrides have platform-specific parsing rules; an OS override does not turn the host into that OS.
An empty value disables the corresponding capability in the host view, not in the target declaration.

For custom detector names, accepted channel registrations establish the override names.
For example, `__username_length` uses `CONDA_OVERRIDE_USERNAME_LENGTH`, with a value such as `"9"` or `"9=0"` to include a build string.
An override can supply that host value without executing or trusting the detector.
Arbitrary `CONDA_OVERRIDE_*` variables are not automatically imported as capabilities without a recognized name.
User-supplied override variables can be inherited by child processes like other environment variables; this is not detector-result injection.

## Virtual package detectors

Channels can register virtual package detectors: packages that report system capabilities, such as an MPI runtime or a driver installed outside the environment.
Pixi compares built-in names with declarations and checks all names against locked package requirements.
Custom names are not compared with declarations.
Detectors can extend or replace Pixi's built-in detection.

Pixi runs detectors when their virtual packages are needed for the current machine, not for foreign target platforms.
`pixi lock` can run them too, to select the platform for the current machine, but workspace solves only use the virtual packages declared in the manifest.

Detectors execute code from the channel, so Pixi asks whether to trust them before running them.
You can save the decision in the [configuration](../reference/pixi_configuration.md#virtual-package-detectors).
Without a terminal, detectors without a saved decision are skipped.
Detector report caching and installed-prefix reuse are separate; see the [consent and cache policy](../reference/pixi_configuration.md#virtual-package-detectors).

See [Channel-provided virtual package detectors](../advanced/virtual_package_detectors.md) for a complete example with a Rust detector, a local channel, and a package depending on its result.
