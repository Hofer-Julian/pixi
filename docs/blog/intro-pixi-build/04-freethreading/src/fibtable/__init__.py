import subprocess

from rich.console import Console
from rich.table import Table


# --8<-- [start:call]
def fib(n: int) -> int:
    # `fib` is on PATH: it was built from source and installed into the environment.
    result = subprocess.run(
        ["fib", str(n)], capture_output=True, text=True, check=True
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
