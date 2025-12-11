"""Import command to import accounts from API."""
import asyncio
import typer
from typing import Optional
from mega_account import AccountManager


def import_from_api(
    api_url: str = typer.Option("http://127.0.0.1:9932", "--api-url", "-u", help="API server URL"),
    master_password: Optional[str] = typer.Option(None, "--master-password", "-p", help="Master password (prompted if not provided)"),
    collection_name: Optional[str] = typer.Option(None, "--collection", "-c", help="Collection name to import only accounts from that collection")
):
    """
    Import all accounts from API.
    
    Fetches all accounts from the API, decrypts passwords using master password,
    logs in to each account, and saves session files.
    
    If --collection (-c) is provided, only imports accounts from that collection.
    """
    asyncio.run(_import_from_api(api_url, master_password, collection_name))


async def _import_from_api(api_url: str, master_password: Optional[str], collection_name: Optional[str]):
    """Import accounts from API."""
    async with AccountManager() as manager:
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

