from enum import StrEnum
import subprocess
import sys


class Colors(StrEnum):
    GREEN = "\033[92m"
    RED = "\033[91m"
    RESET = "\033[0m"


def colored_print(message: str, color: Colors) -> None:
    print(f"{color}{message}{Colors.RESET}")


def check_openssl_dependency() -> None:
    # Run the cargo tree command
    result = subprocess.run(
        ["cargo", "tree", "-i", "openssl", "--workspace"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        colored_print("Error: openssl is part of the dependencies tree", Colors.RED)
        print(result.stdout)
        sys.exit(1)

    # Check if the error message matches the expected message
    if "package ID specification `openssl` did not match any packages" in result.stderr:
        colored_print("Success: openssl is not part of the dependencies tree.", Colors.GREEN)
    else:
        colored_print("Error: Unexpected error message.", Colors.RED)
        print(result.stderr)
        sys.exit(1)


if __name__ == "__main__":
    check_openssl_dependency()