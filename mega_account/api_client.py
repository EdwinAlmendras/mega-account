"""REST client for mega-account-api."""
import httpx
from typing import Optional, List
from pathlib import Path
import asyncio
import logging

logger = logging.getLogger(__name__)


class AccountAPIClient:
    """Client for communicating with mega-account-api."""
    
    def __init__(self, api_url: str = "http://127.0.0.1:8000"):
        """
        Initialize API client.
        
        Args:
            api_url: Base URL of the API server
        """
        self.api_url = api_url.rstrip('/')
        self.client = httpx.AsyncClient(base_url=self.api_url, timeout=30.0)
    
    async def add_account(
        self,
        email: str,
        password: str,
        collection_name: Optional[str] = None,
        collection_id: Optional[int] = None
    ) -> dict:
        """
        Add an account via API.
        
        Args:
            email: Account email
            password: Account password
            collection_name: Collection name (optional)
            collection_id: Collection ID (optional)
            
        Returns:
            Response dict with account info
        """
        payload = {
            "email": email,
            "password": password
        }
        if collection_name:
            payload["collection_name"] = collection_name
        if collection_id:
            payload["collection_id"] = collection_id
        
        try:
            response = await self.client.post("/add", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"API error adding account: {e}")
            raise
    
    async def get_collection_emails(
        self,
        collection_name: Optional[str] = None,
        collection_id: Optional[int] = None
    ) -> List[str]:
        """
        Get all email addresses in a collection.
        
        Args:
            collection_name: Collection name (optional)
            collection_id: Collection ID (optional)
            
        Returns:
            List of email addresses
        """
        params = {}
        if collection_name:
            params["name"] = collection_name
        if collection_id:
            params["id"] = collection_id
        
        try:
            response = await self.client.get("/collection", params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("emails", [])
        except httpx.HTTPError as e:
            logger.error(f"API error getting collection: {e}")
            raise
    
    async def get_account(self, email: str, encrypted: bool = False) -> dict:
        """
        Get account information.
        
        Args:
            email: Account email
            encrypted: If True, returns encrypted password. If False, returns decrypted password.
            
        Returns:
            Account dict with email, password, and collection_id
        """
        try:
            response = await self.client.get(
                "/get",
                params={"email": email, "encrypted": encrypted}
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"API error getting account: {e}")
            raise
    
    async def get_all_accounts(self) -> List[dict]:
        """
        Get all accounts with encrypted passwords.
        
        Returns:
            List of account dicts with encrypted passwords
        """
        try:
            response = await self.client.get("/get_all")
            response.raise_for_status()
            data = response.json()
            return data.get("accounts", [])
        except httpx.HTTPError as e:
            logger.error(f"API error getting all accounts: {e}")
            raise
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, *args):
        """Async context manager exit."""
        await self.close()

