"""Atomic application state and Windows user-scoped API key encryption."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
import threading


DEFAULT_SETTINGS = {
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "image_model": "gpt-image-2",
    "text_model": "gpt-4.1-mini",
    "quality": "high",
    "size": "1024x1024",
    "concurrency": 2,
    "reference_path": "",
    "fabric_reference_path": "",
}


def default_data_dir() -> Path:
    configured = os.environ.get("FABRIC_STUDIO_DATA")
    if configured:
        return Path(configured).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "FabricLabelStudio" if local else Path.home() / ".fabric-label-studio"


class StorageError(RuntimeError):
    """An actionable storage failure; secrets are never included in its message."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise StorageError("Saving API keys requires Windows DPAPI. This platform cannot securely persist an API key.")
    buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        operation = crypt32.CryptUnprotectData
        operation.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    else:
        operation = crypt32.CryptProtectData
        operation.argtypes = [ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    operation.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN; omit LOCAL_MACHINE so only this Windows user can read it.
    success = operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    if not success:
        code = ctypes.get_last_error()
        action = "decrypt" if decrypt else "encrypt"
        raise StorageError(f"Windows could not {action} the API key (error {code}). Re-enter the key under the same Windows user account.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def _protect_key(key: str) -> str:
    return "dpapi:v1:" + base64.b64encode(_dpapi(key.encode("utf-8"))).decode("ascii")


def _unprotect_key(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("dpapi:v1:"):
        raise StorageError("The saved API key format is invalid. Re-enter the key in Settings.")
    try:
        payload = base64.b64decode(value[len("dpapi:v1:"):], validate=True)
        return _dpapi(payload, decrypt=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise StorageError("The saved API key is damaged. Re-enter the key in Settings.") from error


class Store:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read(self, filename: str, fallback):
        path = self.data_dir / filename
        if not path.exists():
            return fallback
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise StorageError(f"Cannot read {filename}. The file may be damaged; keep a backup before resetting it.") from error

    def _write(self, filename: str, value) -> None:
        temporary = None
        try:
            content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.data_dir, prefix=f".{filename}.", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.data_dir / filename)
        except (OSError, ValueError, TypeError) as error:
            raise StorageError(f"Cannot save {filename}. Check free disk space and folder permissions.") from error
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)

    def load_settings(self) -> dict:
        with self._lock:
            stored = self._read("settings.json", {})
            if not isinstance(stored, dict):
                raise StorageError("Settings must contain a JSON object.")
            # Refuse accidental legacy plaintext secrets instead of silently continuing.
            if stored.get("api_key"):
                raise StorageError("An unencrypted API key was found in settings.json. Remove it and save the key again through Settings.")
            settings = dict(DEFAULT_SETTINGS)
            settings.update({key: value for key, value in stored.items() if key not in {"api_key", "_protected_api_key"}})
            protected = stored.get("_protected_api_key")
            settings["api_key"] = _unprotect_key(protected) if protected else ""
            return settings

    def save_settings(self, settings: dict) -> None:
        if not isinstance(settings, dict):
            raise StorageError("Settings must be a dictionary.")
        with self._lock:
            stored = dict(settings)
            key = stored.pop("api_key", "")
            stored.pop("_protected_api_key", None)
            if not isinstance(key, str):
                raise StorageError("The API key must be text.")
            if key.strip():
                stored["_protected_api_key"] = _protect_key(key.strip())
            self._write("settings.json", stored)

    def load_jobs(self) -> list:
        with self._lock:
            jobs = self._read("jobs.json", [])
            if not isinstance(jobs, list):
                raise StorageError("Saved jobs must contain a JSON list.")
            return jobs

    def save_jobs(self, jobs: list) -> None:
        if not isinstance(jobs, list):
            raise StorageError("Jobs must be a list.")
        with self._lock:
            self._write("jobs.json", jobs)
