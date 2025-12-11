"""Add command to create a new MEGA account session."""
import asyncio
import typer
from typing import Optional
from mega_account import AccountManager
from mega_account.api_client import AccountAPIClient


def add(
    email: str = typer.Argument(..., help="MEGA account email"),
    password: str = typer.Argument(..., help="MEGA account password"),
    collection_name: Optional[str] = typer.Option(None, "--collection-name", "-c", help="Collection name to store account in API"),
    collection_id: Optional[int] = typer.Option(None, "--collection-id", help="Collection ID to store account in API"),
    api_url: Optional[str] = typer.Option(None, "--api-url", help="API URL (if not provided, only creates local session)")
):
    """
    Add a new MEGA account session.
    
    Creates a session file named md5(email).session.
    Optionally saves account to API if --api-url is provided.
    """
    asyncio.run(_add_session(email, password, collection_name, collection_id, api_url))


async def _add_session(
    email: str,
    password: str,
    collection_name: Optional[str] = None,
    collection_id: Optional[int] = None,
    api_url: Optional[str] = None
):
    """Create a new MEGA account session and optionally save to API."""
    async with AccountManager() as manager:
        try:
            # Create local session file (md5(email).session)
            account = await manager.create_new_session(
                email=email,
                password=password
            )
            typer.echo(f"✓ Session created successfully: {account.name}")
            
            # Optionally save to API
            if api_url:
                try:
                    async with AccountAPIClient(api_url=api_url) as api:
                        result = await api.add_account(
                            email=email,
                            password=password,
                            collection_name=collection_name,
                            collection_id=collection_id
                        )
                        typer.echo(f"✓ Account saved to API (ID: {result['account_id']})")
                except Exception as e:
                    typer.echo(f"⚠ Warning: Failed to save to API: {e}", err=True)
                    # Don't fail the whole operation if API save fails
        except Exception as e:
            typer.echo(f"✗ Failed to create session: {e}", err=True)
            raise typer.Exit(1)

