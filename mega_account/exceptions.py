"""
Exceptions for mega-account manager.
"""


class MegaAccountError(Exception):
    """Base exception for mega-account errors."""
    pass


class NoAccountsError(MegaAccountError):
    """No accounts configured."""
    pass


class NoSpaceError(MegaAccountError):
    """No account has enough space for the file."""
    
    def __init__(self, file_size: int, available_space: int):
        self.file_size = file_size
        self.available_space = available_space
        super().__init__(
            f"No account has enough space. "
            f"Need {file_size / (1024**3):.2f} GB, "
            f"best available: {available_space / (1024**3):.2f} GB"
        )


class AllAccountsFullError(MegaAccountError):
    """All accounts are full."""
    pass


class AccountConnectionError(MegaAccountError):
    """Failed to connect to account."""
    
    def __init__(self, account_name: str, original_error: Exception):
        self.account_name = account_name
        self.original_error = original_error
        super().__init__(f"Failed to connect to {account_name}: {original_error}")


class SessionNotFoundError(MegaAccountError):
    """Session file not found."""
    
    def __init__(self, session_path: str):
        self.session_path = session_path
        super().__init__(f"Session not found: {session_path}")
