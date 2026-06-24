"""Gmail-klient via Google OAuth2 + Gmail API."""
import os
import json
import re
import html
import base64
import pickle
import email.utils
from datetime import datetime

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

from .storage import Storage

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DATA_DIR = os.path.join(os.path.expanduser("~"), ".kvitto-appen")
TOKEN_PATH = os.path.join(DATA_DIR, "gmail_token.pickle")
CREDS_PATH = os.path.join(DATA_DIR, "gmail_credentials.json")

# Google OAuth credentials – användaren fyller i sina egna
DEFAULT_CREDENTIALS = {
    "installed": {
        "client_id":     "DIN_GMAIL_CLIENT_ID",
        "client_secret": "DIN_GMAIL_CLIENT_SECRET",
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
        "token_uri":     "https://oauth2.googleapis.com/token",
    }
}


class GmailClient:
    def __init__(self, storage: Storage):
        self.storage = storage
        self._service = None
        self._email = None

        # Försök återansluta om token finns
        if GOOGLE_AVAILABLE and os.path.exists(TOKEN_PATH):
            try:
                self._init_service()
            except Exception:
                pass

    def is_connected(self) -> bool:
        return self._service is not None

    def get_email(self) -> str:
        return self._email or self.storage.get_account("gmail").get("email", "")

    def has_credentials(self) -> bool:
        if not os.path.exists(CREDS_PATH):
            return False
        try:
            with open(CREDS_PATH) as f:
                data = json.load(f)
            return data.get("installed", {}).get("client_id") != "DIN_GMAIL_CLIENT_ID"
        except Exception:
            return False

    def connect(self, client_id: str = None, client_secret: str = None) -> str:
        if not GOOGLE_AVAILABLE:
            raise RuntimeError(
                "Google-bibliotek saknas. Kör: pip install google-auth google-auth-oauthlib google-api-python-client"
            )

        if client_id and client_secret:
            creds_dict = {
                "installed": {
                    "client_id":     client_id.strip(),
                    "client_secret": client_secret.strip(),
                    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                    "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                    "token_uri":     "https://oauth2.googleapis.com/token",
                }
            }
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(CREDS_PATH, "w") as f:
                json.dump(creds_dict, f)
        elif not self.has_credentials():
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(CREDS_PATH, "w") as f:
                json.dump(DEFAULT_CREDENTIALS, f)
            raise RuntimeError("Fyll i Client ID och Client secret.")

        creds = None
        if os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH, "rb") as f:
                creds = pickle.load(f)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    # Refresh-token indraget/utgånget (vanligt i Googles Testing-läge
                    # efter 7 dagar) – starta om hela inloggningen istället.
                    creds = None

            if not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(TOKEN_PATH, "wb") as f:
                pickle.dump(creds, f)

        self._init_service(creds)
        return self._email

    def _init_service(self, creds=None):
        if creds is None and os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH, "rb") as f:
                creds = pickle.load(f)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())

        self._service = build("gmail", "v1", credentials=creds)
        profile = self._service.users().getProfile(userId="me").execute()
        self._email = profile.get("emailAddress", "")
        self.storage.save_account("gmail", {"email": self._email})

    def disconnect(self):
        self._service = None
        self._email = None
        if os.path.exists(TOKEN_PATH):
            os.remove(TOKEN_PATH)
        self.storage.remove_account("gmail")

    def tag_as_receipt(self, message_id: str):
        """Sätter label 'Kvitto' på mailet i Gmail. Skapar labeln om den inte finns."""
        if not self._service:
            return
        try:
            label_id = self._get_or_create_label("Kvitto")
            self._service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_id]}
            ).execute()
        except Exception:
            pass  # Taggning är best-effort, ska inte stoppa flödet

    def _get_or_create_label(self, name: str) -> str:
        """Returnerar label-ID för 'name', skapar den om den saknas."""
        labels = self._service.users().labels().list(userId="me").execute()
        for label in labels.get("labels", []):
            if label["name"].lower() == name.lower():
                return label["id"]
        # Skapa ny label med grön färg
        new_label = self._service.users().labels().create(
            userId="me",
            body={
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
                "color": {"backgroundColor": "#16a765", "textColor": "#ffffff"},
            }
        ).execute()
        return new_label["id"]

    def fetch_emails(self, max_results: int = 100) -> list:
        if not self._service:
            return []

        results = self._service.users().messages().list(
            userId="me",
            maxResults=max_results,
            q="has:attachment OR subject:kvitto OR subject:receipt OR subject:faktura OR subject:order"
        ).execute()

        messages = results.get("messages", [])
        emails = []
        for msg_ref in messages:
            try:
                msg = self._service.users().messages().get(
                    userId="me", id=msg_ref["id"], format="full"
                ).execute()
                parsed = self._parse_message(msg)
                emails.append(parsed)
            except Exception:
                continue
        return emails

    def _parse_message(self, msg: dict) -> dict:
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        payload = msg.get("payload", {})

        body_text = self._extract_body(payload)
        attachments = self._extract_attachments(payload, msg.get("id", ""))

        return {
            "message_id":   msg.get("id"),
            "source":       "gmail",
            "sender":       headers.get("From", ""),
            "subject":      headers.get("Subject", ""),
            "date":         self._normalize_date(headers.get("Date", "")),
            "body_preview": body_text[:800],
            "attachments":  attachments,
        }

    def _normalize_date(self, raw_date: str) -> str:
        if not raw_date:
            return ""
        try:
            return email.utils.parsedate_to_datetime(raw_date).isoformat()
        except Exception:
            return raw_date

    def _walk_parts(self, payload: dict):
        """Går igenom payload och alla nästlade parts (multipart/alternative, multipart/mixed osv)."""
        yield payload
        for part in payload.get("parts", []):
            yield from self._walk_parts(part)

    def _extract_body(self, payload: dict) -> str:
        def decode(data):
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                return ""

        plain, html_body = "", ""
        for part in self._walk_parts(payload):
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data")
            if not data:
                continue
            if mime == "text/plain" and not plain:
                plain = decode(data)
            elif mime == "text/html" and not html_body:
                html_body = decode(data)

        if plain:
            return plain
        if html_body:
            return self._html_to_text(html_body)
        return ""

    def _html_to_text(self, html_str: str) -> str:
        text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", html_str,
                      flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_attachments(self, payload: dict, message_id: str) -> list:
        attachments = []
        for part in self._walk_parts(payload):
            filename = part.get("filename", "")
            attachment_id = part.get("body", {}).get("attachmentId", "")
            if not filename or not attachment_id:
                continue

            data = None
            try:
                att = self._service.users().messages().attachments().get(
                    userId="me", messageId=message_id, id=attachment_id
                ).execute()
                raw = att.get("data")
                if raw:
                    data = base64.urlsafe_b64decode(raw)
            except Exception:
                pass

            attachments.append({
                "name":     filename,
                "mimeType": part.get("mimeType", ""),
                "data":     data,
            })
        return attachments
