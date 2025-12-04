"""
Models for mega-account manager.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from datetime import datetime


@dataclass
class ManagedAccount:
    """
    A managed MEGA account with session and status info.
    
    Attributes:
        session_path: Path to the session file
        name: Display name for the account
        space_free: Free space in bytes (updated on check)
        space_total: Total space in bytes
        space_used: Used space in bytes
        last_checked: When space was last checked
        is_active: Whether this account is currently usable
        priority: Account priority (lower = preferred)
    """
    session_path: Path
    name: str = ""
    space_free: int = 0
    space_total: int = 0
    space_used: int = 0
    last_checked: Optional[datetime] = None
    is_active: bool = True
    priority: int = 0
    
    def __post_init__(self):
        if not self.name:
            self.name = self.session_path.stem
    
    @property
    def space_free_gb(self) -> float:
        """Free space in GB."""
        return self.space_free / (1024 ** 3)
    
    @property
    def space_used_gb(self) -> float:
        """Used space in GB."""
        return self.space_used / (1024 ** 3)
    
    @property
    def space_total_gb(self) -> float:
        """Total space in GB."""
        return self.space_total / (1024 ** 3)
    
    @property
    def usage_percent(self) -> float:
        """Storage usage percentage."""
        if self.space_total == 0:
            return 0.0
        return (self.space_used / self.space_total) * 100
    
    def has_space_for(self, file_size: int, buffer_mb: int = 100) -> bool:
        """
        Check if account has enough space for a file.
        
        Args:
            file_size: File size in bytes
            buffer_mb: Extra buffer space to keep free (default 100MB)
        """
        buffer_bytes = buffer_mb * 1024 * 1024
        return self.space_free >= (file_size + buffer_bytes)
    
    def __str__(self) -> str:
        status = "✓" if self.is_active else "✗"
        return (
            f"[{status}] {self.name}: "
            f"{self.space_free_gb:.1f} GB free / {self.space_total_gb:.1f} GB total "
            f"({self.usage_percent:.1f}% used)"
        )


@dataclass
class AccountSelection:
    """Result of account selection."""
    account: ManagedAccount
    client: any  # MegaClient
    reason: str = ""


@dataclass
class UploadPlan:
    """
    Plan for uploading files across multiple accounts.
    
    When a single account doesn't have enough space,
    this provides a plan to split files across accounts.
    """
    assignments: list = field(default_factory=list)  # [(file_path, account)]
    total_size: int = 0
    can_complete: bool = True
    missing_space: int = 0
    
    def add(self, file_path: Path, account: ManagedAccount):
        """Add file to upload plan."""
        self.assignments.append((file_path, account))
    
    @property
    def files_count(self) -> int:
        return len(self.assignments)
    
    @property
    def accounts_needed(self) -> int:
        return len(set(a for _, a in self.assignments))
