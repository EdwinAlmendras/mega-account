"""CLI entry point for mega-account."""
import typer
from .commands import info
from .commands.add import add
from .commands.import_api import import_from_api

app = typer.Typer()
app.add_typer(info.app, name="info")
app.command("add")(add)
app.command("import")(import_from_api)


def main():
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()

