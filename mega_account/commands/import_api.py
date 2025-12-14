"""Import command to import accounts from API."""
import asyncio
import typer
from typing import Optional
import logging
from mega_account import AccountManager


def import_from_api(
    api_url: str = typer.Option("http://127.0.0.1:9932", "--api-url", "-u", help="API server URL"),
    master_password: Optional[str] = typer.Option(None, "--master-password", "-p", help="Master password (prompted if not provided)"),
    collection_name: Optional[str] = typer.Option(None, "--collection", "-c", help="Collection name to import only accounts from that collection"),
    log_level: str = typer.Option("WARN", "--log-level", "-l", help="Logging level (e.g., DEBUG, INFO, WARN, ERROR)")
):
    """
    Import all accounts from API.
    
    Fetches all accounts from the API, decrypts passwords using master password,
    logs in to each account, and saves session files.

    If --collection (-c) is provided, only imports accounts from that collection.
    """
    # Set logging level
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        typer.echo(f"Invalid log level: {log_level}", err=True)
        raise typer.Exit(1)
    logging.basicConfig(level=numeric_level)
    asyncio.run(_import_from_api(api_url, master_password, collection_name))


async def _import_from_api(api_url: str, master_password: Optional[str], collection_name: Optional[str]):
    """Import accounts from API."""
    async with AccountManager(auto_load=False) as manager:
        try:
            accounts = await manager.import_from_api(
                api_url=api_url,
                master_password=master_password,
                collection_name=collection_name
            )
            collection_msg = f" from collection '{collection_name}'" if collection_name else ""
            typer.echo(f"\n✓ Successfully imported {len(accounts)} account(s){collection_msg}")
        except Exception as e:
            typer.echo(f"✗ Failed to import accounts: {e}", err=True)
            raise typer.Exit(1)

