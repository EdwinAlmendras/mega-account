"""Add command to create a new MEGA account session."""
import asyncio
import typer
from mega_account import AccountManager


def add(
    email: str = typer.Argument(..., help="MEGA account email"),
    password: str = typer.Argument(..., help="MEGA account password")
):
    """Add a new MEGA account session."""
    asyncio.run(_add_session(email, password))


async def _add_session(email: str, password: str):
    """Create a new MEGA account session."""
    async with AccountManager() as manager:
        try:
            account = await manager.create_new_session(
                email=email,
                password=password
            )
            typer.echo(f"✓ Session created successfully: {account.name}")
        except Exception as e:
            typer.echo(f"✗ Failed to create session: {e}", err=True)
            raise typer.Exit(1)

