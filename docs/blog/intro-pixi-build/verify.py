"""Prove every example in this blog post at least installs, and that the
pixi-build stage runs end to end and produces a publishable artifact.

Usage:
    python verify.py            # install all stages; run + publish stage 03
    python verify.py --full     # additionally build the source-CPython finale

Set PIXI=/path/to/pixi to use a specific pixi binary (the pixi-build stages
need a recent pixi that speaks pixi-build-api-version >=5).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
PIXI = os.environ.get("PIXI", "pixi")

FAST_STAGES = ["01-python", "02-rust-cli", "03-pixi-build"]


def run(args: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(args)}  (in {cwd.relative_to(HERE)})", flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="also build the source-CPython finale (slow, Linux/macOS only)",
    )
    args = parser.parse_args()

    for stage in FAST_STAGES:
        run([PIXI, "install"], HERE / stage)

    stage3 = HERE / "03-pixi-build"
    run([PIXI, "run", "start"], stage3)
    run([PIXI, "publish", "--target-dir", "./dist"], stage3)
    artifacts = sorted((stage3 / "dist").rglob("*.conda"))
    if not artifacts:
        print("error: pixi publish produced no .conda artifact", file=sys.stderr)
        return 1
    print(f"published artifacts: {[a.name for a in artifacts]}")

    if args.full:
        stage4 = HERE / "04-freethreading"
        run([PIXI, "install"], stage4)
        run([PIXI, "run", "start"], stage4)
        run([PIXI, "run", "gil"], stage4)

    print("\nAll examples verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
