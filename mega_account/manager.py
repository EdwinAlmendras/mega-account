"""
MEGA Account Manager - Manages multiple MEGA accounts for optimal storage usage.

Features:
- Auto-discovery of session files from ~/.config/mega/sessions/
- Account space tracking
- Automatic account selection based on free space
- Account rotation when full
- Auto-create new session when all accounts are full
- Upload planning across multiple accounts
"""
import asyncio
import os
from pathlib import Path
from typing import Optional, List, Dict, Callable, Any
from datetime import datetime, timedelta
import logging
import getpass
import hashlib

from megapy import MegaClient, AccountInfo

from .models import ManagedAccount, AccountSelection, UploadPlan
from .api_client import AccountAPIClient
from .exceptions import (
    NoAccountsError,
    NoSpaceError,
    AllAccountsFullError,
    AccountConnectionError,
    SessionNotFoundError
)

logger = logging.getLogger(__name__)

# Proxy configuration - read from environment variable
PROXY_URL = os.getenv("MEGA_PROXY_URL")


class AccountManager:
    """
    Manages multiple MEGA accounts for storage operations.
    
    Sessions are stored in ~/.config/mega/sessions/
    
    Features:
    - Auto-discovers session files from sessions directory
    - Tracks space usage across accounts
    - Selects best account for uploads
    - Rotates to next account when one is full
    - Creates new session interactively when all are full
    
    Usage:
        >>> async with AccountManager() as manager:
        ...     # Auto-selects best account
        ...     client = await manager.get_client_for(file_size)
        ...     await client.upload(file_path)
        
        >>> # Or with auto-rotation
        >>> async with AccountManager() as manager:
        ...     await manager.upload_with_rotation(file_path, dest="/Videos")
    
    Session directory:
        ~/.config/mega/sessions/
        ├── account1.session
        ├── account2.session
        └── backup.session
    """
    
    DEFAULT_SESSIONS_DIR = Path.home() / ".config" / "mega" / "sessions"
    CACHE_TTL = timedelta(minutes=5)  # How long to cache space info
    
    def __init__(
        self,
        sessions_dir: Optional[Path] = None,
        session_pattern: str = "*.session",
        buffer_mb: int = 100,
        auto_create: bool = True,
        auto_load: bool = True
    ):
        """
        Initialize account manager.
        
        Args:
            sessions_dir: Directory containing session files (default: ~/.config/mega/sessions/)
            session_pattern: Glob pattern for session files
            buffer_mb: Buffer space to keep free (MB)
            auto_create: Auto-create new session if all accounts are full
            auto_load: Automatically load all accounts in __aenter__ (default: True)
        """
        if not sessions_dir:
            sessions_dir = os.getenv("MEGA_SESSIONS_DIR")
            if sessions_dir:
                sessions_dir = Path(sessions_dir)
            if not sessions_dir:
                sessions_dir = self.DEFAULT_SESSIONS_DIR
            if not sessions_dir.exists():
                sessions_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Sessions directory: {sessions_dir}")
        
        self._sessions_dir = Path(sessions_dir)
        self._session_pattern = session_pattern
        self._buffer_mb = buffer_mb
        self._auto_create = auto_create
        self._auto_load = auto_load
        
        self._accounts: Dict[str, ManagedAccount] = {}
        self._clients: Dict[str, MegaClient] = {}
        self._current_account: Optional[str] = None
        
        # Ensure sessions directory exists
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
    
    @property
    def accounts(self) -> List[ManagedAccount]:
        """Get all managed accounts."""
        return list(self._accounts.values())
    
    @property
    def active_accounts(self) -> List[ManagedAccount]:
        """Get active (usable) accounts."""
        return [a for a in self._accounts.values() if a.is_active]
    
    @property
    def total_space_free(self) -> int:
        """Total free space across all accounts."""
        return sum(a.space_free for a in self.active_accounts)
    
    @property
    def total_space_free_gb(self) -> float:
        """Total free space in GB."""
        return self.total_space_free / (1024 ** 3)
    
    @property
    def sessions_dir(self) -> Path:
        """Get sessions directory path."""
        return self._sessions_dir
    
    async def load_accounts(self, refresh_space: bool = True) -> List[ManagedAccount]:
        """
        Discover and load all accounts from sessions directory.
        
        Also checks for legacy single session at ~/.config/mega/session.session
        
        Args:
            refresh_space: Whether to query space info from MEGA
            
        Returns:
            List of discovered accounts
        """
        # Find all session files
        session_files = list(self._sessions_dir.glob(self._session_pattern))
        
        if not session_files:
            logger.info(f"No session files found in {self._sessions_dir}")
            return []
        
        logger.info(f"Found {len(session_files)} session(s)")
        
        # Load each account
        for session_path in sorted(session_files):
            name = session_path.stem
            
            if name not in self._accounts:
                self._accounts[name] = ManagedAccount(
                    session_path=session_path,
                    name=name,
                    priority=len(self._accounts)
                )
        
        # Refresh space info if requested
        if refresh_space:
            await self.refresh_all()
        
        return self.accounts
    
    async def add_account(
        self,
        session_path: Path,
        name: Optional[str] = None,
        priority: int = 0
    ) -> ManagedAccount:
        """
        Add a specific account.
        
        Args:
            session_path: Path to session file
            name: Display name (defaults to filename)
            priority: Account priority (lower = preferred)
        """
        session_path = Path(session_path)
        
        if not session_path.exists():
            raise SessionNotFoundError(str(session_path))
        
        account = ManagedAccount(
            session_path=session_path,
            name=name or session_path.stem,
            priority=priority
        )
        
        self._accounts[account.name] = account
        
        # Refresh space info
        await self._refresh_account(account)
        
        return account
    
    async def refresh_all(self) -> None:
        """Refresh space info for all accounts."""
        for account in self._accounts.values():
            logger.info(f"Refreshing space info for account: {account.name}")
            await self._refresh_account(account)
            logger.info(f"Refreshed space info for account: {account.name}")
    
    async def _refresh_account(self, account: ManagedAccount) -> None:
        """Refresh space info for a single account."""
        try:
            client = await self._get_or_create_client(account)
            info = await client.get_account_info()
            
            account.space_free = info.space_free
            account.space_total = info.space_total
            account.space_used = info.space_used
            account.last_checked = datetime.now()
            account.is_active = True
            
            logger.debug(f"Refreshed {account.name}: {account.space_free_gb:.1f} GB free")
            
        except Exception as e:
            logger.error(f"Failed to refresh {account.name}: {e}")
            account.is_active = False
    
    async def _get_or_create_client(self, account: ManagedAccount) -> MegaClient:
        """Get or create a MegaClient for an account."""
        if account.name not in self._clients:
            config = MegaClient.create_config(proxy=PROXY_URL)
            client = MegaClient(str(account.session_path), config=config)
            await client.start()
            self._clients[account.name] = client
        
        return self._clients[account.name]
    
    def get_best_account(self, file_size: int) -> Optional[ManagedAccount]:
        """
        Get the best account for a file of given size.
        
        Selection criteria:
        1. Has enough space (with buffer)
        2. Lowest priority (prefer primary accounts)
        3. Most free space (to balance usage)
        
        Args:
            file_size: File size in bytes
            
        Returns:
            Best account or None if no account has space
        """
        candidates = [
            a for a in self.active_accounts
            if a.has_space_for(file_size, self._buffer_mb)
        ]
        
        if not candidates:
            return None
        
        # Sort by priority, then by free space (descending)
        candidates.sort(key=lambda a: (a.priority, -a.space_free))
        
        return candidates[0]
    
    async def exists(self, path: str) -> bool:
        """
        Check if a file/folder exists in ANY account.
        
        Searches across all active accounts.
        
        Args:
            path: Path to check (e.g., "/Social/youtube/video.mp4")
            
        Returns:
            True if exists in any account
        """
        if not self._accounts:
            await self.load_accounts(refresh_space=False)
        
        # Normalize path
        if not path.startswith("/"):
            path = f"/{path}"
        
        # Check each account
        for account in self.active_accounts:
            try:
                client = await self._get_or_create_client(account)
                node = await client.get(path)
                if node:
                    logger.debug(f"Found {path} in account {account.name}")
                    return True
            except Exception as e:
                logger.debug(f"Error checking {path} in {account.name}: {e}")
                continue
        
        return False
    
    async def find_in_accounts(self, path: str) -> Optional[tuple]:
        """
        Find which account contains a file/folder.
        
        Args:
            path: Path to find
            
        Returns:
            Tuple of (account, node) if found, None otherwise
        """
        if not self._accounts:
            await self.load_accounts(refresh_space=False)
        
        if not path.startswith("/"):
            path = f"/{path}"
        
        for account in self.active_accounts:
            try:
                client = await self._get_or_create_client(account)
                node = await client.get(path)
                if node:
                    return (account, node)
            except Exception:
                continue
        
        return None
    
    async def list_all(self, path: str) -> List[tuple]:
        """
        List contents of a path across ALL accounts.
        
        Returns list of (account, node) for each file found.
        
        Args:
            path: Path to list
            
        Returns:
            List of (account, node) tuples
        """
        if not self._accounts:
            await self.load_accounts(refresh_space=False)
        
        if not path.startswith("/"):
            path = f"/{path}"
        
        results = []
        
        for account in self.active_accounts:
            try:
                client = await self._get_or_create_client(account)
                node = await client.get(path)
                if node and node.is_folder:
                    for child in node.children:
                        results.append((account, child))
            except Exception:
                continue
        
        return results
    
    async def find_by_mega_id(self, mega_id: str) -> Optional[tuple]:
        """
        Find a file by mega_id (attribute 'm') across ALL accounts.
        
        Searches recursively through all nodes in all accounts.
        
        Args:
            mega_id: Source ID (mega_id stored as 'm' attribute)
            
        Returns:
            Tuple of (account, node) if found, None otherwise
        """
        if not self._accounts:
            await self.load_accounts(refresh_space=False)
        
        def search_nodes(node, account_name: str):
            """Recursively search for node with mega_id."""
            if not node:
                return None
            
            # Check if this node has the mega_id
            if node.attributes and node.attributes.mega_id == mega_id:
                return (account_name, node)
            
            # If it's a folder, search children
            if node.is_folder:
                for child in node.children:
                    result = search_nodes(child, account_name)
                    if result:
                        return result
            
            return None
        
        # Search in all active accounts
        for account in self.active_accounts:
            try:
                client = await self._get_or_create_client(account)
                
                # Ensure nodes are loaded
                if client._node_service is None:
                    await client._load_nodes()
                
                # Start from root
                root = await client.get_root()
                result = search_nodes(root, account.name)
                if result:
                    return result
            except Exception as e:
                logger.debug(f"Error searching in account {account.name} for mega_id {mega_id}: {e}")
                continue
        
        return None
    
    async def create_new_session(
        self,
        name: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None
    ) -> ManagedAccount:
        """
        Create a new session interactively or with provided credentials.
        
        Args:
            name: Session name (auto-generated from email MD5 if not provided)
            email: MEGA email (prompted if not provided)
            password: MEGA password (prompted if not provided)
            
        Returns:
            New ManagedAccount
        """
        # Get credentials interactively if not provided
        if not email:
            print("\n📧 New MEGA account login required")
            email = input("  Email: ").strip()
        
        # Generate session name from email MD5 if not provided
        if not name:
            email_hash = hashlib.md5(email.lower().encode()).hexdigest()
            name = email_hash
        
        session_path = self._sessions_dir / f"{name}.session"
        
        # Check if already exists
        if session_path.exists():
            logger.warning(f"Session {name} already exists, loading it")
            return await self.add_account(session_path, name)
        
        if not password:
            password = getpass.getpass("  Password: ")
        
        # Create client and login with proxy
        print(f"  Logging in as {email}...")
        
        config = MegaClient.create_config(proxy=PROXY_URL)
        client = MegaClient(str(session_path), config=config)
        try:
            await client.start(email=email, password=password)
            
            # Get account info
            info = await client.get_account_info()
            
            # Create managed account
            account = ManagedAccount(
                session_path=session_path,
                name=name,
                space_free=info.space_free,
                space_total=info.space_total,
                space_used=info.space_used,
                last_checked=datetime.now(),
                is_active=True,
                priority=len(self._accounts)
            )
            
            self._accounts[name] = account
            self._clients[name] = client
            
            print(f"  ✓ Logged in! Free space: {account.space_free_gb:.1f} GB")
            logger.info(f"Created new session: {name} ({email})")
            
            return account
            
        except Exception as e:
            # Cleanup failed session
            if session_path.exists():
                session_path.unlink()
            raise AccountConnectionError(name, e)
    
    async def get_client_for(self, file_size: int, prompt_new: bool = True) -> MegaClient:
        """
        Get a MegaClient with enough space for the file.
        
        If no account has enough space and auto_create is True,
        prompts to create a new session.
        
        Args:
            file_size: File size in bytes
            prompt_new: Whether to prompt for new account if all full
            
        Returns:
            MegaClient ready for upload
            
        Raises:
            NoAccountsError: No accounts configured
            NoSpaceError: No account has enough space
        """
        # Load accounts if not loaded
        if not self._accounts:
            await self.load_accounts()
        
        # If still no accounts, prompt to create one
        if not self._accounts:
            if self._auto_create and prompt_new:
                print("\n⚠️  No MEGA accounts found. Let's add one.")
                account = await self.create_new_session()
                self._current_account = account.name
                return await self._get_or_create_client(account)
            else:
                raise NoAccountsError("No accounts configured.")
        
        # Check if all accounts have less than 1GB free
        MIN_FREE_SPACE_GB = 1
        MIN_FREE_SPACE_BYTES = MIN_FREE_SPACE_GB * 1024 * 1024 * 1024
        
        all_accounts_low_space = all(
            a.space_free < MIN_FREE_SPACE_BYTES 
            for a in self.active_accounts
        ) if self.active_accounts else False
        
        # If all accounts have less than 1GB, create a new one automatically
        if all_accounts_low_space and self._auto_create and prompt_new:
            print(f"\n⚠️  All accounts have less than {MIN_FREE_SPACE_GB}GB free space.")
            print("   Creating a new MEGA account automatically...")
            try:
                account = await self.create_new_session()
                self._current_account = account.name
                # Refresh to get accurate space info
                await self._refresh_account(account)
                # Check if new account has space
                if account.has_space_for(file_size, self._buffer_mb):
                    return await self._get_or_create_client(account)
            except Exception as e:
                print(f"   Failed to create new account: {e}")
                # Continue to normal flow
        
        account = self.get_best_account(file_size)
        
        if not account:
            # Try refreshing and check again
            await self.refresh_all()
            account = self.get_best_account(file_size)
        
        if not account:
            # All accounts full - try to create new one
            if self._auto_create and prompt_new:
                print(f"\n⚠️  All accounts full! Need {file_size / (1024**3):.2f} GB")
                print("   Let's add a new MEGA account.")
                account = await self.create_new_session()
                
                if account.has_space_for(file_size, self._buffer_mb):
                    self._current_account = account.name
                    return await self._get_or_create_client(account)
            
            best_available = max((a.space_free for a in self.active_accounts), default=0)
            raise NoSpaceError(file_size, best_available)
        
        self._current_account = account.name
        return await self._get_or_create_client(account)
    
    async def get_client(self, name: str) -> MegaClient:
        """
        Get client by account name.
        
        Args:
            name: Account name (session filename without extension)
        """
        if name not in self._accounts:
            raise KeyError(f"Account not found: {name}")
        
        account = self._accounts[name]
        self._current_account = name
        return await self._get_or_create_client(account)
    
    def plan_upload(self, files: List[Path]) -> UploadPlan:
        """
        Plan upload of multiple files across accounts.
        
        Assigns files to accounts based on space availability.
        
        Args:
            files: List of file paths to upload
            
        Returns:
            UploadPlan with file assignments
        """
        plan = UploadPlan()
        
        # Sort accounts by priority, then free space
        available = sorted(
            self.active_accounts,
            key=lambda a: (a.priority, -a.space_free)
        )
        
        # Track remaining space per account
        remaining = {a.name: a.space_free - (self._buffer_mb * 1024 * 1024) for a in available}
        
        for file_path in files:
            file_size = file_path.stat().st_size
            plan.total_size += file_size
            
            # Find account with enough space
            assigned = False
            for account in available:
                if remaining[account.name] >= file_size:
                    plan.add(file_path, account)
                    remaining[account.name] -= file_size
                    assigned = True
                    break
            
            if not assigned:
                plan.can_complete = False
                plan.missing_space += file_size
        
        return plan
    
    async def upload_with_rotation(
        self,
        file_path: Path,
        dest: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        **upload_kwargs
    ) -> Any:
        """
        Upload file, automatically rotating accounts if needed.
        
        Args:
            file_path: Path to file to upload
            dest: Destination folder path
            progress_callback: Upload progress callback
            **upload_kwargs: Additional arguments for upload
            
        Returns:
            Upload result from MegaClient.upload()
        """
        file_path = Path(file_path)
        file_size = file_path.stat().st_size
        
        client = await self.get_client_for(file_size)
        
        result = await client.upload(
            file_path,
            dest_folder=dest,
            progress_callback=progress_callback,
            **upload_kwargs
        )
        
        # Update space tracking
        if self._current_account:
            account = self._accounts[self._current_account]
            account.space_used += file_size
            account.space_free -= file_size
        
        return result
    
    async def close(self) -> None:
        """Close all client connections."""
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:
                pass
        
        self._clients.clear()
    
    async def __aenter__(self) -> 'AccountManager':
        """Async context manager entry."""
        if self._auto_load:
            await self.load_accounts()
        return self
    
    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        await self.close()
    
    async def import_from_api(
        self,
        api_url: str = "http://127.0.0.1:8000",
        master_password: Optional[str] = None
    ) -> List[ManagedAccount]:
        """
        Import all accounts from API, decrypt passwords, login and save sessions.
        
        This method:
        1. Gets all accounts from API (with encrypted passwords)
        2. Decrypts passwords using master password
        3. Logs in to each account
        4. Saves session files (md5(email).session)
        
        Args:
            api_url: API server URL
            master_password: Master password for decryption (prompted if not provided)
            
        Returns:
            List of imported ManagedAccount instances
        """
        # Import crypto module (local)
        from .crypto import PasswordCrypto
        
        # Get master password if not provided
        if not master_password:
            print("\n🔐 Master password required to decrypt accounts")
            master_password = getpass.getpass("Master password: ")
            if not master_password:
                raise ValueError("Master password is required")
        
        # Initialize crypto
        crypto = PasswordCrypto(master_password)
        
        # Get all accounts from API
        print(f"\n📡 Fetching accounts from API: {api_url}")
        async with AccountAPIClient(api_url=api_url) as api:
            try:
                accounts_data = await api.get_all_accounts()
            except Exception as e:
                logger.error(f"Failed to fetch accounts from API: {e}")
                raise AccountConnectionError("API", e)
        
        if not accounts_data:
            print("  No accounts found in API")
            return []
        
        print(f"  Found {len(accounts_data)} account(s)")
        
        imported_accounts = []
        failed_accounts = []
        
        # Process each account
        for acc_data in accounts_data:
            email = acc_data['email']
            encrypted_password = acc_data['password']
            
            try:
                # Decrypt password
                password = crypto.decrypt_password(encrypted_password)
                
                # Create session (md5(email).session)
                email_hash = hashlib.md5(email.lower().encode()).hexdigest()
                session_path = self._sessions_dir / f"{email_hash}.session"
                
                # Check if session already exists
                if session_path.exists():
                    logger.info(f"Session already exists for {email}, skipping login")
                    # Load existing account
                    account = await self.add_account(session_path, email_hash)
                    imported_accounts.append(account)
                    continue
                
                # Login and create session with proxy
                print(f"  Logging in {email}...")
                config = MegaClient.create_config(proxy=PROXY_URL)
                client = MegaClient(str(session_path), config=config)
                try:
                    await client.start(email=email, password=password)
                    
                    # Get account info
                    info = await client.get_account_info()
                    
                    # Create managed account
                    account = ManagedAccount(
                        session_path=session_path,
                        name=email_hash,
                        space_free=info.space_free,
                        space_total=info.space_total,
                        space_used=info.space_used,
                        last_checked=datetime.now(),
                        is_active=True,
                        priority=len(self._accounts)
                    )
                    
                    self._accounts[account.name] = account
                    self._clients[account.name] = client
                    
                    imported_accounts.append(account)
                    print(f"    ✓ {email}: {account.space_free_gb:.1f} GB free")
                    
                except Exception as e:
                    logger.error(f"Failed to login {email}: {e}")
                    failed_accounts.append((email, str(e)))
                    # Cleanup failed session
                    if session_path.exists():
                        session_path.unlink()
                    
            except Exception as e:
                logger.error(f"Failed to decrypt password for {email}: {e}")
                failed_accounts.append((email, f"Decryption error: {e}"))
        
        # Summary
        print(f"\n✓ Imported {len(imported_accounts)} account(s)")
        if failed_accounts:
            print(f"✗ Failed to import {len(failed_accounts)} account(s):")
            for email, error in failed_accounts:
                print(f"  - {email}: {error}")
        
        return imported_accounts
    
    async def merge(
        self,
        source_account_name: Optional[str] = None,
        target_account_name: Optional[str] = None,
        imports_folder_name: str = "imports"
    ) -> Dict[str, Any]:
        """
        Automatically merge all content from account with less space (more full) to account with more space (less full).
        
        Process:
        1. Identifies source account (less free space = more content) and target account (more free space = less content)
        2. In source account:
           - Creates "imports" folder (or uses existing)
           - Merges all children from root to imports folder
           - Shares the imports folder to get a link
        3. In target account:
           - Imports the shared link into root
        
        Args:
            source_account_name: Optional source account name. If not provided, uses account with least free space (most full).
            target_account_name: Optional target account name. If not provided, uses account with most free space (least full).
            imports_folder_name: Name of the imports folder to create (default: "imports")
            
        Returns:
            Dict with:
                - source_account: Source account name
                - target_account: Target account name
                - imports_folder: Name of imports folder
                - shared_link: The shared link URL
                - merged_count: Number of items merged
                - success: Whether the operation succeeded
        """
        logger.info("=== Starting merge ===")
        
        # If both account names are provided, only load those two accounts
        # Otherwise, load all accounts for auto-selection
        if source_account_name and target_account_name:
            logger.info(f"Loading only specified accounts: {source_account_name} -> {target_account_name}")
            
            # Build session paths for the two accounts
            source_session_path = self._sessions_dir / f"{source_account_name}.session"
            target_session_path = self._sessions_dir / f"{target_account_name}.session"
            
            # Check if session files exist
            if not source_session_path.exists():
                raise FileNotFoundError(f"Source session file not found: {source_session_path}")
            if not target_session_path.exists():
                raise FileNotFoundError(f"Target session file not found: {target_session_path}")
            
            # Only load/add these two accounts
            if source_account_name not in self._accounts:
                await self.add_account(source_session_path, source_account_name)
            if target_account_name not in self._accounts:
                await self.add_account(target_session_path, target_account_name)
            
            source_account = self._accounts[source_account_name]
            target_account = self._accounts[target_account_name]
            
            logger.info(f"Loaded 2 accounts: {source_account_name} and {target_account_name}")
        else:
            # Auto-selection mode: load all accounts
            logger.info("Loading/refreshing all accounts for auto-selection...")
            if not self._accounts:
                await self.load_accounts()
            else:
                await self.refresh_all()
            logger.info(f"Accounts loaded: {len(self._accounts)} total, {len(self.active_accounts)} active")
            
            if len(self.active_accounts) < 2:
                raise ValueError("Need at least 2 active accounts to perform merge")
            
            # Determine source and target accounts
            if source_account_name:
                if source_account_name not in self._accounts:
                    raise KeyError(f"Source account not found: {source_account_name}")
                source_account = self._accounts[source_account_name]
            else:
                # Use account with least free space (most full, has more content to move)
                source_account = min(self.active_accounts, key=lambda a: a.space_free)
            
            if target_account_name:
                if target_account_name not in self._accounts:
                    raise KeyError(f"Target account not found: {target_account_name}")
                target_account = self._accounts[target_account_name]
            else:
                # Use account with most free space (least full, has room for content)
                candidates = [a for a in self.active_accounts if a.name != source_account.name]
                if not candidates:
                    raise ValueError("Cannot use same account as source and target")
                target_account = max(candidates, key=lambda a: a.space_free)
        
        # Ensure source and target are different
        if source_account.name == target_account.name:
            raise ValueError("Source and target accounts must be different")
        
        logger.info(
            f"Merging from {source_account.name} ({source_account.space_free_gb:.1f} GB free) "
            f"to {target_account.name} ({target_account.space_free_gb:.1f} GB free)"
        )
        
        # Get clients
        logger.info(f"Getting client for source account: {source_account.name}")
        source_client = await self._get_or_create_client(source_account)
        logger.info(f"Source client obtained")
        
        logger.info(f"Getting client for target account: {target_account.name}")
        target_client = await self._get_or_create_client(target_account)
        logger.info(f"Target client obtained")
        
        try:
            # Step 1: Get root in source account and ensure nodes are loaded
            logger.info("Getting root and loading nodes in source account...")
            
            # Ensure nodes are loaded first
            if source_client._node_service is None:
                logger.info("Loading nodes in source account...")
                await source_client._load_nodes()
            
            # Get root (this should use the loaded nodes)
            source_root = await source_client.get_root(refresh=True)
            logger.info(f"Source root obtained, loading children...")
            
            # Ensure children are loaded
            if not hasattr(source_root, 'children') or len(source_root.children) == 0:
                logger.info("Root has no children or children not loaded, refreshing...")
                # Try to load children explicitly
                await source_client._load_nodes()
                source_root = await source_client.get_root(refresh=True)
            
            logger.info(f"Source root has {len(source_root.children)} children")
            
            # Step 2: Create or get imports folder
            imports_folder = None
            # Check if imports folder already exists
            logger.info("Checking for existing imports folder...")
            for child in source_root.children:
                if child.is_folder and child.name == imports_folder_name:
                    imports_folder = child
                    logger.info(f"Found existing imports folder: {imports_folder_name}")
                    break
            
            if not imports_folder:
                logger.info(f"Creating imports folder: {imports_folder_name}")
                imports_folder = await source_client.create_folder(imports_folder_name, parent=source_root)
            
            # Step 3: Move all children from root to imports folder
            # Get all children (make a copy of the list since we'll be modifying it)
            logger.info("Getting list of children to move...")
            root_children = list(source_root.children)
            logger.info(f"Found {len(root_children)} total children in root")
            
            # Filter out the imports folder itself
            children_to_move = [child for child in root_children if child.handle != imports_folder.handle]
            logger.info(f"Will move {len(children_to_move)} children (excluding imports folder)")
            
            if len(children_to_move) == 0:
                logger.info("No children to move, skipping move step")
                moved_count = 0
            else:
                moved_count = 0
                for i, child in enumerate(children_to_move, 1):
                    try:
                        logger.info(f"Moving {i}/{len(children_to_move)}: {child.name} to {imports_folder_name}")
                        await source_client.move(child, imports_folder)
                        moved_count += 1
                        logger.debug(f"Successfully moved {child.name}")
                    except Exception as e:
                        logger.error(f"Failed to move {child.name}: {e}", exc_info=True)
                        # Continue with other children
                
                logger.info(f"Moved {moved_count}/{len(children_to_move)} items to {imports_folder_name}")
            
            # Step 4: Share the imports folder
            logger.info("Sharing imports folder...")
            shared_link = await imports_folder.share_folder()
            logger.info(f"Shared link: {shared_link}")
            
            # Step 5: Import the link in target account
            logger.info(f"Importing link into {target_account.name}...")
            target_root = await target_client.get_root()
            
            # Ensure nodes are loaded in target account
            if target_client._node_service is None:
                logger.info("Loading nodes in target account...")
                await target_client._load_nodes()
            
            # Import the link
            logger.info(f"Importing shared link: {shared_link}")
            imported = await target_root.import_link(shared_link, clear_attributes=True)
            logger.info(f"Successfully imported {len(imported)} items into target account")
            
            # Refresh space info for both accounts
            await self._refresh_account(source_account)
            await self._refresh_account(target_account)
            
            return {
                "source_account": source_account.name,
                "target_account": target_account.name,
                "imports_folder": imports_folder_name,
                "shared_link": shared_link,
                "moved_count": moved_count,
                "imported_count": len(imported),
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Auto-move failed: {e}", exc_info=True)
            return {
                "source_account": source_account.name,
                "target_account": target_account.name,
                "imports_folder": imports_folder_name,
                "shared_link": None,
                "moved_count": moved_count if 'moved_count' in locals() else 0,
                "imported_count": 0,
                "success": False,
                "error": str(e)
            }
    
    def __str__(self) -> str:
        lines = [f"AccountManager ({len(self._accounts)} accounts):"]
        for account in sorted(self._accounts.values(), key=lambda a: a.priority):
            lines.append(f"  {account}")
        lines.append(f"Total free: {self.total_space_free_gb:.1f} GB")
        return "\n".join(lines)
