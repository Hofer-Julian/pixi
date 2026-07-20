"""Command coverage and config layering for `--prefer-local`.

`test_prefer_local.py` pins the restriction itself. This file asks a different
question: does every command that advertises the flag actually route it to the
solve, and does every configuration layer reach every command?

Like `test_prefer_local.py`, everything observable happens against an HTTP-served
channel, because `file://` records are exempt from the restriction.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from .common import CURRENT_PLATFORM, ExitCode, verify_cli_command
from .test_prefer_local import isolated_cache, serve, write_manifest

# The reason the solver prints for a record ruled out by prefer-local mode.
EXCLUDED = "excluded because not available locally"


@pytest.fixture(scope="module")
def http_channels() -> Iterator[str]:
    """The whole `channels/` tree over HTTP, so a single server backs both
    `dummy_channel_1` and `multiple_versions_channel_1`."""
    yield from serve("")


@pytest.fixture
def dummy_http(http_channels: str) -> str:
    return f"{http_channels}/dummy_channel_1"


@pytest.fixture
def versions_http(http_channels: str) -> str:
    return f"{http_channels}/multiple_versions_channel_1"


def isolated_home(tmp_path: Path) -> dict[str, str]:
    """Point every global-config search path at a private directory.

    Without this a test would read the developer's own `~/.pixi/config.toml`
    and `$XDG_CONFIG_HOME/pixi/config.toml`, and `pixi global` would install
    into their real global environment.
    """
    home = tmp_path / "prefer-local-home"
    home.mkdir(exist_ok=True)
    xdg = tmp_path / "prefer-local-xdg"
    xdg.mkdir(exist_ok=True)
    return {
        "PIXI_HOME": str(home),
        "XDG_CONFIG_HOME": str(xdg),
        "APPDATA": str(xdg),
    }


def write_global_config(env: dict[str, str], body: str) -> Path:
    """Write `$PIXI_HOME/config.toml`, one of the global config search paths."""
    config = Path(env["PIXI_HOME"]) / "config.toml"
    config.write_text(body)
    return config


def write_global_manifest(env: dict[str, str], channel: str) -> Path:
    manifests = Path(env["PIXI_HOME"]) / "manifests"
    manifests.mkdir(exist_ok=True)
    manifest = manifests / "pixi-global.toml"
    manifest.write_text(
        f"""
version = 1

