"""Kontrollerar om kända avsändare saknas för en given månad."""
import statistics
from datetime import datetime
from dateutil.relativedelta import relativedelta
from .storage import Storage


class MissingChecker:
    def __init__(self, storage: Storage):
        self.storage = storage

    def _matches(self, sender_lower: str, match_keys: list) -> bool:
        return any(mk in sender_lower or sender_lower in mk for mk in match_keys)

    def _receipts_for(self, sender_key: str) -> list:
        """Alla kvitton som hör till en avsändare, inklusive sammanslagna alias."""
        match_keys = self.storage.get_sender_match_keys(sender_key)
        return [
            r for r in self.storage.get_receipts()
            if self._matches((r.get("sender") or "").lower(), match_keys)
        ]

    def filter_expected(self, receipts: list) -> tuple:
        """
        Delar upp en lista kvitton i (förväntade, ej förväntade) baserat på
        vilka avsändare som är markerade 'förväntade varje månad'.
        """
        expected = self.storage.get_expected_monthly_senders()
        match_key_lists = [self.storage.get_sender_match_keys(e) for e in expected]

        included, other = [], []
        for r in receipts:
            sender_lower = (r.get("sender") or "").lower()
            if any(self._matches(sender_lower, mks) for mks in match_key_lists):
                included.append(r)
            else:
                other.append(r)
        return included, other

    def check_month(self, month: str, senders: list = None) -> list:
        """
        Returnerar lista med avsändare som saknar kvitto under given
        månad (format: '2024-03'). Kollar 'senders' om angiven, annars
        alla kända avsändare.
        """
        known = senders if senders is not None else self.storage.get_known_senders()
        if not known:
            return []

        receipts = self.storage.get_receipts()
        month_receipts = [
            r for r in receipts
            if (r.get("date") or "")[:7] == month
        ]

        # Vilka kända avsändare finns representerade?
        seen = set()
        for r in month_receipts:
            sender_lower = (r.get("sender") or "").lower()
            for k in known:
                match_keys = self.storage.get_sender_match_keys(k)
                if self._matches(sender_lower, match_keys):
                    seen.add(k)

        # Hitta avsändare som BORDE ha skickat men inte gjort det
        missing = []
        for k in known:
            if k not in seen:
                last_seen = "–"
                k_receipts = sorted(self._receipts_for(k),
                                     key=lambda x: x.get("date", ""), reverse=True)
                if k_receipts:
                    last_seen = (k_receipts[0].get("date") or "")[:10]
                missing.append({
                    "sender":    k,
                    "last_seen": last_seen,
                })

        return missing

    def get_missing_summary(self, month: str) -> dict:
        """Returnerar sammanfattning för UI-visning."""
        missing = self.check_month(month)
        return {
            "count":   len(missing),
            "missing": missing,
            "month":   month,
        }

    def days_since_last_seen(self, sender_key: str):
        """Antal dagar sedan senaste kvittot från avsändaren, eller None om inget finns."""
        dates = []
        for r in self._receipts_for(sender_key):
            d = (r.get("date") or "")[:10]
            if d:
                try:
                    dates.append(datetime.strptime(d, "%Y-%m-%d"))
                except ValueError:
                    continue
        if not dates:
            return None
        return (datetime.now() - max(dates)).days

    def get_sender_cadence(self, sender_key: str) -> dict:
        """
        Analyserar hur ofta en känd avsändare skickar kvitton, baserat på
        mediantiden mellan kvitton. Returnerar t.ex. {"label": "Veckovis", "days": 7}.
        """
        dates = []
        for r in self._receipts_for(sender_key):
            d = (r.get("date") or "")[:10]
            if d:
                try:
                    dates.append(datetime.strptime(d, "%Y-%m-%d"))
                except ValueError:
                    continue

        if len(dates) < 2:
            return {"label": "Ny", "days": None}

        dates.sort()
        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        if not gaps:
            return {"label": "Ny", "days": None}

        median_gap = statistics.median(gaps)

        if median_gap <= 9:
            label = "Veckovis"
        elif median_gap <= 18:
            label = "Varannan vecka"
        elif median_gap <= 40:
            label = "Månadsvis"
        else:
            label = "Oregelbunden"

        return {"label": label, "days": round(median_gap)}

    def get_weekly_senders(self) -> list:
        """Returnerar kända avsändare som skickar kvitton ungefär varje vecka."""
        known = self.storage.get_known_senders()
        weekly = []
        for k in known:
            cadence = self.get_sender_cadence(k)
            if cadence["label"] == "Veckovis":
                weekly.append({"sender": k, **cadence})
        return weekly

    def get_sender_stats(self, sender_key: str) -> dict:
        """
        Fullständig statistik för en avsändarprofil: antal, först/senast sett,
        frekvens och vilka månader som saknas i historiken.
        """
        receipts = sorted(self._receipts_for(sender_key), key=lambda r: r.get("date", ""))
        months_present = sorted({
            (r.get("date") or "")[:7] for r in receipts if r.get("date")
        })

        missing_months = []
        if months_present:
            start = datetime.strptime(months_present[0], "%Y-%m")
            end   = datetime.now()
            cursor = start
            while cursor <= end:
                m = cursor.strftime("%Y-%m")
                if m not in months_present:
                    missing_months.append(m)
                cursor += relativedelta(months=1)

        return {
            "total":          len(receipts),
            "first_seen":     (receipts[0].get("date") or "")[:10] if receipts else "–",
            "last_seen":      (receipts[-1].get("date") or "")[:10] if receipts else "–",
            "cadence":        self.get_sender_cadence(sender_key),
            "months_present": months_present,
            "missing_months": missing_months,
        }
