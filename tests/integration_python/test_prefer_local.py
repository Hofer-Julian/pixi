"""Integration tests for `--prefer-local` / `PIXI_PREFER_LOCAL` / `prefer-local`.

The restriction is only observable against a channel whose records are *not*
`file://`, since local channels are carved out unconditionally. A plain HTTP
server over one of the dummy channels gives records with `http://` URLs while
staying fast and network-free.
"""

import functools
import http.server
import socketserver
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from .common import CURRENT_PLATFORM, ExitCode, verify_cli_command


def serve(channel_name: str) -> Iterator[str]:
    """Serve a test channel over HTTP so its records carry `http://` URLs."""
    directory = str(
        Path(__file__).parents[1].joinpath("data", "channels", "channels", channel_name).resolve()
    )

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

    handler = functools.partial(QuietHandler, directory=directory)

    # Port 0 lets the OS pick a free port, so parallel xdist workers don't collide.
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def http_channel() -> Iterator[str]:
    yield from serve("dummy_channel_1")


@pytest.fixture(scope="module")
def http_versions_channel() -> Iterator[str]:
    """A channel offering both `package` 0.1.0 and 0.2.0."""
    yield from serve("multiple_versions_channel_1")


def write_manifest(workspace: Path, channel: str, dependency: str = 'dummy-a = "*"') -> Path:
    manifest = workspace / "pixi.toml"
    manifest.write_text(
        f"""
[workspace]
name = "prefer-local-test"
channels = ["{channel}"]
platforms = ["{CURRENT_PLATFORM}"]

[dependencies]
{dependency}
"""
    )
    return manifest


def isolated_cache(tmp_path: Path) -> dict[str, str]:
    """A private package/repodata cache, so one test can't warm another's."""
    cache = tmp_path / "prefer-local-cache"
    cache.mkdir(exist_ok=True)
    return {"PIXI_CACHE_DIR": str(cache)}


def enable_prefer_local_in_config(workspace: Path) -> None:
    """Prepend the key: the fixture's config ends inside a `[repodata-config...]`
    table, so appending would nest `prefer-local` under it."""
    config = workspace / ".pixi" / "config.toml"
    config.write_text("prefer-local = true\n" + config.read_text())


# --- the restriction itself -------------------------------------------------


def test_remote_records_are_excluded_with_a_reason(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, http_channel: str
) -> None:
    """The failure must name the restriction, not report a bare missing package."""
    manifest = write_manifest(tmp_pixi_workspace, http_channel)

    output = verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, "--prefer-local"],
        ExitCode.FAILURE,
        env=isolated_cache(tmp_path),
        stderr_contains="not available locally",
    )
    # A bare "no candidates" would hide *why* the package was unusable.
    assert "excluded because not available locally" in output.stderr


def test_local_channel_is_exempt_from_the_restriction(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_channel_1: str
) -> None:
    """`file://` records need no download, so prefer-local must not exclude them."""
    manifest = write_manifest(tmp_pixi_workspace, dummy_channel_1)

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, "--prefer-local"],
        env=isolated_cache(tmp_path),
        stderr_contains="dummy-a",
    )
    assert (tmp_pixi_workspace / "pixi.lock").is_file()


def test_unrestricted_solve_against_the_same_channel_succeeds(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, http_channel: str
) -> None:
    """Control: the HTTP channel is solvable, so the failure above is the flag."""
    manifest = write_manifest(tmp_pixi_workspace, http_channel)

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest],
        env=isolated_cache(tmp_path),
        stderr_contains="dummy-a",
    )


# --- offline implies prefer-local, explicit beats implied ---------------------


def test_offline_implies_prefer_local(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, http_channel: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, http_channel)
    env = isolated_cache(tmp_path)

    # Warm the repodata cache so the solve fails on the restriction rather
    # than on offline mode refusing to fetch repodata.
    verify_cli_command([pixi, "lock", "--manifest-path", manifest], env=env)
    (tmp_pixi_workspace / "pixi.lock").unlink()

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, "--offline"],
        ExitCode.FAILURE,
        env=env,
        stderr_contains="not available locally",
    )


def test_explicit_prefer_local_false_beats_offline(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, http_channel: str
) -> None:
    """`--prefer-local=false` is the escape hatch back to pre-flag offline mode."""
    manifest = write_manifest(tmp_pixi_workspace, http_channel)
    env = isolated_cache(tmp_path)

    verify_cli_command([pixi, "lock", "--manifest-path", manifest], env=env)
    (tmp_pixi_workspace / "pixi.lock").unlink()

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, "--offline", "--prefer-local=false"],
        env=env,
        stderr_contains="dummy-a",
    )


def lock_with_cold_cache(
    pixi: Path, manifest: Path, tmp_path: Path, extra: list[str] | None = None
) -> list[str]:
    """Warm the repodata cache but not the package cache, then return the
    argv for a lock that will hit the prefer-local restriction if it is on.

    This is the observable the plumbing tests use: solving is what `prefer-local`
    changes, so assert on solving rather than on a command that merely happens
    to react to the flag.
    """
    env = isolated_cache(tmp_path)
    verify_cli_command([pixi, "lock", "--manifest-path", manifest], env=env)
    (manifest.parent / "pixi.lock").unlink()
    return [pixi, "lock", "--manifest-path", manifest, *(extra or [])]