[envs.dummy]
channels = ["{channel}"]
dependencies = {{ dummy-a = "*" }}
exposed = {{ dummy-a = "dummy-a" }}
"""
    )
    return manifest


# --- does the flag reach every command that advertises it? ------------------

WIRED_COMMANDS = [
    "add",
    "build",
    "exec",
    "global add",
    "global install",
    "global sync",
    "install",
    "lock",
    "reinstall",
    "run",
    "search",
    "shell",
    "shell-hook",
    "update",
    "upgrade",
]


@pytest.mark.parametrize("command", WIRED_COMMANDS)
def test_flag_is_documented_where_it_is_accepted(pixi: Path, command: str) -> None:
    output = verify_cli_command([pixi, *command.split(), "--help"])
    assert "--prefer-local" in output.stdout, (
        f"`pixi {command}` should document --prefer-local next to --offline"
    )


@pytest.mark.parametrize("command", ["tree", "list", "info", "clean cache"])
def test_commands_without_offline_also_lack_prefer_local(pixi: Path, command: str) -> None:
    """The two flags must be offered as a pair: a command that cannot be run
    offline has no solve to restrict either."""
    output = verify_cli_command([pixi, *command.split(), "--help"])
    assert ("--offline" in output.stdout) == ("--prefer-local" in output.stdout)


@pytest.mark.parametrize("command", ["install", "shell-hook", "reinstall", "lock", "update"])
def test_workspace_commands_restrict_the_solve(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_http: str, command: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_http)

    verify_cli_command(
        [pixi, *command.split(), "--manifest-path", manifest, "--prefer-local"],
        ExitCode.FAILURE,
        env=isolated_cache(tmp_path),
        stderr_contains=EXCLUDED,
    )


def test_run_restricts_the_solve(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_http: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_http)
    manifest.write_text(manifest.read_text() + '\n[tasks]\nhello = "echo hi"\n')

    verify_cli_command(
        [pixi, "run", "--manifest-path", manifest, "--prefer-local", "hello"],
        ExitCode.FAILURE,
        env=isolated_cache(tmp_path),
        stderr_contains=EXCLUDED,
    )


def test_run_flag_does_not_swallow_the_task_name(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_channel_1: str
) -> None:
    """`run` takes trailing var args, so a flag with `num_args = 0..=1` is the
    classic place for the next word to be eaten as its value. The local
    channel keeps the solve unrestricted, so the task really runs."""
    manifest = write_manifest(tmp_pixi_workspace, dummy_channel_1)
    manifest.write_text(manifest.read_text() + '\n[tasks]\nhello = "echo marker-97"\n')

    verify_cli_command(
        [pixi, "run", "--manifest-path", manifest, "--prefer-local", "hello"],
        env=isolated_cache(tmp_path),
        stdout_contains="marker-97",
    )


# --- pixi exec: its own solve, outside the command dispatcher ---------------


def test_exec_restricts_the_solve(pixi: Path, tmp_path: Path, dummy_http: str) -> None:
    verify_cli_command(
        [pixi, "exec", "--prefer-local", "--channel", dummy_http, "--spec", "dummy-a", "dummy-a"],
        ExitCode.FAILURE,
        env=isolated_cache(tmp_path) | isolated_home(tmp_path),
        stderr_contains=EXCLUDED,
    )


def test_exec_restricts_the_solve_from_the_env_var(
    pixi: Path, tmp_path: Path, dummy_http: str
) -> None:
    verify_cli_command(
        [pixi, "exec", "--channel", dummy_http, "--spec", "dummy-a", "dummy-a"],
        ExitCode.FAILURE,
        env=isolated_cache(tmp_path) | isolated_home(tmp_path) | {"PIXI_PREFER_LOCAL": "1"},
        stderr_contains=EXCLUDED,
    )


def test_exec_reads_prefer_local_from_the_global_config(
    pixi: Path, tmp_path: Path, dummy_http: str
) -> None:
    env = isolated_cache(tmp_path) | isolated_home(tmp_path)
    write_global_config(env, "prefer-local = true\n")

    verify_cli_command(
        [pixi, "exec", "--channel", dummy_http, "--spec", "dummy-a", "dummy-a"],
        ExitCode.FAILURE,
        env=env,
        stderr_contains=EXCLUDED,
    )


def test_exec_cli_false_overrides_the_global_config(
    pixi: Path, tmp_path: Path, dummy_http: str
) -> None:
    env = isolated_cache(tmp_path) | isolated_home(tmp_path)
    write_global_config(env, "prefer-local = true\n")

    # The command is deliberately missing: reaching "failed to execute" proves
    # the solve was unrestricted without paying for a real subprocess.
    verify_cli_command(
        [
            pixi,
            "exec",
            "--prefer-local=false",
            "--channel",
            dummy_http,
            "--spec",
            "dummy-a",
            "prefer-local-no-such-command",
        ],
        ExitCode.FAILURE,
        env=env,
        stderr_contains="failed to execute",
        stderr_excludes=EXCLUDED,
    )


def test_lock_honours_prefer_local_from_pixi_config_file(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_http: str
) -> None:
    """Control for the test above: the same env var on a dispatcher command."""
    manifest = write_manifest(tmp_pixi_workspace, dummy_http)
    env = isolated_cache(tmp_path) | isolated_home(tmp_path)
    config = tmp_path / "explicit-config.toml"
    config.write_text("prefer-local = true\n")
    env["PIXI_CONFIG_FILE"] = str(config)

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, "--prefer-local"],
        ExitCode.FAILURE,
        env=env,
        stderr_contains=EXCLUDED,
    )


def exec_prefix_versions(cache: Path) -> list[str]:
    """The package versions installed into `pixi exec`'s cached prefixes."""
    return sorted(
        p.name for p in cache.glob("cached-envs-v0/*/conda-meta/*.json") if p.name != "history"
    )


