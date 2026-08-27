from __future__ import annotations

import base64
import ctypes
import getpass
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from cryptography.fernet import Fernet


KEYCHAIN_SERVICE = "com.vkoutreach.manager.master-key"


class SecretProtectionError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


class DPAPIProtector:
    """Protect secrets with DPAPI on Windows and Keychain on macOS."""

    def __init__(self, fallback_key_path: Path | None = None):
        self.fallback_key_path = fallback_key_path

    def _fallback_fernet(self) -> Fernet:
        if self.fallback_key_path is None:
            raise SecretProtectionError("На этой системе не настроен ключ разработки")
        path = self.fallback_key_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(Fernet.generate_key())
            try:
                path.chmod(0o600)
            except OSError:
                pass
        return Fernet(path.read_bytes())

    def _macos_fernet(self) -> Fernet:
        account = getpass.getuser()
        find_command = [
            "/usr/bin/security",
            "find-generic-password",
            "-a",
            account,
            "-s",
            KEYCHAIN_SERVICE,
            "-w",
        ]
        try:
            found = subprocess.run(
                find_command,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SecretProtectionError("Не удалось обратиться к macOS Keychain") from exc

        if found.returncode == 0:
            key = found.stdout.strip().encode("ascii", errors="strict")
        else:
            generated = Fernet.generate_key()
            key_text = generated.decode("ascii")
            add_command = [
                "/usr/bin/security",
                "add-generic-password",
                "-U",
                "-a",
                account,
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
                key_text,
            ]
            try:
                added = subprocess.run(
                    add_command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise SecretProtectionError("Не удалось сохранить ключ в macOS Keychain") from exc
            if added.returncode != 0:
                raise SecretProtectionError(
                    f"Не удалось сохранить ключ в macOS Keychain (код {added.returncode})"
                )
            key = generated
        try:
            return Fernet(key)
        except (TypeError, ValueError) as exc:
            raise SecretProtectionError("macOS Keychain вернул повреждённый ключ приложения") from exc

    def protect(self, plaintext: str) -> bytes:
        raw = plaintext.encode("utf-8")
        if sys.platform == "darwin":
            return b"keychain:" + self._macos_fernet().encrypt(raw)
        if os.name != "nt":
            return b"fernet:" + self._fallback_fernet().encrypt(raw)
        input_blob, input_buffer = _blob(raw)
        output_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "VK Outreach Manager",
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        ):
            raise SecretProtectionError(f"CryptProtectData: {ctypes.GetLastError()}")
        try:
            encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
            return b"dpapi:" + base64.urlsafe_b64encode(encrypted)
        finally:
            kernel32.LocalFree(output_blob.pbData)
            del input_buffer

    def unprotect(self, encrypted: bytes) -> str:
        if encrypted.startswith(b"keychain:"):
            if sys.platform != "darwin":
                raise SecretProtectionError("Секрет macOS Keychain нельзя открыть на этой системе")
            return self._macos_fernet().decrypt(encrypted[9:]).decode("utf-8")
        if encrypted.startswith(b"fernet:"):
            return self._fallback_fernet().decrypt(encrypted[7:]).decode("utf-8")
        if os.name != "nt" or not encrypted.startswith(b"dpapi:"):
            raise SecretProtectionError("Неизвестный формат защищённого секрета")
        raw = base64.urlsafe_b64decode(encrypted[6:])
        input_blob, input_buffer = _blob(raw)
        output_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptUnprotectData(
            ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)
        ):
            raise SecretProtectionError(f"CryptUnprotectData: {ctypes.GetLastError()}")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
        finally:
            kernel32.LocalFree(output_blob.pbData)
            del input_buffer
