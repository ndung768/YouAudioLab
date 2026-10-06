"""Password hashers — including legacy Gate A1 raw bcrypt hashes."""

from __future__ import annotations

from django.contrib.auth.hashers import BasePasswordHasher, mask_hash


class LegacyBcryptPasswordHasher(BasePasswordHasher):
    """Verify Gate A1 hashes stored as ``legacy_bcrypt$<raw $2b$ digest>``.

    New passwords must not use this hasher (keep it after PBKDF2 in
    ``PASSWORD_HASHERS``). ``must_update`` is always True so a successful
    login can upgrade to the preferred hasher.
    """

    algorithm = "legacy_bcrypt"

    def salt(self) -> str:
        return ""

    def encode(self, password: str, salt: str) -> str:  # noqa: ARG002
        import bcrypt

        raw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        return f"{self.algorithm}${raw}"

    def decode(self, encoded: str) -> dict:
        algorithm, rest = encoded.split("$", 1)
        return {"algorithm": algorithm, "hash": rest}

    def verify(self, password: str, encoded: str) -> bool:
        import bcrypt

        decoded = self.decode(encoded)
        raw = decoded["hash"]
        if not raw.startswith("$2"):
            # Stored as legacy_bcrypt$$2b$... → split('$', 1) drops one '$'
            raw = "$" + raw if not raw.startswith("$") else raw
        try:
            return bcrypt.checkpw(password.encode("utf-8"), raw.encode("ascii"))
        except (ValueError, TypeError):
            return False

    def safe_summary(self, encoded: str) -> dict:
        decoded = self.decode(encoded)
        return {
            "algorithm": decoded["algorithm"],
            "hash": mask_hash(decoded["hash"], show=3),
        }

    def must_update(self, encoded: str) -> bool:  # noqa: ARG002
        return True

    def harden_runtime(self, password: str, encoded: str) -> None:
        pass