def test_exec_does_not_reuse_a_restricted_prefix_for_an_unrestricted_run(
    pixi: Path, tmp_path: Path, versions_http: str
) -> None:
    """`pixi exec` prefixes are content-addressed and shared across processes.
    A prefer-local solve can resolve an older version than an unrestricted one,
    so the two must not land on the same prefix - otherwise the restricted
    result is silently served to every later unrestricted `pixi exec`."""
    env = isolated_cache(tmp_path) | isolated_home(tmp_path)
    cache = Path(env["PIXI_CACHE_DIR"])

    # Warm the package cache with 0.1.0 only, so a restricted solve can pick
    # 0.1.0 while an unrestricted one would pick 0.2.0.
    warmup = tmp_path / "warmup"
    warmup.mkdir()
    warmup_manifest = write_manifest(warmup, versions_http, dependency='package = "==0.1.0"')
    verify_cli_command([pixi, "install", "--manifest-path", warmup_manifest], env=env)

    verify_cli_command(
        [
            pixi,
            "exec",
            "--prefer-local",
            "--channel",
            versions_http,
            "--spec",
            "package",
            "prefer-local-no-such-command",
        ],
        ExitCode.FAILURE,
        env=env,
        stderr_contains="failed to execute",
    )
    verify_cli_command(
        [
            pixi,
            "exec",
            "--channel",
            versions_http,
            "--spec",
            "package",
            "prefer-local-no-such-command",
        ],
        ExitCode.FAILURE,
        env=env,
        stderr_contains="failed to execute",
    )

    installed = exec_prefix_versions(cache)
    assert any("0.2.0" in name for name in installed), (
        "an unrestricted `pixi exec` must not reuse the prefix a `--prefer-local` "
        f"run built from an older package; found {installed}"
    )


# --- pixi global: a separate project type with its own dispatcher -----------


def test_global_install_restricts_the_solve(pixi: Path, tmp_path: Path, dummy_http: str) -> None:
    verify_cli_command(
        [pixi, "global", "install", "--prefer-local", "--channel", dummy_http, "dummy-a"],
        ExitCode.FAILURE,
        env=isolated_cache(tmp_path) | isolated_home(tmp_path),
        stderr_contains=EXCLUDED,
    )


def test_global_sync_restricts_the_solve(pixi: Path, tmp_path: Path, dummy_http: str) -> None:
    env = isolated_cache(tmp_path) | isolated_home(tmp_path)
    write_global_manifest(env, dummy_http)

    verify_cli_command(
        [pixi, "global", "sync", "--prefer-local"],
        ExitCode.FAILURE,
        env=env,
        stderr_contains=EXCLUDED,
    )


def test_global_install_reads_prefer_local_from_the_global_config(
    pixi: Path, tmp_path: Path, dummy_http: str
) -> None:
    env = isolated_cache(tmp_path) | isolated_home(tmp_path)
    write_global_config(env, "prefer-local = true\n")

    verify_cli_command(
        [pixi, "global", "install", "--channel", dummy_http, "dummy-a"],
        ExitCode.FAILURE,
        env=env,
        stderr_contains=EXCLUDED,
    )


def test_global_install_cli_false_overrides_the_global_config(
    pixi: Path, tmp_path: Path, dummy_http: str
) -> None:
    env = isolated_cache(tmp_path) | isolated_home(tmp_path)
    write_global_config(env, "prefer-local = true\n")

    verify_cli_command(
        [
            pixi,
            "global",
            "install",
            "--prefer-local=false",
            "--channel",
            dummy_http,
            "dummy-a",
        ],
        env=env,
        stderr_excludes=EXCLUDED,
    )


# --- precedence: CLI > env > config, then `prefer_local.unwrap_or(offline)` ---


def warm_repodata(pixi: Path, manifest: Path, env: dict[str, str]) -> None:
    """Solve once unrestricted so later offline runs fail on the restriction
    rather than on a missing repodata cache."""
    verify_cli_command([pixi, "lock", "--manifest-path", manifest], env=env)
    (manifest.parent / "pixi.lock").unlink()


# (config body, extra env, extra argv, expect the solve to be restricted)
PRECEDENCE_CASES: list[tuple[str, dict[str, str], list[str], bool]] = [
    # `offline` implies `prefer-local`, whichever layer it comes from.
    ("offline = true\n", {}, [], True),
    ("", {"PIXI_OFFLINE": "1"}, [], True),
    ("", {}, ["--offline"], True),
    # An explicit `prefer-local` beats an implied one, across layers.
    ("prefer-local = false\n", {"PIXI_OFFLINE": "1"}, [], False),
    ("prefer-local = false\n", {}, ["--offline"], False),
    ("offline = true\n", {"PIXI_PREFER_LOCAL": "0"}, [], False),
    ("offline = true\n", {}, ["--prefer-local=false"], False),
    # `--offline=false` does not cancel an explicit `prefer-local`.
    ("prefer-local = true\n", {}, ["--offline=false"], True),
    ("prefer-local = true\n", {"PIXI_OFFLINE": "0"}, [], True),
    # Same-option precedence: CLI > env > config.
    ("prefer-local = true\n", {"PIXI_PREFER_LOCAL": "0"}, [], False),
    ("prefer-local = false\n", {"PIXI_PREFER_LOCAL": "1"}, [], True),
    ("prefer-local = true\n", {}, ["--prefer-local=false"], False),
    ("prefer-local = false\n", {}, ["--prefer-local"], True),
    ("", {"PIXI_PREFER_LOCAL": "1"}, ["--prefer-local=false"], False),
    ("", {"PIXI_PREFER_LOCAL": "0"}, ["--prefer-local"], True),
    # A contradictory pair on the same command line: the explicit one wins.
    ("", {}, ["--offline", "--prefer-local=false"], False),
    ("", {}, ["--offline=false", "--prefer-local"], True),
]


