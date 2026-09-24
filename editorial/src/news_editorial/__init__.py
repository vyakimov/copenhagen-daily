__version__ = "0.1.0"


def main() -> None:
    import sys

    from .cli import main as cli_main

    sys.exit(cli_main())
