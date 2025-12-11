"""Encryption utilities for password storage."""
import base64
import hashlib
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import os


class PasswordCrypto:
    """Handle password encryption/decryption using master key."""
    
    def __init__(self, master_password: str):
        """
        Initialize with master password.
        
        Args:
            master_password: Master password for deriving encryption key
        """
        self.master_password = master_password
        self._derived_key = None
    
    def _get_derived_key(self) -> bytes:
        """Derive encryption key from master password."""
        if self._derived_key is None:
            # Use PBKDF2 to derive key from master password
            salt = b'mega_account_salt_v1'  # Fixed salt for consistency
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,  # 256 bits for AES-256
                salt=salt,
                iterations=100000,
                backend=default_backend()
            )
            self._derived_key = kdf.derive(self.master_password.encode())
        return self._derived_key
    
    def encrypt_password(self, password: str) -> str:
        """
        Encrypt password: MASTERKEY -> DERIVED_KEY -> AES encrypt -> Base64.
        
        Args:
            password: Plain text password
            
        Returns:
            Base64 encoded encrypted password (IV + ciphertext)
        """
        key = self._get_derived_key()
        
        # Generate random IV for each encryption
        iv = os.urandom(16)
        
        # Create cipher
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        
        # Pad password to block size (16 bytes)
        password_bytes = password.encode('utf-8')
        pad_length = 16 - (len(password_bytes) % 16)
        padded_password = password_bytes + bytes([pad_length] * pad_length)
        
        # Encrypt
        ciphertext = encryptor.update(padded_password) + encryptor.finalize()
        
        # Combine IV + ciphertext and encode to Base64
        encrypted_data = iv + ciphertext
        return base64.b64encode(encrypted_data).decode('utf-8')
    
    def decrypt_password(self, encrypted_password: str) -> str:
        """
        Decrypt password: Base64 -> extract IV -> AES decrypt -> plaintext.
        
        Args:
            encrypted_password: Base64 encoded encrypted password
            
        Returns:
            Plain text password
        """
        key = self._get_derived_key()
        
        # Decode from Base64
        encrypted_data = base64.b64decode(encrypted_password.encode('utf-8'))
        
        # Extract IV (first 16 bytes) and ciphertext
        iv = encrypted_data[:16]
        ciphertext = encrypted_data[16:]
        
        # Create cipher
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()
        
        # Decrypt
        padded_password = decryptor.update(ciphertext) + decryptor.finalize()
        
        # Remove padding
        pad_length = padded_password[-1]
        password = padded_password[:-pad_length]
        
        return password.decode('utf-8')