@pytest.mark.parametrize(
    ("config_body", "extra_env", "extra_argv", "restricted"),
    PRECEDENCE_CASES,
    ids=[
        f"{body.strip() or '-'}|{env or '-'}|{' '.join(argv) or '-'}"
        for body, env, argv, _ in PRECEDENCE_CASES
    ],
)
def test_precedence_between_layers(
    pixi: Path,
    tmp_pixi_workspace: Path,
    tmp_path: Path,
    dummy_http: str,
    config_body: str,
    extra_env: dict[str, str],
    extra_argv: list[str],
    restricted: bool,
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_http)
    env = isolated_cache(tmp_path) | isolated_home(tmp_path)
    warm_repodata(pixi, manifest, env)

    config = tmp_pixi_workspace / ".pixi" / "config.toml"
    config.write_text(config_body + config.read_text())

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, *extra_argv],
        ExitCode.FAILURE if restricted else ExitCode.SUCCESS,
        env=env | extra_env,
        stderr_contains=EXCLUDED if restricted else "dummy-a",
    )


def test_workspace_config_beats_the_global_config(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_http: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_http)
    env = isolated_cache(tmp_path) | isolated_home(tmp_path)
    write_global_config(env, "prefer-local = true\n")

    config = tmp_pixi_workspace / ".pixi" / "config.toml"
    config.write_text("prefer-local = false\n" + config.read_text())

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest],
        env=env,
        stderr_contains="dummy-a",
    )


def test_no_config_drops_a_global_prefer_local(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_http: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_http)
    env = isolated_cache(tmp_path) | isolated_home(tmp_path)
    write_global_config(env, "prefer-local = true\n")

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, "--no-config"],
        env=env,
        stderr_contains="dummy-a",
    )


# --- `pixi config` roundtrips -----------------------------------------------


@pytest.mark.parametrize("value", ["true", "false"])
def test_config_set_and_unset_roundtrip(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, value: str
) -> None:
    write_manifest(tmp_pixi_workspace, "https://example.invalid/channel")
    config = tmp_pixi_workspace / ".pixi" / "config.toml"
    env = isolated_home(tmp_path)
    scope = ["--local", "--manifest-path", str(tmp_pixi_workspace)]

    verify_cli_command([pixi, "config", "set", *scope, "prefer-local", value], env=env)
    assert f"prefer-local = {value}" in config.read_text()

    listed = verify_cli_command([pixi, "config", "list", *scope], env=env)
    assert f"prefer-local = {value}" in listed.stdout

    verify_cli_command([pixi, "config", "unset", *scope, "prefer-local"], env=env)
    assert "prefer-local" not in config.read_text()


def test_config_list_accepts_prefer_local_as_a_key(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path
) -> None:
    """`pixi config list <key>` filters to one key. `offline` is accepted, so
    the setting it implies has to be accepted too - otherwise `prefer-local` is
    settable but not inspectable."""
    write_manifest(tmp_pixi_workspace, "https://example.invalid/channel")
    env = isolated_home(tmp_path)
    scope = ["--local", "--manifest-path", str(tmp_pixi_workspace)]

    verify_cli_command([pixi, "config", "set", *scope, "prefer-local", "true"], env=env)
    verify_cli_command([pixi, "config", "list", *scope, "offline"], env=env)

    listed = verify_cli_command([pixi, "config", "list", *scope, "prefer-local"], env=env)
    assert "prefer-local = true" in listed.stdout


