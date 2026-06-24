"""Outlook/Hotmail-klient via Microsoft MSAL + Graph API."""
import os
import json
import base64
import requests

try:
    import msal
    MSAL_AVAILABLE = True
except ImportError:
    MSAL_AVAILABLE = False

from .storage import Storage

DATA_DIR = os.path.join(os.path.expanduser("~"), ".kvitto-appen")
TOKEN_CACHE_PATH = os.path.join(DATA_DIR, "outlook_token_cache.json")
CONFIG_PATH = os.path.join(DATA_DIR, "outlook_config.json")

GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/Mail.Read"]

DEFAULT_CONFIG = {
    "client_id":  "DIN_AZURE_CLIENT_ID",
    "tenant_id":  "consumers",
}


class OutlookClient:
    def __init__(self, storage: Storage):
        self.storage = storage
        self._token = None
        self._email = None
        self._app = None

        account_data = self.storage.get_account("outlook")
        if account_data.get("email") and MSAL_AVAILABLE:
            try:
                self._try_silent_auth()
            except Exception:
                pass

    def is_connected(self) -> bool:
        return self._token is not None

    def get_email(self) -> str:
        return self._email or self.storage.get_account("outlook").get("email", "")

    def has_credentials(self) -> bool:
        return self._load_config().get("client_id") != "DIN_AZURE_CLIENT_ID"

    def connect(self, client_id: str = None) -> str:
        if not MSAL_AVAILABLE:
            raise RuntimeError(
                "MSAL saknas. Kör: pip install msal"
            )

        if client_id:
            config = {"client_id": client_id.strip(), "tenant_id": "consumers"}
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
        else:
            config = self._load_config()
            if config.get("client_id") == "DIN_AZURE_CLIENT_ID":
                raise RuntimeError("Fyll i ditt Azure Application (client) ID.")

        cache = msal.SerializableTokenCache()
        if os.path.exists(TOKEN_CACHE_PATH):
            with open(TOKEN_CACHE_PATH, "r") as f:
                cache.deserialize(f.read())

        self._app = msal.PublicClientApplication(
            client_id=config["client_id"],
            authority=f"https://login.microsoftonline.com/{config['tenant_id']}",
            token_cache=cache,
        )

        # Försök tyst inloggning
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._token = result["access_token"]
                self._save_cache(cache)
                return self._fetch_email()

        # Interaktiv inloggning
        result = self._app.acquire_token_interactive(scopes=SCOPES)
        if "access_token" not in result:
            raise RuntimeError(f"Inloggning misslyckades: {result.get('error_description', '')}")

        self._token = result["access_token"]
        self._save_cache(cache)
        return self._fetch_email()

    def _try_silent_auth(self):
        config = self._load_config()
        if config.get("client_id") == "DIN_AZURE_CLIENT_ID":
            return

        cache = msal.SerializableTokenCache()
        if os.path.exists(TOKEN_CACHE_PATH):
            with open(TOKEN_CACHE_PATH, "r") as f:
                cache.deserialize(f.read())

        self._app = msal.PublicClientApplication(
            client_id=config["client_id"],
            authority=f"https://login.microsoftonline.com/{config['tenant_id']}",
            token_cache=cache,
        )
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._token = result["access_token"]
                self._email = self.storage.get_account("outlook").get("email", "")
                self._save_cache(cache)

    def _fetch_email(self) -> str:
        resp = requests.get(
            f"{GRAPH_ENDPOINT}/me",
            headers={"Authorization": f"Bearer {self._token}"}
        )
        self._email = resp.json().get("mail") or resp.json().get("userPrincipalName", "")
        self.storage.save_account("outlook", {"email": self._email})
        return self._email

    def disconnect(self):
        self._token = None
        self._email = None
        self._app = None
        if os.path.exists(TOKEN_CACHE_PATH):
            os.remove(TOKEN_CACHE_PATH)
        self.storage.remove_account("outlook")

    def tag_as_receipt(self, message_id: str):
        """Sätter kategorin 'Kvitto' på mailet i Outlook via Graph API."""
        if not self._token:
            return
        try:
            requests.patch(
                f"{GRAPH_ENDPOINT}/me/messages/{message_id}",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                json={"categories": ["Kvitto"]},
            )
        except Exception:
            pass

    def fetch_emails(self, max_results: int = 100) -> list:
        if not self._token:
            return []

        filter_q = (
            "contains(subject,'kvitto') or contains(subject,'receipt') or "
            "contains(subject,'faktura') or contains(subject,'order') or "
            "contains(subject,'invoice') or contains(subject,'payment') or "
            "hasAttachments eq true"
        )

        resp = requests.get(
            f"{GRAPH_ENDPOINT}/me/messages",
            headers={"Authorization": f"Bearer {self._token}"},
            params={
                "$filter": filter_q,
                "$top":    max_results,
                "$select": "id,from,subject,receivedDateTime,body,hasAttachments",
            }
        )

        if resp.status_code != 200:
            return []

        emails = []
        for msg in resp.json().get("value", []):
            emails.append(self._parse_message(msg))
        return emails

    def _parse_message(self, msg: dict) -> dict:
        sender = msg.get("from", {}).get("emailAddress", {})
        sender_str = f"{sender.get('name', '')} <{sender.get('address', '')}>".strip()
        body_text = msg.get("body", {}).get("content", "")
        # Strippa HTML
        import re, base64, html
        body_text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", body_text,
                            flags=re.DOTALL | re.IGNORECASE)
        body_text = re.sub(r"<[^>]+>", " ", body_text)
        body_text = html.unescape(body_text)
        body_text = re.sub(r"\s+", " ", body_text).strip()

        attachments = []
        if msg.get("hasAttachments"):
            att_resp = requests.get(
                f"{GRAPH_ENDPOINT}/me/messages/{msg['id']}/attachments",
                headers={"Authorization": f"Bearer {self._token}"},
                params={"$select": "name,contentType,contentBytes,@odata.type"}
            )
            if att_resp.status_code == 200:
                for att in att_resp.json().get("value", []):
                    data = None
                    content_bytes = att.get("contentBytes")
                    if content_bytes:
                        try:
                            data = base64.b64decode(content_bytes)
                        except Exception:
                            pass
                    attachments.append({
                        "name":     att.get("name", ""),
                        "mimeType": att.get("contentType", ""),
                        "data":     data,
                    })

        return {
            "message_id":   msg.get("id"),
            "source":       "outlook",
            "sender":       sender_str,
            "subject":      msg.get("subject", ""),
            "date":         msg.get("receivedDateTime", ""),
            "body_preview": body_text[:800],
            "attachments":  attachments,
        }

    def _load_config(self) -> dict:
        if not os.path.exists(CONFIG_PATH):
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)

    def _save_cache(self, cache):
        with open(TOKEN_CACHE_PATH, "w") as f:
            f.write(cache.serialize())
