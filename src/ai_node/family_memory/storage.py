import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from ai_node.family_memory.models import FamilyMemoryRecord
from ai_node.persistence.file_storage_lock import file_storage_lock, locked_json_temp_path


FAMILY_MEMORY_STORE_SCHEMA_VERSION = "1.0"


class FamilyMemoryStoreError(RuntimeError):
    pass


def _scope_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class EncryptedFamilyMemoryStore:
    def __init__(self, *, root: Path, master_key: bytes) -> None:
        if len(master_key) != 32:
            raise ValueError("family_memory_master_key_must_be_32_bytes")
        self._root = root
        self._master_key = bytes(master_key)

    def upsert(self, record: FamilyMemoryRecord) -> None:
        for person_id in record.subject_person_ids:
            path = self._partition_path(
                core_id=record.core_id,
                household_id=record.household_id,
                person_id=person_id,
            )
            with file_storage_lock(path):
                records = self._load_partition_locked(
                    path=path,
                    core_id=record.core_id,
                    household_id=record.household_id,
                    person_id=person_id,
                )
                by_id = {item.memory_id: item for item in records}
                by_id[record.memory_id] = record
                self._save_partition_locked(
                    path=path,
                    core_id=record.core_id,
                    household_id=record.household_id,
                    person_id=person_id,
                    records=sorted(by_id.values(), key=lambda item: item.memory_id),
                )

    def load_partition(self, *, core_id: str, household_id: str, person_id: str) -> list[FamilyMemoryRecord]:
        path = self._partition_path(core_id=core_id, household_id=household_id, person_id=person_id)
        with file_storage_lock(path):
            return self._load_partition_locked(
                path=path,
                core_id=core_id,
                household_id=household_id,
                person_id=person_id,
            )

    def _partition_path(self, *, core_id: str, household_id: str, person_id: str) -> Path:
        return (
            self._root
            / _scope_hash(core_id)
            / _scope_hash(household_id)
            / f"{_scope_hash(person_id)}.json.enc"
        )

    @staticmethod
    def _associated_data(*, core_id: str, household_id: str, person_id: str) -> bytes:
        return json.dumps(
            {
                "schema_version": FAMILY_MEMORY_STORE_SCHEMA_VERSION,
                "core_scope": _scope_hash(core_id),
                "household_scope": _scope_hash(household_id),
                "person_scope": _scope_hash(person_id),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _partition_key(self, *, core_id: str, household_id: str, person_id: str) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=hashlib.sha256(f"{core_id}\0{household_id}".encode("utf-8")).digest(),
            info=f"hexe-family-memory-v1\0{person_id}".encode("utf-8"),
        ).derive(self._master_key)

    def _load_partition_locked(
        self,
        *,
        path: Path,
        core_id: str,
        household_id: str,
        person_id: str,
    ) -> list[FamilyMemoryRecord]:
        if not path.exists():
            return []
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if envelope.get("schema_version") != FAMILY_MEMORY_STORE_SCHEMA_VERSION:
                raise FamilyMemoryStoreError("family_memory_store_version_unsupported")
            nonce = base64.b64decode(str(envelope["nonce"]), validate=True)
            ciphertext = base64.b64decode(str(envelope["ciphertext"]), validate=True)
            plaintext = AESGCM(
                self._partition_key(core_id=core_id, household_id=household_id, person_id=person_id)
            ).decrypt(
                nonce,
                ciphertext,
                self._associated_data(core_id=core_id, household_id=household_id, person_id=person_id),
            )
            payload = json.loads(plaintext.decode("utf-8"))
            if not isinstance(payload, list):
                raise ValueError("partition_payload_not_list")
            records = [FamilyMemoryRecord.model_validate(item) for item in payload]
        except FamilyMemoryStoreError:
            raise
        except Exception as exc:
            raise FamilyMemoryStoreError("family_memory_store_decryption_failed") from exc
        for record in records:
            if (
                record.core_id != core_id
                or record.household_id != household_id
                or person_id not in record.subject_person_ids
            ):
                raise FamilyMemoryStoreError("family_memory_store_scope_mismatch")
        return records

    def _save_partition_locked(
        self,
        *,
        path: Path,
        core_id: str,
        household_id: str,
        person_id: str,
        records: list[FamilyMemoryRecord],
    ) -> None:
        plaintext = json.dumps(
            [record.model_dump(mode="json") for record in records],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = AESGCM(
            self._partition_key(core_id=core_id, household_id=household_id, person_id=person_id)
        ).encrypt(
            nonce,
            plaintext,
            self._associated_data(core_id=core_id, household_id=household_id, person_id=person_id),
        )
        envelope = {
            "schema_version": FAMILY_MEMORY_STORE_SCHEMA_VERSION,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = locked_json_temp_path(path)
        try:
            temp_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
            os.chmod(temp_path, 0o600)
            temp_path.replace(path)
            os.chmod(path, 0o600)
        finally:
            temp_path.unlink(missing_ok=True)
