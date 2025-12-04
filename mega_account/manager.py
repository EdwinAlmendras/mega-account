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
from pathlib import Path
from typing import Optional, List, Dict, Callable, Any
from datetime import datetime, timedelta
import logging
import getpass

from megapy import MegaClient, AccountInfo

from .models import ManagedAccount, AccountSelection, UploadPlan
from .exceptions import (
    NoAccountsError,
    NoSpaceError,
    AllAccountsFullError,
    AccountConnectionError,
    SessionNotFoundError
)

logger = logging.getLogger(__name__)


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
        auto_create: bool = True
    ):
        """
        Initialize account manager.
        
        Args:
            sessions_dir: Directory containing session files (default: ~/.config/mega/sessions/)
            session_pattern: Glob pattern for session files
            buffer_mb: Buffer space to keep free (MB)
            auto_create: Auto-create new session if all accounts are full
        """
        self._sessions_dir = Path(sessions_dir) if sessions_dir else self.DEFAULT_SESSIONS_DIR
        self._session_pattern = session_pattern
        self._buffer_mb = buffer_mb
        self._auto_create = auto_create
        
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
        
        # Also check for legacy single session
        legacy_session = Path.home() / ".config" / "mega" / "session.session"
        if legacy_session.exists() and legacy_session not in session_files:
            session_files.append(legacy_session)
            logger.info(f"Found legacy session: {legacy_session}")
        
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
        tasks = [self._refresh_account(a) for a in self._accounts.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
    
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
            client = MegaClient(str(account.session_path))
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
    
    async def create_new_session(
        self,
        name: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None
    ) -> ManagedAccount:
        """
        Create a new session interactively or with provided credentials.
        
        Args:
            name: Session name (auto-generated if not provided)
            email: MEGA email (prompted if not provided)
            password: MEGA password (prompted if not provided)
            
        Returns:
            New ManagedAccount
        """
        # Generate session name if not provided
        if not name:
            existing = len(list(self._sessions_dir.glob("*.session")))
            name = f"account{existing + 1}"
        
        session_path = self._sessions_dir / f"{name}.session"
        
        # Check if already exists
        if session_path.exists():
            logger.warning(f"Session {name} already exists, loading it")
            return await self.add_account(session_path, name)
        
        # Get credentials interactively if not provided
        if not email:
            print("\n📧 New MEGA account login required")
            email = input("  Email: ").strip()
        
        if not password:
            password = getpass.getpass("  Password: ")
        
        # Create client and login
        print(f"  Logging in as {email}...")
        
        client = MegaClient(str(session_path))
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
        await self.load_accounts()
        return self
    
    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        await self.close()
    
    def __str__(self) -> str:
        lines = [f"AccountManager ({len(self._accounts)} accounts):"]
        for account in sorted(self._accounts.values(), key=lambda a: a.priority):
            lines.append(f"  {account}")
        lines.append(f"Total free: {self.total_space_free_gb:.1f} GB")
        return "\n".join(lines)
