from __future__ import annotations

from unittest.mock import patch

import pytest

from bot.utils.encryption import decrypt_value, encrypt_value


def test_encrypt_decrypt_roundtrip_with_key() -> None:
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    with patch("bot.utils.encryption.get_settings") as mock_settings:
        mock_settings.return_value.session_encryption_key = key
        plaintext = "telegram_session_string_12345"
        encrypted = encrypt_value(plaintext)
        assert encrypted is not None
        assert encrypted != plaintext
        decrypted = decrypt_value(encrypted)
        assert decrypted == plaintext


def test_encrypt_no_key_returns_plaintext() -> None:
    with patch("bot.utils.encryption.get_settings") as mock_settings:
        mock_settings.return_value.session_encryption_key = None
        plaintext = "session_string"
        assert encrypt_value(plaintext) == plaintext


def test_decrypt_no_key_returns_plaintext() -> None:
    with patch("bot.utils.encryption.get_settings") as mock_settings:
        mock_settings.return_value.session_encryption_key = None
        assert decrypt_value("encrypted_stuff") == "encrypted_stuff"


def test_encrypt_none_returns_none() -> None:
    assert encrypt_value(None) is None


def test_decrypt_none_returns_none() -> None:
    assert decrypt_value(None) is None
