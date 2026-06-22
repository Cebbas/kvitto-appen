"""iCloud Mail-klient via IMAP med app-lösenord."""
import imaplib
import email
import email.header
import html
import re
import os
import json
from datetime import datetime, timedelta
from .storage import Storage

# Mappnamn (lowercase, delsträngsmatch) där allt räknas som kvitto utan vidare kontroll
RECEIPT_FOLDERS = {"ordrar", "laddkviton", "handel", "fakturor", "kvitton",
                   "receipts", "orders", "fakturer", "kviton", "faktura"}

DATA_DIR = os.path.join(os.path.expanduser("~"), ".kvitto-appen")
CONFIG_PATH = os.path.join(DATA_DIR, "icloud_config.json")

ICLOUD_IMAP_HOST = "imap.mail.me.com"
ICLOUD_IMAP_PORT = 993

DEFAULT_CONFIG = {
    "email":        "din@icloud.com",
    "app_password": "DITT-APP-LÖSENORD",
}


class ICloudClient:
    def __init__(self, storage: Storage):
        self.storage = storage
        self._connected = False
        self._email_addr = None

        account = self.storage.get_account("icloud")
        if account.get("email"):
            self._email_addr = account["email"]
            self._connected = True  # Optimistisk – verifieras vid fetch

    def is_connected(self) -> bool:
        return self._connected

    def get_email(self) -> str:
        return self._email_addr or self.storage.get_account("icloud").get("email", "")

    def connect(self, email: str = None, password: str = None) -> str:
        if email and password:
            config = {"email": email.strip(), "app_password": password.strip()}
        else:
            config = self._load_config()

        if not config.get("email") or not config.get("app_password"):
            raise RuntimeError("Fyll i e-post och app-lösenord.")

        imap = self._connect_imap(config)
        imap.logout()

        self._email_addr = config["email"]
        self._connected = True
        self.storage.save_account("icloud", {
            "email":        self._email_addr,
            "app_password": config["app_password"],
        })
        return self._email_addr

    def disconnect(self):
        self._connected = False
        self._email_addr = None
        self.storage.remove_account("icloud")

    def tag_as_receipt(self, message_id: str):
        """Sätter IMAP-keyword 'Kvitto' på mailet. Syns som flagga i Mail.app."""
        if not self._connected:
            return
        try:
            config = self._load_config()
            imap = self._connect_imap(config)
            imap.select("INBOX")
            # message_id är här IMAP UID – vi söker upp det
            _, data = imap.search(None, f'HEADER Message-ID "{message_id}"')
            ids = data[0].split()
            if ids:
                imap.store(ids[-1], "+FLAGS", "Kvitto")
            imap.logout()
        except Exception:
            pass

    def fetch_emails(self, max_results: int = 100) -> list:
        if not self._connected:
            return []

        config = self._load_config()
        try:
            imap = self._connect_imap(config)
        except Exception as e:
            self._connected = False
            raise RuntimeError(f"iCloud IMAP fel: {e}")

        emails = []
        seen_ids = set()
        since_date = (datetime.now() - timedelta(days=90)).strftime("%d-%b-%Y")

        SKIP_FOLDERS = {"drafts", "sent", "trash", "junk", "spam", "deleted",
                        "utkast", "skickat", "papperskorg", "skräppost", "sent messages"}

        _, folder_data = imap.list()
        receipt_folders, other_folders = [], []
        for f in folder_data or []:
            name = f.decode(errors="replace") if isinstance(f, bytes) else f
            # Format: `flags "/" "FolderName"` — mappnamnet är näst sista elementet
            parts = name.split('"')
            fn = parts[-2].strip() if len(parts) >= 2 else name.split()[-1]
            if not fn or fn.lower() in SKIP_FOLDERS:
                continue
            base = fn.split("/")[-1].lower()
            if any(kw in base for kw in RECEIPT_FOLDERS):
                receipt_folders.append(fn)
            else:
                other_folders.append(fn)

        def _scan_folder(folder, limit, force_receipt=False):
            try:
                status, _ = imap.select(f'"{folder}"')
                if status != "OK":
                    return
            except Exception:
                return
            _, msg_ids = imap.search(None, f'SINCE "{since_date}"')
            id_list = msg_ids[0].split() if msg_ids and msg_ids[0] else []
            for msg_id in reversed(id_list[-limit:]):
                if msg_id in seen_ids or len(emails) >= max_results:
                    break
                seen_ids.add(msg_id)
                try:
                    _, msg_data = imap.fetch(msg_id, "BODY[]")
                    if not msg_data or not isinstance(msg_data[0], tuple):
                        continue
                    parsed = self._parse_raw_email(msg_data[0][1])
                    if parsed:
                        if force_receipt:
                            parsed["force_receipt"] = True
                        emails.append(parsed)
                except Exception:
                    continue

        try:
            # Kvitto-mappar: upp till 50 mail var, markeras direkt som kvitto
            for folder in receipt_folders:
                _scan_folder(folder, limit=50, force_receipt=True)

            # INBOX + övriga mappar delar resterande budget
            remaining = max_results - len(emails)
            if remaining > 0:
                all_other = ["INBOX"] + other_folders
                per_folder = max(10, remaining // len(all_other))
                for folder in all_other:
                    _scan_folder(folder, limit=per_folder)
                    if len(emails) >= max_results:
                        break
        finally:
            try:
                imap.logout()
            except Exception:
                pass

        return emails

    def _connect_imap(self, config: dict) -> imaplib.IMAP4_SSL:
        imap = imaplib.IMAP4_SSL(ICLOUD_IMAP_HOST, ICLOUD_IMAP_PORT)
        imap.login(config["email"], config["app_password"])
        return imap

    def _parse_raw_email(self, raw: bytes) -> dict | None:
        try:
            msg = email.message_from_bytes(raw)
        except Exception:
            return None

        sender  = self._decode_header(msg.get("From", ""))
        subject = self._decode_header(msg.get("Subject", ""))
        date    = self._normalize_date(msg.get("Date", ""))
        msg_id  = msg.get("Message-ID", "")

        body_plain = ""
        body_html  = ""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition  = str(part.get("Content-Disposition", ""))

                if "attachment" in disposition:
                    fname = part.get_filename() or ""
                    try:
                        data = part.get_payload(decode=True)
                    except Exception:
                        data = None
                    attachments.append({
                        "name":     fname,
                        "mimeType": content_type,
                        "data":     data,
                    })
                elif content_type == "text/plain" and not body_plain:
                    try:
                        body_plain = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace")
                    except Exception:
                        pass
                elif content_type == "text/html" and not body_html:
                    try:
                        body_html = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace")
                    except Exception:
                        pass
        else:
            ct = msg.get_content_type()
            try:
                raw_text = msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", errors="replace")
                if ct == "text/html":
                    body_html = raw_text
                else:
                    body_plain = raw_text
            except Exception:
                pass

        # Extrahera text från HTML om text/plain saknas
        if not body_plain and body_html:
            body_plain = self._html_to_text(body_html)

        return {
            "message_id":   msg_id,
            "source":       "icloud",
            "sender":       sender,
            "subject":      subject,
            "date":         date,
            "body_preview": body_plain[:800],
            "attachments":  attachments,
        }

    def _html_to_text(self, html_str: str) -> str:
        text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", html_str,
                      flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _normalize_date(self, raw_date: str) -> str:
        """Konverterar RFC2822-datum (Date-header) till ISO 8601 för korrekt sortering/jämförelse."""
        if not raw_date:
            return ""
        try:
            dt = email.utils.parsedate_to_datetime(raw_date)
            return dt.isoformat()
        except Exception:
            return raw_date

    def _decode_header(self, value: str) -> str:
        parts = email.header.decode_header(value)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(str(part))
        return " ".join(decoded)

    def _load_config(self) -> dict:
        # Prioritera uppgifter sparade via UI
        saved = self.storage.get_account("icloud")
        if saved.get("email") and saved.get("app_password"):
            return saved
        # Fallback: JSON-fil
        if not os.path.exists(CONFIG_PATH):
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
