from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path

MAGIC = b"CCAT1\x00"  # marks a file as encrypted, whatever its extension
NONCE_LEN = 12
SALT_LEN = 16
KEY_LEN = 32  # AES-256
SCRYPT_N = 1 << 17
SCRYPT_R = 8
SCRYPT_P = 1

_CHECK = b"cutecat-passphrase-check"


class CryptoError(Exception):
 ...

# The unlocked key for this process. Never written anywhere.
_key: bytes | None = None


def marker_file() -> Path:
    from cutecat import config as config_mod

    return config_mod.CUTECAT_DIR / "encrypted.json"


def is_encrypted() -> bool:
    return marker_file().exists()


def is_unlocked() -> bool:
    return _key is not None


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover
        raise CryptoError(
            "encryption needs the 'cryptography' package: pip install cryptography"
        ) from exc
    return AESGCM(key)


def derive_key(passphrase: str, salt: bytes) -> bytes:
    from hashlib import scrypt

    return scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_LEN,
        maxmem=128 * SCRYPT_R * SCRYPT_N * 2,
    )


def encrypt(data: bytes, key: bytes | None = None) -> bytes:
    key = key or _key
    if key is None:
        raise CryptoError("locked — no passphrase has been supplied")
    nonce = secrets.token_bytes(NONCE_LEN)
    return MAGIC + nonce + _aesgcm(key).encrypt(nonce, data, None)


def decrypt(blob: bytes, key: bytes | None = None) -> bytes:
    key = key or _key
    if key is None:
        raise CryptoError("locked — no passphrase has been supplied")
    if not blob.startswith(MAGIC):
        raise CryptoError("not an encrypted cutecat file")
    nonce = blob[len(MAGIC):len(MAGIC) + NONCE_LEN]
    body = blob[len(MAGIC) + NONCE_LEN:]
    try:
        return _aesgcm(key).decrypt(nonce, body, None)
    except CryptoError:
        raise
    except Exception as exc:  # InvalidTag and friends
        raise CryptoError("wrong passphrase, or the file has been damaged") from exc


def looks_encrypted(data: bytes) -> bool:
    return data.startswith(MAGIC)



def unlock(passphrase: str) -> None:
    """Check the passphrase against the marker and keep the key for this run."""
    global _key
    try:
        meta = json.loads(marker_file().read_text(encoding="utf-8"))
        salt = bytes.fromhex(meta["salt"])
        check = bytes.fromhex(meta["check"])
    except (OSError, ValueError, KeyError) as exc:
        raise CryptoError("the encryption marker is missing or unreadable") from exc
    key = derive_key(passphrase, salt)
    try:
        ok = decrypt(check, key) == _CHECK
    except CryptoError:
        ok = False
    if not ok:
        raise CryptoError("wrong passphrase")
    _key = key


def lock() -> None:
    global _key
    _key = None


def _write_marker(salt: bytes, key: bytes) -> None:
    path = marker_file()
    path.write_text(
        json.dumps({"salt": salt.hex(), "check": encrypt(_CHECK, key).hex()}),
        encoding="utf-8",
    )
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass




def _stored_files() -> list[Path]:
    from cutecat import config as config_mod

    files = [config_mod.CONFIG_FILE] if config_mod.CONFIG_FILE.exists() else []
    if config_mod.SESSIONS_DIR.exists():
        files += sorted(
            p for p in config_mod.SESSIONS_DIR.iterdir()
            if p.is_file() and p.suffix in (config_mod.SESSION_EXT, ".json")
        )
    return files


def enable(passphrase: str) -> tuple[int, Path | None]:
    global _key
    if is_encrypted():
        raise CryptoError("already encrypted — use --decrypt first to change it")
    from cutecat import config as config_mod

    config_mod.ensure_dirs()
    salt = secrets.token_bytes(SALT_LEN)
    key = derive_key(passphrase, salt)
    count = 0
    for path in _stored_files():
        data = path.read_bytes()
        if looks_encrypted(data):
            continue
        _replace(path, encrypt(data, key), shred_old=True)
        count += 1
    _key = key
    _write_marker(salt, key)
    legacy = config_mod.legacy_config_file()
    if legacy is not None:
        shred(legacy)
    return count, legacy


def disable(passphrase: str) -> int:
    global _key
    if not is_encrypted():
        raise CryptoError("not encrypted")
    unlock(passphrase)  # raises on a wrong passphrase, before anything is written
    count = 0
    for path in _stored_files():
        data = path.read_bytes()
        if not looks_encrypted(data):
            continue
        _replace(path, decrypt(data, _key))
        count += 1
    marker_file().unlink(missing_ok=True)
    _key = None
    return count


def _replace(path: Path, data: bytes, shred_old: bool = False) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if shred_old:
        _overwrite(path)
    os.replace(tmp, path)


def _overwrite(path: Path) -> None:
    try:
        size = path.stat().st_size
        with open(path, "r+b", buffering=0) as fh:
            fh.write(secrets.token_bytes(size))
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass


def shred(path: Path) -> None:
    _overwrite(path)
    try:
        path.unlink()
    except OSError:
        pass
