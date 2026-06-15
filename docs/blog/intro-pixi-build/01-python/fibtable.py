from rich.console import Console
from rich.table import Table


# --8<-- [start:fib]
def fib(n: int) -> int:
    """The nth Fibonacci number."""
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
# --8<-- [end:fib]


# --8<-- [start:render]
def main() -> None:
    console = Console()
    table = Table(title="Fibonacci")
    table.add_column("n", justify="right")
    table.add_column("fib(n)", justify="right")
    for n in (10, 20, 30):
        table.add_row(str(n), str(fib(n)))
    console.print(table)
# --8<-- [end:render]


if __name__ == "__main__":
    main()
