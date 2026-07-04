import json
import logging as logger
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.fernet import Fernet, MultiFernet

from config import ProjectConfig
from src.enums import MongoCollectionsNames

_KEY_DOC_ID = "auth_key_config"

# In-process cache so we don't hit MongoDB on every request.
# Invalidated after _CACHE_TTL_SECONDS or when a rotation occurs.
_cache_lock = threading.Lock()
_cache: dict = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _key_collection():
    from src.mongodb.base import BaseDatabase

    return BaseDatabase.get_collection(MongoCollectionsNames.AUTH_KEY_STORE)


def _load_or_init_keys() -> dict:
    """Return the key document, generating a fresh key on first startup."""
    col = _key_collection()
    doc = col.find_one({"_id": _KEY_DOC_ID})
    if doc is None:
        doc = {
            "_id": _KEY_DOC_ID,
            "current_key": Fernet.generate_key().decode(),
            "prev_key": None,
            "rotated_at": datetime.now(timezone.utc),
        }
        col.insert_one(doc)
        logger.info("Auth key store initialised with a generated key.")
    return doc


def _get_keys(force_reload: bool = False) -> tuple[str, Optional[str]]:
    """Return (current_key, prev_key), using the in-process cache when fresh."""
    global _cache
    with _cache_lock:
        now = datetime.now(timezone.utc)
        loaded_at = _cache.get("loaded_at")
        if force_reload or not _cache or loaded_at is None or (now - loaded_at).total_seconds() > _CACHE_TTL_SECONDS:
            doc = _load_or_init_keys()
            _cache = {
                "current_key": doc["current_key"],
                "prev_key": doc.get("prev_key"),
                "rotated_at": doc["rotated_at"],
                "loaded_at": now,
            }
        return _cache["current_key"], _cache.get("prev_key")


def rotate_if_due() -> bool:
    """
    Automatically rotate the auth key if it is older than KEY_ROTATION_DAYS.
    - Promotes current_key → prev_key (so existing sessions keep working).
    - Generates a brand-new current_key.
    - Invalidates the in-process cache so all threads pick up the new key.
    Returns True if rotation was performed.
    """
    global _cache
    col = _key_collection()
    doc = col.find_one({"_id": _KEY_DOC_ID})
    if doc is None:
        _get_keys()  # initialise first
        return False

    rotated_at: datetime = doc["rotated_at"]
    if rotated_at.tzinfo is None:
        rotated_at = rotated_at.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) - rotated_at < timedelta(days=ProjectConfig.KEY_ROTATION_DAYS):
        return False

    new_key = Fernet.generate_key().decode()

    # Atomic check-and-set: only the worker whose read matched the current
    # rotated_at timestamp will succeed. All others get matched_count == 0
    # and skip, preventing duplicate rotations across multiple worker processes.
    result = col.find_one_and_update(
        {"_id": _KEY_DOC_ID, "rotated_at": doc["rotated_at"]},
        {
            "$set": {
                "prev_key": doc["current_key"],
                "current_key": new_key,
                "rotated_at": datetime.now(timezone.utc),
            }
        },
        return_document=False,
    )

    if result is None:
        # Another worker already rotated, just invalidate our cache
        with _cache_lock:
            _cache = {}
        return False

    # Invalidate cache so every thread in this process reloads on next request
    with _cache_lock:
        _cache = {}

    logger.info("Auth key rotated automatically.")
    return True


class EncryptionSystem:
    """
    Fernet-based symmetric encryption for auth tokens.

    Keys are stored in MongoDB and rotated automatically every KEY_ROTATION_DAYS days.
    MultiFernet tries the current key first, then the previous key, so existing
    sessions remain valid across a rotation.
    """

    def __init__(self):
        current_key, prev_key = _get_keys()
        keys = [Fernet(current_key.encode())]
        if prev_key:
            keys.append(Fernet(prev_key.encode()))
        self.cipher_suite = MultiFernet(keys)

    def encrypt_dict(self, input_json: dict) -> str:
        json_string = json.dumps(input_json)
        return self.cipher_suite.encrypt(json_string.encode()).decode()

    def decrypt_string(self, encrypted_string: str) -> dict:
        decrypted_string = self.cipher_suite.decrypt(encrypted_string.encode()).decode()
        return json.loads(decrypted_string)
