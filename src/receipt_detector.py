"""
Kvittoigenkänning med regelbaserad AI + inlärning av kända avsändare.
"""
import re
from .storage import Storage

# Nyckelord som indikerar kvitto
RECEIPT_KEYWORDS_SV = [
    "kvitto", "orderbekräftelse", "faktura", "betalning", "köp",
    "order", "receipt", "invoice", "payment", "purchase", "confirmation",
    "beställning", "leverans", "transaction", "charged", "debit",
    "total", "summa", "att betala", "betalat", "tack för din beställning",
    "tack för ditt köp", "your order", "your receipt", "your invoice",
]

RECEIPT_SUBJECT_PATTERNS = [
    r"kvitto",
    r"order\s*(#|nr|nummer|bekräftelse)",
    r"faktura",
    r"betalning",
    r"receipt",
    r"invoice\s*(#|nr)?",
    r"your\s+(order|purchase|receipt)",
    r"order\s+confirmation",
    r"payment\s+(confirmation|receipt)",
    r"transaction\s+receipt",
]

KNOWN_RECEIPT_DOMAINS = [
    "noreply", "no-reply", "donotreply", "orders@", "receipts@",
    "billing@", "invoice@", "faktura@", "kvitto@", "payments@",
    "transactions@", "shop@", "store@", "butik@",
]

SPAM_INDICATORS = [
    "unsubscribe", "avprenumerera", "nyhetsbrev", "newsletter",
    "erbjudande", "kampanj", "rabatt kod", "promo",
]


class ReceiptDetector:
    def __init__(self, storage: Storage):
        self.storage = storage

    def is_receipt(self, email: dict) -> bool:
        """Returnerar True om mailet troligtvis är ett kvitto."""
        if email.get("force_receipt"):
            return True
        sender = email.get("sender", "").lower()
        subject = email.get("subject", "").lower()
        body = email.get("body_preview", "").lower()

        score = 0

        # Känd avsändare → direkt godkänd
        known_senders = [s.lower() for s in self.storage.get_known_senders()]
        for known in known_senders:
            if known in sender:
                email["known_sender"] = True
                self.storage.increment_sender_count(sender)
                return True

        # Poängsättning baserat på ämnesrad
        for pattern in RECEIPT_SUBJECT_PATTERNS:
            if re.search(pattern, subject, re.IGNORECASE):
                score += 3
                break

        # Nyckelord i ämne
        for kw in RECEIPT_KEYWORDS_SV:
            if kw in subject:
                score += 2

        # Nyckelord i brödtext
        keyword_hits = sum(1 for kw in RECEIPT_KEYWORDS_SV if kw in body)
        score += min(keyword_hits, 4)

        # Avsändardomän
        for indicator in KNOWN_RECEIPT_DOMAINS:
            if indicator in sender:
                score += 2
                break

        # Bifogade filer (PDF/bild = troligt kvitto)
        attachments = email.get("attachments", [])
        for att in attachments:
            name = att.get("name", "").lower()
            if name.endswith(".pdf") or name.endswith(".png") or name.endswith(".jpg"):
                score += 2

        # Spam-indikatorer sänker poängen
        for spam in SPAM_INDICATORS:
            if spam in subject or spam in body:
                score -= 2

        is_receipt = score >= 4

        if is_receipt:
            email["known_sender"] = False
            # Automatiskt lär sig avsändare med hög poäng
            if score >= 8:
                self.storage.add_known_sender(sender)
                email["known_sender"] = True
            self.storage.increment_sender_count(sender)

        return is_receipt

    def score_email(self, email: dict) -> dict:
        """Returnerar detaljerad poängsättning för felsökning."""
        sender = email.get("sender", "").lower()
        subject = email.get("subject", "").lower()
        body = email.get("body_preview", "").lower()
        breakdown = {}

        breakdown["known_sender"] = any(
            s.lower() in sender for s in self.storage.get_known_senders()
        )
        breakdown["subject_pattern"] = any(
            re.search(p, subject, re.IGNORECASE) for p in RECEIPT_SUBJECT_PATTERNS
        )
        breakdown["keyword_hits"] = sum(1 for kw in RECEIPT_KEYWORDS_SV if kw in body)
        breakdown["sender_domain"] = any(ind in sender for ind in KNOWN_RECEIPT_DOMAINS)
        breakdown["has_pdf"] = any(
            a.get("name", "").endswith(".pdf") for a in email.get("attachments", [])
        )

        return breakdown