# --- flag / env var / config plumbing ---------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_truthy_env_values_enable_prefer_local(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, http_channel: str, value: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, http_channel)
    argv = lock_with_cold_cache(pixi, manifest, tmp_path)

    verify_cli_command(
        argv,
        ExitCode.FAILURE,
        env=isolated_cache(tmp_path) | {"PIXI_PREFER_LOCAL": value},
        stderr_contains="not available locally",
    )


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_falsy_env_values_disable_prefer_local(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, http_channel: str, value: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, http_channel)
    argv = lock_with_cold_cache(pixi, manifest, tmp_path)

    verify_cli_command(
        argv,
        env=isolated_cache(tmp_path) | {"PIXI_PREFER_LOCAL": value},
        stderr_contains="dummy-a",
    )


def test_invalid_env_value_is_rejected(
    pixi: Path, tmp_pixi_workspace: Path, dummy_channel_1: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_channel_1)

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest],
        ExitCode.INCORRECT_USAGE,
        env={"PIXI_PREFER_LOCAL": "bogus"},
        stderr_contains="value was not a boolean",
    )


def test_flag_requires_equals_for_its_value(
    pixi: Path, tmp_pixi_workspace: Path, dummy_channel_1: str
) -> None:
    """`--prefer-local false` must not silently enable the flag and eat `false`."""
    manifest = write_manifest(tmp_pixi_workspace, dummy_channel_1)

    verify_cli_command(
        [pixi, "lock", "--manifest-path", manifest, "--prefer-local", "false"],
        ExitCode.INCORRECT_USAGE,
        stderr_contains="unexpected argument",
    )


def test_config_prefer_local_is_honoured(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, http_channel: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, http_channel)
    argv = lock_with_cold_cache(pixi, manifest, tmp_path)
    enable_prefer_local_in_config(tmp_pixi_workspace)

    verify_cli_command(
        argv,
        ExitCode.FAILURE,
        env=isolated_cache(tmp_path),
        stderr_contains="not available locally",
    )


def test_cli_prefer_local_false_overrides_config(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, http_channel: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, http_channel)
    argv = lock_with_cold_cache(pixi, manifest, tmp_path, ["--prefer-local=false"])
    enable_prefer_local_in_config(tmp_pixi_workspace)

    verify_cli_command(argv, env=isolated_cache(tmp_path), stderr_contains="dummy-a")


def test_config_set_prefer_local_roundtrip(
    pixi: Path, tmp_pixi_workspace: Path, dummy_channel_1: str
) -> None:
    write_manifest(tmp_pixi_workspace, dummy_channel_1)
    config = tmp_pixi_workspace / ".pixi" / "config.toml"

    verify_cli_command(
        [
            pixi,
            "config",
            "set",
            "--local",
            "--manifest-path",
            tmp_pixi_workspace,
            "prefer-local",
            "true",
        ],
    )
    assert "prefer-local = true" in config.read_text()


# --- commands that react to the mode ----------------------------------------


def test_upgrade_works_under_prefer_local(
    pixi: Path, tmp_pixi_workspace: Path, http_channel: str
) -> None:
    """`upgrade` is not special-cased: it runs and rewrites the manifest exactly
    as it does online, from whatever the restricted solve resolved."""
    manifest = write_manifest(tmp_pixi_workspace, http_channel)

    verify_cli_command(
        [pixi, "upgrade", "--manifest-path", manifest, "--prefer-local"],
    )
    assert 'dummy-a = ">=0.1.0,<0.2"' in manifest.read_text()


def test_upgrade_works_with_a_local_channel(
    pixi: Path, tmp_pixi_workspace: Path, dummy_channel_1: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_channel_1)

    verify_cli_command(
        [pixi, "upgrade", "--manifest-path", manifest, "--prefer-local"],
    )
    assert 'dummy-a = ">=0.1.0,<0.2"' in manifest.read_text()


def test_upgrade_dry_run_works(pixi: Path, tmp_pixi_workspace: Path, http_channel: str) -> None:
    manifest = write_manifest(tmp_pixi_workspace, http_channel)
    before = manifest.read_text()

    verify_cli_command(
        [pixi, "upgrade", "--manifest-path", manifest, "--prefer-local", "--dry-run"],
    )
    assert manifest.read_text() == before, "a dry run must not touch the manifest"


def test_update_warns_that_the_lock_file_may_be_stale(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, dummy_channel_1: str
) -> None:
    manifest = write_manifest(tmp_pixi_workspace, dummy_channel_1)

    verify_cli_command(
        [pixi, "update", "--manifest-path", manifest, "--prefer-local"],
        env=isolated_cache(tmp_path),
        stderr_contains=["may pin older versions", "pixi.lock"],
    )


def test_add_pins_from_the_restricted_solve(
    pixi: Path, tmp_pixi_workspace: Path, tmp_path: Path, http_versions_channel: str
) -> None:
    """`add` is not special-cased either. The channel offers 0.2.0 but only
    0.1.0 is cached, so the bound recorded describes what was available
    locally. That is a deliberate choice, so pin it."""
    env = isolated_cache(tmp_path)

    # Warm the package cache with 0.1.0 only.
    warmup = tmp_path / "warmup"
    warmup.mkdir()
    warmup_manifest = write_manifest(
        warmup, http_versions_channel, dependency='package = "==0.1.0"'
    )
    verify_cli_command([pixi, "install", "--manifest-path", warmup_manifest], env=env)

    manifest = write_manifest(tmp_pixi_workspace, http_versions_channel, dependency="")
    verify_cli_command(
        [pixi, "add", "--manifest-path", manifest, "--prefer-local", "--no-install", "package"],
        env=env,
    )

    assert ">=0.1.0,<0.2" in manifest.read_text(), (
        "`pixi add --prefer-local` should record a bound from the version it "
        f"resolved locally:\n{manifest.read_text()}"
    )
