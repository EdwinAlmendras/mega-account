"""CLI entry point for mega-account."""
import typer
from .commands import info

app = typer.Typer()
app.add_typer(info.app, name="info")


def main():
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()

