"""Info command to show account information."""
import asyncio
import typer
from megapy.core.session import SQLiteSession
from mega_account import AccountManager

app = typer.Typer()


@app.command()
def info():
    """Show information about all MEGA accounts."""
    asyncio.run(_show_info())


async def _show_info():
    """Display account information."""
    async with AccountManager() as manager:
        accounts = await manager.load_accounts(refresh_space=True)
        
        if not accounts:
            typer.echo("No accounts found.", err=True)
            raise typer.Exit(1)
        
        for account in accounts:
            # Get email from session file
            try:
                session = SQLiteSession(account.session_path)
                session_data = session.load()
                email = session_data.email if session_data else "N/A"
                session.close()
            except Exception:
                email = "N/A"
            
            # Get space used in GB
            space_used_gb = account.space_used_gb
            
            # Display info: EMAIL | SPACE_USED_IN_GB
            typer.echo(f"{email} | {space_used_gb:.2f}")


if __name__ == "__main__":
    app()