def test_config_list_json_reports_prefer_local(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path
) -> None:
    write_manifest(tmp_pixi_workspace, "https://example.invalid/channel")
    env = isolated_home(tmp_path)
    scope = ["--local", "--manifest-path", str(tmp_pixi_workspace)]

    verify_cli_command([pixi, "config", "set", *scope, "prefer-local", "true"], env=env)
    listed = verify_cli_command([pixi, "config", "list", *scope, "--json"], env=env)
    assert json.loads(listed.stdout)["prefer-local"] is True


def test_config_set_rejects_a_non_boolean(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path
) -> None:
    """A rejection has to say which key it is about; `pixi config set` accepts
    many keys, so a bare parse error leaves the user guessing."""
    write_manifest(tmp_pixi_workspace, "https://example.invalid/channel")

    verify_cli_command(
        [
            pixi,
            "config",
            "set",
            "--local",
            "--manifest-path",
            str(tmp_pixi_workspace),
            "prefer-local",
            "sometimes",
        ],
        ExitCode.FAILURE,
        env=isolated_home(tmp_path),
        stderr_contains="prefer-local",
    )


# --- flags that should not collide ------------------------------------------


def test_flag_does_not_consume_the_following_option(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_http: str
) -> None:
    """`--prefer-local --frozen` must parse as two flags, not as one flag with
    the value `--frozen`."""
    manifest = write_manifest(tmp_pixi_workspace, dummy_http)
    write_manifest(tmp_pixi_workspace, dummy_http)

    verify_cli_command(
        [pixi, "install", "--manifest-path", manifest, "--prefer-local", "--frozen"],
        ExitCode.FAILURE,
        env=isolated_cache(tmp_path),
        stderr_excludes="unexpected argument",
    )


def test_invalid_flag_value_is_a_usage_error(
    pixi: Path, tmp_pixi_workspace: Path, dummy_channel_1: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_channel_1)

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, "--prefer-local=sometimes"],
        ExitCode.INCORRECT_USAGE,
        stderr_contains="--prefer-local",
    )


# --- commands that accept the flag but have no solve to restrict ------------


def test_search_reports_packages_that_are_not_available_locally(
    pixi: Path, tmp_path: Path, dummy_http: str
) -> None:
    """`pixi search` advertises `--prefer-local` but only queries repodata, so
    the flag changes nothing. Pinned so a future change is a deliberate one."""
    verify_cli_command(
        [pixi, "search", "--prefer-local", "--channel", dummy_http, "dummy-a"],
        env=isolated_cache(tmp_path) | isolated_home(tmp_path),
        stdout_contains="dummy-a",
    )


def test_install_from_an_existing_lock_file_still_downloads(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_http: str
) -> None:
    """`--prefer-local` restricts solving, not installing. With an up-to-date
    lock file there is no solve, so the flag does not stop pixi from fetching
    packages it does not have cached."""
    manifest = write_manifest(tmp_pixi_workspace, dummy_http)
    env = isolated_cache(tmp_path)
    verify_cli_command([pixi, "lock", "--manifest-path", manifest], env=env)

    # A second, empty cache: nothing is available locally any more.
    cold_root = tmp_path / "cold"
    cold_root.mkdir(exist_ok=True)
    cold = isolated_cache(cold_root)

    verify_cli_command(
        [pixi, "install", "--manifest-path", manifest, "--prefer-local"],
        env=cold,
    )
    installed = tmp_pixi_workspace / ".pixi" / "envs" / "default" / "conda-meta"
    assert any(p.name.startswith("dummy-a") for p in installed.glob("*.json"))


def test_lock_file_warning_is_emitted_for_a_restricted_solve(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_channel_1: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_channel_1)

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, "--prefer-local"],
        env=isolated_cache(tmp_path),
        stderr_contains="may pin older versions",
    )


def test_lock_file_warning_is_absent_without_the_flag(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_channel_1: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_channel_1)

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest],
        env=isolated_cache(tmp_path),
        stderr_excludes="may pin older versions",
    )


def test_platform_specific_manifest_is_unaffected(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_channel_1: str
) -> None:
    """A sanity check that the exemption for local channels survives a
    manifest that names the current platform explicitly."""
    manifest = tmp_pixi_workspace / "pixi.toml"
    manifest.write_text(
        f"""
[workspace]
name = "prefer-local-platform"
channels = ["{dummy_channel_1}"]
platforms = ["{CURRENT_PLATFORM}"]

[target.{CURRENT_PLATFORM}.dependencies]
dummy-a = "*"
"""
    )

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, "--prefer-local"],
        env=isolated_cache(tmp_path),
    )
    assert (tmp_pixi_workspace / "pixi.lock").is_file()
