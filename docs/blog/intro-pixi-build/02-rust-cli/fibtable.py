import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

# --8<-- [start:locate]
# The binary lands under target/release, and gets a .exe suffix on Windows.
BINARY = (
    Path(__file__).parent
    / "fib"
    / "target"
    / "release"
    / ("fib.exe" if sys.platform == "win32" else "fib")
)
# --8<-- [end:locate]


# --8<-- [start:call]
def fib(n: int) -> int:
    result = subprocess.run(
        [str(BINARY), str(n)], capture_output=True, text=True, check=True
    )
    return int(result.stdout)
# --8<-- [end:call]


def main() -> None:
    console = Console()
    table = Table(title="Fibonacci")
    table.add_column("n", justify="right")
    table.add_column("fib(n)", justify="right")
    for n in (10, 20, 30):
        table.add_row(str(n), str(fib(n)))
    console.print(table)


if __name__ == "__main__":
    main()
