# mega-account

Multi-account MEGA storage manager for Python.

## Features

- **Auto-discovery**: Finds all session files in config directory
- **Space tracking**: Monitors free space across accounts
- **Smart selection**: Picks best account based on available space
- **Auto-rotation**: Switches accounts when one is full
- **Upload planning**: Plans multi-file uploads across accounts

## Installation

```bash
pip install -e ./mega-account
```

## Quick Start

```python
from mega_account import AccountManager

async with AccountManager() as manager:
    # Upload with automatic account selection
    await manager.upload_with_rotation(
        "video.mp4",
        dest="/Videos"
    )
```

## Session Files

By default, looks for `*.session` files in `~/.config/mega/sessions/`:

```
~/.config/mega/sessions/
├── md5(email1).session  # Account 1 (email hash)
├── md5(email2).session  # Account 2 (email hash)
└── ...
```

Session files are named using `md5(email).session` format.

## Usage

### Import Accounts from API

Import all accounts from `mega-account-api`:

```bash
mega-account import --api-url http://127.0.0.1:8000
```

This will:
1. Fetch all accounts from the API (with encrypted passwords)
2. Prompt for master password to decrypt
3. Login to each account
4. Save session files as `md5(email).session`

**Options:**
- `--api-url` / `-u`: API server URL (default: http://127.0.0.1:8000)
- `--master-password` / `-p`: Master password (prompted if not provided)

### Basic Upload with Auto-Selection

```python
from mega_account import AccountManager

async def upload_file(file_path):
    async with AccountManager() as manager:
        # Get client with enough space
        file_size = Path(file_path).stat().st_size
        client = await manager.get_client_for(file_size)
        
        # Upload using the selected client
        result = await client.upload(file_path)
        return result
```

### Upload with Auto-Rotation

```python
async with AccountManager() as manager:
    # Automatically selects account and tracks space
    result = await manager.upload_with_rotation(
        file_path,
        dest="/Uploads",
        mega_id="abc123"  # Links to MongoDB
    )
```

### Plan Multi-File Upload

```python
async with AccountManager() as manager:
    files = [Path("file1.mp4"), Path("file2.mp4"), Path("file3.mp4")]
    
    plan = manager.plan_upload(files)
    
    if plan.can_complete:
        print(f"Upload plan: {plan.files_count} files across {plan.accounts_needed} accounts")
        
        for file_path, account in plan.assignments:
            client = await manager.get_client(account.name)
            await client.upload(file_path)
    else:
        print(f"Not enough space! Missing: {plan.missing_space / 1024**3:.2f} GB")
```

### Check Account Status

```python
async with AccountManager() as manager:
    print(manager)
    # Output:
    # AccountManager (3 accounts):
    #   [✓] session: 45.2 GB free / 50.0 GB total (9.6% used)
    #   [✓] session2: 120.5 GB free / 200.0 GB total (39.8% used)
    #   [✗] backup: 0.0 GB free / 15.0 GB total (100.0% used)
    # Total free: 165.7 GB
```

### Import from API (Programmatic)

```python
from mega_account import AccountManager

async with AccountManager() as manager:
    # Import all accounts from API
    accounts = await manager.import_from_api(
        api_url="http://127.0.0.1:8000",
        master_password="your_master_password"  # Optional, will prompt if not provided
    )
    print(f"Imported {len(accounts)} accounts")
```

### Custom Config Directory

```python
from pathlib import Path

manager = AccountManager(
    sessions_dir=Path("/custom/path"),
    session_pattern="mega_*.session",  # Custom pattern
    buffer_mb=500  # Keep 500MB buffer free
)
```

## API Reference

### AccountManager

| Method | Description |
|--------|-------------|
| `load_accounts()` | Discover and load all session files |
| `add_account(path)` | Add a specific session file |
| `refresh_all()` | Refresh space info for all accounts |
| `get_best_account(size)` | Get account with most space for file |
| `get_client_for(size)` | Get MegaClient with enough space |
| `get_client(name)` | Get MegaClient by account name |
| `plan_upload(files)` | Plan multi-file upload |
| `upload_with_rotation()` | Upload with auto account rotation |

### ManagedAccount

| Property | Description |
|----------|-------------|
| `space_free` | Free space in bytes |
| `space_free_gb` | Free space in GB |
| `space_total` | Total space in bytes |
| `usage_percent` | Usage percentage |
| `has_space_for(size)` | Check if enough space |
| `is_active` | Account is usable |

### Exceptions

| Exception | Description |
|-----------|-------------|
| `NoAccountsError` | No accounts configured |
| `NoSpaceError` | No account has enough space |
| `AllAccountsFullError` | All accounts are full |
| `SessionNotFoundError` | Session file not found |

## Integration with Uploader

```python
from mega_account import AccountManager
from uploader import UploadOrchestrator

async def upload_folder(folder_path, api_url):
    async with AccountManager() as manager:
        # Get client for estimated size
        total_size = sum(f.stat().st_size for f in folder_path.rglob("*") if f.is_file())
        client = await manager.get_client_for(total_size)
        
        async with UploadOrchestrator(api_url, client) as uploader:
            result = await uploader.upload_folder(folder_path)
            return result
```
