"""
MEGA Account Manager - Multi-account storage management.

Manages multiple MEGA accounts for optimal storage usage:
- Auto-discovery of session files
- Account space tracking
- Automatic account selection based on free space
- Account rotation when full
- Upload planning across multiple accounts

Usage:
    >>> from mega_account import AccountManager
    >>> 
    >>> async with AccountManager() as manager:
    ...     # Get best account for file
    ...     client = await manager.get_client_for(file_size)
    ...     await client.upload(file_path)
    ...     
    ...     # Or upload with auto-rotation
    ...     await manager.upload_with_rotation(file_path, dest="/Uploads")

Session Discovery:
    By default, looks for *.session files in ~/.config/mega/
    
    You can have multiple sessions:
    - ~/.config/mega/session.session (primary)
    - ~/.config/mega/session2.session
    - ~/.config/mega/backup.session
    
    The manager will automatically use the account with most free space.
"""
from .manager import AccountManager
from .models import ManagedAccount, AccountSelection, UploadPlan
from .api_client import AccountAPIClient
from .exceptions import (
    MegaAccountError,
    NoAccountsError,
    NoSpaceError,
    AllAccountsFullError,
    AccountConnectionError,
    SessionNotFoundError
)

__version__ = "0.1.0"

__all__ = [
    # Main
    "AccountManager",
    "AccountAPIClient",
    # Models
    "ManagedAccount",
    "AccountSelection", 
    "UploadPlan",
    # Exceptions
    "MegaAccountError",
    "NoAccountsError",
    "NoSpaceError",
    "AllAccountsFullError",
    "AccountConnectionError",
    "SessionNotFoundError",
]
