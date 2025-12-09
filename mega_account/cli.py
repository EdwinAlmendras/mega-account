"""CLI entry point for mega-account."""
import typer
from .commands import info
from .commands.add import add

app = typer.Typer()
app.add_typer(info.app, name="info")
app.command("add")(add)


def main():
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()

