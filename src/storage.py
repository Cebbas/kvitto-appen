"""Lokal lagring av kvitton, kända avsändare och aktivitetslogg."""
import json
import os
import re
from datetime import datetime

DATA_DIR = os.path.join(os.path.expanduser("~"), ".kvitto-appen")
ATTACH_DIR = os.path.join(DATA_DIR, "attachments")


class Storage:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(ATTACH_DIR, exist_ok=True)
        self._receipts_path = os.path.join(DATA_DIR, "receipts.json")
        self._senders_path  = os.path.join(DATA_DIR, "senders.json")
        self._activity_path = os.path.join(DATA_DIR, "activity.json")
        self._accounts_path = os.path.join(DATA_DIR, "accounts.json")

        self._deleted_path  = os.path.join(DATA_DIR, "deleted_receipts.json")
        self._profiles_path = os.path.join(DATA_DIR, "sender_profiles.json")
        self._receipts  = self._load(self._receipts_path, [])
        self._deleted   = self._load(self._deleted_path, [])
        self._senders   = self._load(self._senders_path, {})   # sender -> count
        self._activity  = self._load(self._activity_path, [])
        self._accounts  = self._load(self._accounts_path, {})
        self._profiles  = self._load(self._profiles_path, {})  # sender_key -> {display_name, aliases}

    # ── Receipts ─────────────────────────────────────────────────

    def get_receipts(self):
        return sorted(self._receipts, key=lambda r: r.get("date", ""), reverse=True)

    def save_receipt(self, receipt: dict):
        """Sparar kvitto om det inte redan finns (dedup på message_id)."""
        msg_id = receipt.get("message_id")
        if msg_id and any(r.get("message_id") == msg_id for r in self._receipts):
            return  # redan sparat
        receipt["saved_at"] = datetime.now().isoformat()

        # Spara eventuella bilagor till disk och ersätt data-bytes med sökväg
        saved_atts = []
        for att in receipt.get("attachments", []):
            data = att.get("data")
            name = att.get("name") or "bilaga"
            safe_name = re.sub(r"[^\w.\-]", "_", name)
            if data and isinstance(data, (bytes, bytearray)):
                folder_id = re.sub(r"[^\w]", "_", msg_id or receipt.get("saved_at", "x"))[:40]
                folder = os.path.join(ATTACH_DIR, folder_id)
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, safe_name)
                with open(path, "wb") as f:
                    f.write(data)
                saved_atts.append({"name": name, "mimeType": att.get("mimeType", ""), "path": path})
            else:
                saved_atts.append({"name": name, "mimeType": att.get("mimeType", "")})
        receipt["attachments"] = saved_atts

        self._receipts.append(receipt)
        self._save(self._receipts_path, self._receipts)

    def delete_receipt(self, message_id: str):
        to_delete = [r for r in self._receipts if r.get("message_id") == message_id]
        self._receipts = [r for r in self._receipts if r.get("message_id") != message_id]
        self._deleted.extend(to_delete)
        self._save(self._receipts_path, self._receipts)
        self._save(self._deleted_path, self._deleted)

    def get_deleted_receipts(self) -> list:
        return sorted(self._deleted, key=lambda r: r.get("saved_at", ""), reverse=True)

    def restore_receipt(self, message_id: str):
        to_restore = [r for r in self._deleted if r.get("message_id") == message_id]
        self._deleted = [r for r in self._deleted if r.get("message_id") != message_id]
        self._receipts.extend(to_restore)
        self._save(self._receipts_path, self._receipts)
        self._save(self._deleted_path, self._deleted)

    # ── Known senders ────────────────────────────────────────────

    def get_known_senders(self) -> list:
        return list(self._senders.keys())

    def add_known_sender(self, sender: str):
        if sender not in self._senders:
            self._senders[sender] = 0
        self._save(self._senders_path, self._senders)

    def remove_known_sender(self, sender: str):
        self._senders.pop(sender, None)
        self._profiles.pop(self._pkey(sender), None)
        self._save(self._senders_path, self._senders)
        self._save(self._profiles_path, self._profiles)

    def increment_sender_count(self, sender: str):
        self._senders[sender] = self._senders.get(sender, 0) + 1
        self._save(self._senders_path, self._senders)

    # ── Sender profiles (visningsnamn + sammanslagning) ────────────

    def _pkey(self, sender: str) -> str:
        return (sender or "").lower()

    def get_sender_profile(self, sender: str) -> dict:
        p = self._profiles.get(self._pkey(sender), {})
        return {
            "display_name": p.get("display_name") or sender,
            "aliases":      p.get("aliases", []),
        }

    def set_sender_display_name(self, sender: str, name: str):
        k = self._pkey(sender)
        self._profiles.setdefault(k, {})["display_name"] = name.strip()
        self._save(self._profiles_path, self._profiles)

    def merge_sender(self, primary: str, alias: str):
        """Slår ihop 'alias' in i 'primary'. Alias tas bort från kända avsändare."""
        pk, ak = self._pkey(primary), self._pkey(alias)
        if pk == ak:
            return
        profile = self._profiles.setdefault(pk, {})
        aliases = set(profile.get("aliases", []))
        aliases.add(ak)
        alias_profile = self._profiles.get(ak, {})
        aliases.update(alias_profile.get("aliases", []))
        profile["aliases"] = sorted(aliases)
        self._profiles.pop(ak, None)
        self._senders = {s: c for s, c in self._senders.items() if self._pkey(s) != ak}
        self._save(self._profiles_path, self._profiles)
        self._save(self._senders_path, self._senders)

    def unmerge_alias(self, primary: str, alias: str):
        """Lyfter ut 'alias' ur 'primary' till en egen känd avsändare igen."""
        pk, ak = self._pkey(primary), self._pkey(alias)
        profile = self._profiles.get(pk, {})
        aliases = [a for a in profile.get("aliases", []) if a != ak]
        profile["aliases"] = aliases
        self._save(self._profiles_path, self._profiles)
        if ak not in self._senders:
            self._senders[ak] = 0
            self._save(self._senders_path, self._senders)

    def get_sender_match_keys(self, sender: str) -> list:
        """Alla nycklar (huvud + alias) som ska räknas som samma avsändare."""
        k = self._pkey(sender)
        profile = self._profiles.get(k, {})
        return [k] + profile.get("aliases", [])

    # ── Activity log ─────────────────────────────────────────────

    def log_activity(self, icon: str, text: str, message_ids: list = None):
        entry = {
            "icon": icon,
            "text": text,
            "time": datetime.now().strftime("%d %b %H:%M"),
            "message_ids": message_ids or [],
        }
        self._activity.insert(0, entry)
        self._activity = self._activity[:100]  # håll senaste 100
        self._save(self._activity_path, self._activity)

    def get_receipts_by_ids(self, message_ids: list) -> list:
        ids = set(message_ids or [])
        return [r for r in self._receipts if r.get("message_id") in ids]

    def get_recent_activity(self, n: int = 20) -> list:
        return self._activity[:n]

    # ── Stats ────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        now = datetime.now()
        this_month = sum(
            1 for r in self._receipts
            if r.get("date", "")[:7] == now.strftime("%Y-%m")
        )
        return {
            "total":         len(self._receipts),
            "this_month":    this_month,
            "known_senders": len(self._senders),
        }

    # ── Accounts ─────────────────────────────────────────────────

    def save_account(self, provider: str, data: dict):
        self._accounts[provider] = data
        self._save(self._accounts_path, self._accounts)

    def get_account(self, provider: str) -> dict:
        return self._accounts.get(provider, {})

    def remove_account(self, provider: str):
        self._accounts.pop(provider, None)
        self._save(self._accounts_path, self._accounts)

    # ── Helpers ──────────────────────────────────────────────────

    def _load(self, path: str, default):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return default

    def _save(self, path: str, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
