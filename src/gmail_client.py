"""Gmail-klient via Google OAuth2 + Gmail API."""
import os
import json
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

    def connect(self) -> str:
        if not GOOGLE_AVAILABLE:
            raise RuntimeError(
                "Google-bibliotek saknas. Kör: pip install google-auth google-auth-oauthlib google-api-python-client"
            )

        # Skapa credentials-fil om den inte finns
        if not os.path.exists(CREDS_PATH):
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(CREDS_PATH, "w") as f:
                json.dump(DEFAULT_CREDENTIALS, f)
            raise RuntimeError(
                f"Fyll i dina Gmail OAuth-uppgifter i:\n{CREDS_PATH}\n\n"
                "Skapa ett projekt på console.cloud.google.com, "
                "aktivera Gmail API och ladda ner OAuth-klientuppgifter."
            )

        creds = None
        if os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH, "rb") as f:
                creds = pickle.load(f)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
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
        attachments = self._extract_attachments(payload)

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

    def _extract_body(self, payload: dict) -> str:
        def decode(data):
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                return ""

        if payload.get("body", {}).get("data"):
            return decode(payload["body"]["data"])

        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return decode(part["body"]["data"])
        return ""

    def _extract_attachments(self, payload: dict) -> list:
        attachments = []
        for part in payload.get("parts", []):
            filename = part.get("filename", "")
            if filename:
                attachments.append({
                    "name":        filename,
                    "mimeType":    part.get("mimeType", ""),
                    "attachmentId": part.get("body", {}).get("attachmentId", ""),
                })
        return attachments
