"""Kvitto-appens huvudklass och UI – v2 med iCloud, månadsrapport och saknade-varning"""
import customtkinter as ctk
import threading
import json
import os
from datetime import datetime
from PIL import Image, ImageTk
from .gmail_client import GmailClient
from .outlook_client import OutlookClient
from .icloud_client import ICloudClient
from .receipt_detector import ReceiptDetector
from .storage import Storage
from .pdf_exporter import PDFExporter
from .monthly_report import MonthlyReportExporter
from .missing_checker import MissingChecker

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg":        "#111318",
    "surface":   "#1C1F27",
    "card":      "#252932",
    "border":    "#2E3340",
    "accent":    "#4F8EF7",
    "accent2":   "#2DC98E",
    "muted":     "#6B7280",
    "text":      "#F0F2F5",
    "text_dim":  "#9CA3AF",
    "danger":    "#F87171",
    "warning":   "#FBBF24",
}


class KvittoApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Kvitton")
        self.root.geometry("1160x740")
        self.root.configure(fg_color=COLORS["bg"])
        self.root.minsize(940, 620)
        self._set_icon()

        self.storage         = Storage()
        self.receipt_detector = ReceiptDetector(self.storage)
        self.pdf_exporter    = PDFExporter()
        self.report_exporter = MonthlyReportExporter()
        self.missing_checker = MissingChecker(self.storage)

        self.gmail_client   = GmailClient(self.storage)
        self.outlook_client = OutlookClient(self.storage)
        self.icloud_client  = ICloudClient(self.storage)

        self.all_receipts    = []
        self.selected_receipt = None
        self._scanning       = False

        self._build_ui()

    # ══════════════════════════════════════════════════════════════
    #  UI SETUP
    # ══════════════════════════════════════════════════════════════

    def _set_icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icon.png")
        try:
            # Sätt process- och menybalksnamn (syns vid hover i Dock)
            from Foundation import NSProcessInfo
            NSProcessInfo.processInfo().setProcessName_("Kvitto-appen")
        except Exception:
            pass
        if not os.path.exists(icon_path):
            return
        try:
            img = Image.open(icon_path)
            self._icon_photo = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, self._icon_photo)
            try:
                from AppKit import NSApp, NSImage
                ns_img = NSImage.alloc().initWithContentsOfFile_(icon_path)
                NSApp.setApplicationIconImage_(ns_img)
            except Exception:
                pass
        except Exception:
            pass

    def _build_ui(self):
        # ── Sidebar ──────────────────────────────────────────────
        self.sidebar = ctk.CTkFrame(self.root, width=228, fg_color=COLORS["surface"],
                                    corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", padx=20, pady=(28, 8))
        ctk.CTkLabel(logo_frame, text="⬡", font=("SF Pro Display", 28),
                     text_color=COLORS["accent"]).pack(side="left")
        ctk.CTkLabel(logo_frame, text=" Kvitton",
                     font=("SF Pro Display", 20, "bold"),
                     text_color=COLORS["text"]).pack(side="left")

        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLORS["border"]).pack(
            fill="x", padx=16, pady=12)

        self.nav_buttons = {}
        nav_items = [
            ("📥", "Kvitton",       self._show_receipts),
            ("🗑️", "Borttagna",     self._show_deleted),
            ("📋", "Månadsrapport", self._show_report),
            ("🔗", "Konton",        self._show_accounts),
            ("📊", "Statistik",     self._show_stats),
        ]
        for icon, label, cmd in nav_items:
            btn = self._nav_button(self.sidebar, icon, label, cmd)
            self.nav_buttons[label] = btn

        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLORS["border"]).pack(
            fill="x", padx=16, pady=12)

        self.scan_btn = ctk.CTkButton(
            self.sidebar, text="  Hämta kvitton",
            font=("SF Pro Display", 13, "bold"),
            fg_color=COLORS["accent"], hover_color="#3a72d8",
            height=44, corner_radius=10, command=self._start_scan)
        self.scan_btn.pack(fill="x", padx=16, pady=4)

        self.status_label = ctk.CTkLabel(
            self.sidebar, text="Klar", font=("SF Pro Display", 11),
            text_color=COLORS["muted"])
        self.status_label.pack(pady=6)

        # ── Main ────────────────────────────────────────────────
        self.main_frame = ctk.CTkFrame(self.root, fg_color=COLORS["bg"], corner_radius=0)
        self.main_frame.pack(side="left", fill="both", expand=True)

        self.pages = {}
        self._build_receipts_page()
        self._build_deleted_page()
        self._build_report_page()
        self._build_accounts_page()
        self._build_stats_page()

        self._show_receipts()

    def _nav_button(self, parent, icon, label, cmd):
        frame = ctk.CTkFrame(parent, fg_color="transparent", cursor="hand2")
        frame.pack(fill="x", padx=8, pady=2)

        def on_click():
            for f in self.nav_buttons.values():
                f.configure(fg_color="transparent")
            frame.configure(fg_color=COLORS["card"])
            cmd()

        for widget in [frame]:
            widget.bind("<Button-1>", lambda e: on_click())

        inner = ctk.CTkLabel(frame, text=f"{icon}  {label}",
                              font=("SF Pro Display", 13),
                              text_color=COLORS["text"], anchor="w")
        inner.pack(side="left", padx=14, pady=10)
        inner.bind("<Button-1>", lambda e: on_click())
        return frame

    # ══════════════════════════════════════════════════════════════
    #  PAGES
    # ══════════════════════════════════════════════════════════════

    # ── Kvitton ─────────────────────────────────────────────────

    def _build_receipts_page(self):
        page = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.pages["Kvitton"] = page

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(28, 16))
        ctk.CTkLabel(header, text="Kvitton",
                     font=("SF Pro Display", 26, "bold"),
                     text_color=COLORS["text"]).pack(side="left")
        ctk.CTkButton(
            header, text="Exportera alla  ↓",
            font=("SF Pro Display", 12), height=36,
            fg_color=COLORS["card"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            command=self._export_selected).pack(side="right")

        filter_row = ctk.CTkFrame(page, fg_color="transparent")
        filter_row.pack(fill="x", padx=28, pady=(0, 12))
        self.search_var = ctk.StringVar()
        ctk.CTkEntry(filter_row, placeholder_text="🔍  Sök avsändare eller ämne…",
                     textvariable=self.search_var,
                     font=("SF Pro Display", 12), height=36,
                     fg_color=COLORS["card"], border_color=COLORS["border"],
                     corner_radius=8).pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.search_var.trace("w", lambda *a: self._refresh_list())

        self.filter_var = ctk.StringVar(value="Alla")
        ctk.CTkOptionMenu(
            filter_row,
            values=["Alla", "Gmail", "Outlook", "iCloud", "Okänd avsändare"],
            variable=self.filter_var,
            font=("SF Pro Display", 12),
            fg_color=COLORS["card"], button_color=COLORS["card"],
            button_hover_color=COLORS["border"],
            dropdown_fg_color=COLORS["surface"],
            height=36, corner_radius=8,
            command=lambda v: self._refresh_list()).pack(side="left")

        split = ctk.CTkFrame(page, fg_color="transparent")
        split.pack(fill="both", expand=True, padx=28, pady=(0, 24))

        list_frame = ctk.CTkFrame(split, fg_color=COLORS["surface"],
                                   corner_radius=12, width=380)
        list_frame.pack(side="left", fill="y")
        list_frame.pack_propagate(False)
        self.receipt_list = ctk.CTkScrollableFrame(
            list_frame, fg_color="transparent", corner_radius=0)
        self.receipt_list.pack(fill="both", expand=True, padx=4, pady=4)

        self.preview_frame = ctk.CTkFrame(split, fg_color=COLORS["surface"],
                                           corner_radius=12)
        self.preview_frame.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self._show_empty_preview()

    # ── Borttagna ────────────────────────────────────────────────

    def _build_deleted_page(self):
        page = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.pages["Borttagna"] = page

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(28, 16))
        ctk.CTkLabel(header, text="Borttagna kvitton",
                     font=("SF Pro Display", 26, "bold"),
                     text_color=COLORS["text"]).pack(side="left")

        self.deleted_list = ctk.CTkScrollableFrame(
            page, fg_color=COLORS["surface"], corner_radius=12)
        self.deleted_list.pack(fill="both", expand=True, padx=28, pady=(0, 24))

    def _show_deleted(self):
        self._show_page("Borttagna")
        self.nav_buttons["Borttagna"].configure(fg_color=COLORS["card"])
        self._refresh_deleted_list()

    def _refresh_deleted_list(self):
        for w in self.deleted_list.winfo_children():
            w.destroy()

        deleted = self.storage.get_deleted_receipts()
        if not deleted:
            ctk.CTkLabel(self.deleted_list,
                         text="Inga borttagna kvitton.",
                         font=("SF Pro Display", 12),
                         text_color=COLORS["muted"]).pack(pady=40)
            return

        for r in deleted:
            self._deleted_row(r)

    def _deleted_row(self, receipt):
        card = ctk.CTkFrame(self.deleted_list, fg_color=COLORS["card"], corner_radius=8)
        card.pack(fill="x", pady=3, padx=2)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=10)

        icon_map = {"gmail": "📧", "outlook": "📨", "icloud": "☁️"}
        src_icon = icon_map.get(receipt.get("source", ""), "✉️")

        ctk.CTkLabel(row, text=f"{src_icon}  {receipt.get('sender', 'Okänd')}",
                     font=("SF Pro Display", 12, "bold"),
                     text_color=COLORS["muted"]).pack(side="left")

        def _restore(r=receipt):
            self.storage.restore_receipt(r.get("message_id", ""))
            self.storage.log_activity("↩️", f"Återställde: {r.get('subject','')[:40]}")
            card.destroy()

        ctk.CTkButton(row, text="Återställ", width=84, height=26, corner_radius=6,
                      fg_color=COLORS["accent"], hover_color="#3a72d8",
                      font=("SF Pro Display", 11),
                      command=_restore).pack(side="right")

        sub = ctk.CTkFrame(card, fg_color="transparent")
        sub.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(sub, text=receipt.get("subject", "")[:50],
                     font=("SF Pro Display", 11),
                     text_color=COLORS["text_dim"]).pack(side="left")
        ctk.CTkLabel(sub, text=receipt.get("date", "")[:10],
                     font=("SF Pro Display", 11),
                     text_color=COLORS["muted"]).pack(side="right")

    # ── Månadsrapport ────────────────────────────────────────────

    def _build_report_page(self):
        page = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        self.pages["Månadsrapport"] = page

        ctk.CTkLabel(page, text="Månadsrapport",
                     font=("SF Pro Display", 26, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", padx=28, pady=(28, 4))
        ctk.CTkLabel(page,
                     text="Generera en PDF-rapport med alla kvitton för månaden – klar att skicka till revisorn.",
                     font=("SF Pro Display", 12), text_color=COLORS["muted"]).pack(
            anchor="w", padx=28, pady=(0, 20))

        # Inställningar
        settings_card = ctk.CTkFrame(page, fg_color=COLORS["card"], corner_radius=12)
        settings_card.pack(fill="x", padx=28, pady=(0, 16))
        inner = ctk.CTkFrame(settings_card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=16)

        # Månad-väljare
        ctk.CTkLabel(inner, text="Månad", font=("SF Pro Display", 12),
                     text_color=COLORS["muted"]).pack(anchor="w")

        now = datetime.now()
        months = []
        for i in range(12):
            m = now.month - i
            y = now.year
            while m <= 0:
                m += 12
                y -= 1
            months.append(f"{y}-{m:02d}")

        self.report_month_var = ctk.StringVar(value=months[0])
        ctk.CTkOptionMenu(inner, values=months,
                          variable=self.report_month_var,
                          font=("SF Pro Display", 12),
                          fg_color=COLORS["surface"],
                          button_color=COLORS["surface"],
                          button_hover_color=COLORS["border"],
                          dropdown_fg_color=COLORS["surface"],
                          height=36, width=160, corner_radius=8).pack(
            anchor="w", pady=(4, 12))

        ctk.CTkLabel(inner, text="Företagsnamn (visas i rapporten)",
                     font=("SF Pro Display", 12),
                     text_color=COLORS["muted"]).pack(anchor="w")
        self.company_var = ctk.StringVar(
            value=self.storage.get_account("settings").get("company", ""))
        company_entry = ctk.CTkEntry(inner, textvariable=self.company_var,
                                      placeholder_text="t.ex. Anderssons Konsult AB",
                                      font=("SF Pro Display", 12), height=36,
                                      fg_color=COLORS["surface"],
                                      border_color=COLORS["border"], corner_radius=8)
        company_entry.pack(fill="x", pady=(4, 0))
        self.company_var.trace("w", lambda *a: self.storage.save_account(
            "settings", {"company": self.company_var.get()}))

        # Förhandsvisning av saknade
        self.missing_frame = ctk.CTkFrame(page, fg_color="transparent")
        self.missing_frame.pack(fill="x", padx=28, pady=(0, 16))

        # Knappar
        btn_row = ctk.CTkFrame(page, fg_color="transparent")
        btn_row.pack(fill="x", padx=28)
        ctk.CTkButton(btn_row, text="Förhandsgranska saknade kvitton",
                      font=("SF Pro Display", 12),
                      fg_color=COLORS["card"], hover_color=COLORS["border"],
                      border_width=1, border_color=COLORS["border"],
                      height=40, corner_radius=10,
                      command=self._preview_missing).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_row, text="  Skapa månadsrapport PDF",
                      font=("SF Pro Display", 13, "bold"),
                      fg_color=COLORS["accent"], hover_color="#3a72d8",
                      height=40, corner_radius=10,
                      command=self._generate_report).pack(side="left")

        self.report_status = ctk.CTkLabel(
            page, text="", font=("SF Pro Display", 12),
            text_color=COLORS["accent2"])
        self.report_status.pack(anchor="w", padx=28, pady=10)

    def _preview_missing(self):
        month = self.report_month_var.get()
        missing = self.missing_checker.check_month(month)

        for w in self.missing_frame.winfo_children():
            w.destroy()

        if not missing:
            ctk.CTkLabel(self.missing_frame,
                         text=f"✓  Inga saknade kvitton för {month}",
                         font=("SF Pro Display", 12),
                         text_color=COLORS["accent2"]).pack(anchor="w")
            return

        ctk.CTkLabel(self.missing_frame,
                     text=f"⚠  {len(missing)} avsändare saknas för {month}:",
                     font=("SF Pro Display", 12, "bold"),
                     text_color=COLORS["warning"]).pack(anchor="w", pady=(0, 6))

        for m in missing:
            row = ctk.CTkFrame(self.missing_frame, fg_color=COLORS["card"],
                                corner_radius=8)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=f"  {m['sender']}",
                         font=("SF Pro Display", 12),
                         text_color=COLORS["text"]).pack(side="left", padx=12, pady=8)
            ctk.CTkLabel(row, text=f"Senast: {m['last_seen']}  ",
                         font=("SF Pro Display", 11),
                         text_color=COLORS["muted"]).pack(side="right")

    def _generate_report(self):
        import tkinter.filedialog as fd
        month    = self.report_month_var.get()
        company  = self.company_var.get() or "Okänt företag"
        receipts = [r for r in self.storage.get_receipts()
                    if (r.get("date") or "")[:7] == month]
        missing  = self.missing_checker.check_month(month)

        path = fd.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=f"kvittorapport_{month}.pdf"
        )
        if not path:
            return

        try:
            self.report_exporter.export(receipts, missing, month, company, path)
            self.storage.log_activity("📋", f"Skapade rapport {month}")
            self.report_status.configure(
                text=f"✓  Rapport skapad med {len(receipts)} kvitton ({len(missing)} saknade)")
        except Exception as e:
            self.report_status.configure(
                text=f"Fel: {str(e)[:60]}", text_color=COLORS["danger"])

    # ── Konton ──────────────────────────────────────────────────

    def _build_accounts_page(self):
        page = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        self.pages["Konton"] = page

        ctk.CTkLabel(page, text="Konton",
                     font=("SF Pro Display", 26, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", padx=28, pady=(28, 20))

        oauth_accounts = [
            ("Gmail",   "📧", self.gmail_client,   "Gmail OAuth – console.cloud.google.com"),
            ("Outlook", "📨", self.outlook_client, "Microsoft OAuth – portal.azure.com"),
        ]

        for provider, icon, client, hint in oauth_accounts:
            card = ctk.CTkFrame(page, fg_color=COLORS["card"], corner_radius=12)
            card.pack(fill="x", padx=28, pady=8)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=20, pady=14)

            left = ctk.CTkFrame(inner, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True)

            ctk.CTkLabel(left, text=f"{icon}  {provider}",
                         font=("SF Pro Display", 14, "bold"),
                         text_color=COLORS["text"]).pack(anchor="w")
            ctk.CTkLabel(left, text=hint, font=("SF Pro Display", 10),
                         text_color=COLORS["muted"]).pack(anchor="w")

            status_lbl = ctk.CTkLabel(left,
                text="✓  " + client.get_email() if client.is_connected() else "Ej ansluten",
                font=("SF Pro Display", 11),
                text_color=COLORS["accent2"] if client.is_connected() else COLORS["muted"])
            status_lbl.pack(anchor="w", pady=(4, 0))

            btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
            btn_frame.pack(side="right")

            def make_connect(c=client, lbl=status_lbl, p=provider):
                def connect():
                    self._set_status(f"Ansluter {p}…")
                    threading.Thread(
                        target=self._connect_account,
                        args=(c, lbl, p), daemon=True).start()
                return connect

            def make_disconnect(c=client, lbl=status_lbl):
                def disconnect():
                    c.disconnect()
                    lbl.configure(text="Ej ansluten", text_color=COLORS["muted"])
                return disconnect

            ctk.CTkButton(btn_frame, text="Anslut",
                          font=("SF Pro Display", 12),
                          fg_color=COLORS["accent"], hover_color="#3a72d8",
                          height=32, width=88, corner_radius=8,
                          command=make_connect()).pack(side="left", padx=4)
            ctk.CTkButton(btn_frame, text="Koppla bort",
                          font=("SF Pro Display", 12),
                          fg_color=COLORS["card"], hover_color=COLORS["border"],
                          border_width=1, border_color=COLORS["border"],
                          text_color=COLORS["muted"],
                          height=32, width=104, corner_radius=8,
                          command=make_disconnect()).pack(side="left", padx=4)

        # ── iCloud – formulär direkt i appen ────────────────────
        self._build_icloud_card(page)

        # Kända avsändare
        ctk.CTkLabel(page, text="Kända avsändare",
                     font=("SF Pro Display", 16, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", padx=28, pady=(28, 4))
        ctk.CTkLabel(page,
                     text="Appen lär sig vilka som brukar skicka kvitton och varnar om de uteblir.",
                     font=("SF Pro Display", 12),
                     text_color=COLORS["muted"]).pack(anchor="w", padx=28)

        self.senders_frame = ctk.CTkScrollableFrame(
            page, fg_color=COLORS["surface"], corner_radius=12, height=180)
        self.senders_frame.pack(fill="x", padx=28, pady=12)
        self._refresh_senders()

    def _build_icloud_card(self, parent):
        saved = self.storage.get_account("icloud")

        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=12)
        card.pack(fill="x", padx=28, pady=8)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=14)

        # Rubrik + status
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text="☁️  iCloud",
                     font=("SF Pro Display", 14, "bold"),
                     text_color=COLORS["text"]).pack(side="left")
        self._icloud_status_lbl = ctk.CTkLabel(
            top,
            text="✓  " + self.icloud_client.get_email() if self.icloud_client.is_connected() else "Ej ansluten",
            font=("SF Pro Display", 11),
            text_color=COLORS["accent2"] if self.icloud_client.is_connected() else COLORS["muted"])
        self._icloud_status_lbl.pack(side="right")

        ctk.CTkLabel(inner, text="IMAP med app-lösenord – appleid.apple.com",
                     font=("SF Pro Display", 10),
                     text_color=COLORS["muted"]).pack(anchor="w", pady=(0, 10))

        # Fält
        fields_frame = ctk.CTkFrame(inner, fg_color="transparent")
        fields_frame.pack(fill="x")
        fields_frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(fields_frame, text="iCloud-epost",
                     font=("SF Pro Display", 12), text_color=COLORS["muted"],
                     anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
        self._icloud_email_var = ctk.StringVar(value=saved.get("email", ""))
        ctk.CTkEntry(fields_frame, textvariable=self._icloud_email_var,
                     placeholder_text="din@icloud.com",
                     font=("SF Pro Display", 12), height=34,
                     fg_color=COLORS["surface"], border_color=COLORS["border"],
                     corner_radius=8).grid(row=0, column=1, sticky="ew", pady=4)

        ctk.CTkLabel(fields_frame, text="App-lösenord",
                     font=("SF Pro Display", 12), text_color=COLORS["muted"],
                     anchor="w").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        self._icloud_pw_var = ctk.StringVar(value=saved.get("app_password", ""))
        ctk.CTkEntry(fields_frame, textvariable=self._icloud_pw_var,
                     placeholder_text="xxxx-xxxx-xxxx-xxxx",
                     show="•",
                     font=("SF Pro Display", 12), height=34,
                     fg_color=COLORS["surface"], border_color=COLORS["border"],
                     corner_radius=8).grid(row=1, column=1, sticky="ew", pady=4)

        # Knappar
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(btn_row, text="Anslut",
                      font=("SF Pro Display", 12),
                      fg_color=COLORS["accent"], hover_color="#3a72d8",
                      height=32, width=88, corner_radius=8,
                      command=self._connect_icloud).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Koppla bort",
                      font=("SF Pro Display", 12),
                      fg_color=COLORS["card"], hover_color=COLORS["border"],
                      border_width=1, border_color=COLORS["border"],
                      text_color=COLORS["muted"],
                      height=32, width=104, corner_radius=8,
                      command=self._disconnect_icloud).pack(side="left")

    def _connect_icloud(self):
        email = self._icloud_email_var.get().strip()
        password = self._icloud_pw_var.get().strip()
        if not email or not password:
            self._icloud_status_lbl.configure(
                text="Fyll i e-post och app-lösenord", text_color=COLORS["danger"])
            return
        self._set_status("Ansluter iCloud…")
        self._icloud_status_lbl.configure(text="Ansluter…", text_color=COLORS["muted"])
        threading.Thread(
            target=self._connect_icloud_worker,
            args=(email, password), daemon=True).start()

    def _connect_icloud_worker(self, email, password):
        try:
            addr = self.icloud_client.connect(email=email, password=password)
            self.root.after(0, lambda: self._icloud_status_lbl.configure(
                text=f"✓  {addr}", text_color=COLORS["accent2"]))
            self.storage.log_activity("🔗", f"Anslöt iCloud: {addr}")
            self._set_status("✓ Anslöt iCloud")
        except Exception as e:
            err = str(e)[:50]
            self.root.after(0, lambda: self._icloud_status_lbl.configure(
                text=f"Fel: {err}", text_color=COLORS["danger"]))
            self._set_status("Fel vid anslutning")

    def _disconnect_icloud(self):
        self.icloud_client.disconnect()
        self._icloud_status_lbl.configure(text="Ej ansluten", text_color=COLORS["muted"])

    # ── Statistik ────────────────────────────────────────────────

    def _build_stats_page(self):
        page = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        self.pages["Statistik"] = page

        ctk.CTkLabel(page, text="Statistik",
                     font=("SF Pro Display", 26, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", padx=28, pady=(28, 20))

        stats = self.storage.get_stats()
        missing_now = self.missing_checker.check_month(
            datetime.now().strftime("%Y-%m"))

        cards = [
            ("Totalt kvitton",     str(stats.get("total", 0)),          COLORS["accent"]),
            ("Denna månaden",      str(stats.get("this_month", 0)),      COLORS["accent2"]),
            ("Saknade denna mån.", str(len(missing_now)),                COLORS["warning"]),
            ("Kända avsändare",   str(stats.get("known_senders", 0)),   COLORS["muted"]),
        ]
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", padx=28)
        for label, value, color in cards:
            card = ctk.CTkFrame(row, fg_color=COLORS["card"], corner_radius=12)
            card.pack(side="left", expand=True, fill="x", padx=(0, 10))
            ctk.CTkLabel(card, text=value,
                         font=("SF Pro Display", 32, "bold"),
                         text_color=color).pack(padx=20, pady=(18, 4))
            ctk.CTkLabel(card, text=label,
                         font=("SF Pro Display", 11),
                         text_color=COLORS["muted"]).pack(pady=(0, 18))

        # Veckovisa avsändare
        weekly = self.missing_checker.get_weekly_senders()
        ctk.CTkLabel(page, text="Veckovisa avsändare",
                     font=("SF Pro Display", 16, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", padx=28, pady=(28, 4))
        ctk.CTkLabel(page,
                     text="Kända avsändare som skickar kvitton ungefär en gång i veckan.",
                     font=("SF Pro Display", 12),
                     text_color=COLORS["muted"]).pack(anchor="w", padx=28)

        weekly_frame = ctk.CTkFrame(page, fg_color=COLORS["surface"], corner_radius=12)
        weekly_frame.pack(fill="x", padx=28, pady=12)
        if not weekly:
            ctk.CTkLabel(weekly_frame, text="Inga veckovisa avsändare ännu.",
                         font=("SF Pro Display", 12),
                         text_color=COLORS["muted"]).pack(pady=16)
        else:
            for w in weekly:
                row = ctk.CTkFrame(weekly_frame, fg_color="transparent")
                row.pack(fill="x", padx=16, pady=6)
                ctk.CTkLabel(row, text=f"●  {w['sender']}",
                             font=("SF Pro Display", 12),
                             text_color=COLORS["accent2"]).pack(side="left")
                ctk.CTkLabel(row, text=f"var {w['days']}:e dag",
                             font=("SF Pro Display", 11),
                             text_color=COLORS["muted"]).pack(side="right")

        ctk.CTkLabel(page, text="Senaste aktivitet",
                     font=("SF Pro Display", 16, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", padx=28, pady=(28, 8))

        activity_frame = ctk.CTkScrollableFrame(
            page, fg_color=COLORS["surface"], corner_radius=12, height=280)
        activity_frame.pack(fill="x", padx=28)

        for entry in self.storage.get_recent_activity(30):
            has_ids = bool(entry.get("message_ids"))
            r = ctk.CTkFrame(activity_frame, fg_color="transparent",
                              cursor="hand2" if has_ids else "")
            r.pack(fill="x", padx=12, pady=4)
            icon_lbl = ctk.CTkLabel(r, text=entry["icon"],
                         font=("SF Pro Display", 14))
            icon_lbl.pack(side="left")
            text_lbl = ctk.CTkLabel(r, text=entry["text"],
                         font=("SF Pro Display", 12),
                         text_color=COLORS["accent"] if has_ids else COLORS["text_dim"])
            text_lbl.pack(side="left", padx=8)
            ctk.CTkLabel(r, text=entry["time"],
                         font=("SF Pro Display", 11),
                         text_color=COLORS["muted"]).pack(side="right")

            if has_ids:
                def make_open(ids=entry["message_ids"]):
                    def _open():
                        self._show_activity_receipts(ids)
                    return _open
                for w in (r, icon_lbl, text_lbl):
                    w.bind("<Button-1>", lambda e, f=make_open(): f())

    # ══════════════════════════════════════════════════════════════
    #  NAVIGATION
    # ══════════════════════════════════════════════════════════════

    def _show_page(self, name):
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    def _show_receipts(self):
        self._show_page("Kvitton")
        self._refresh_list()
        self.nav_buttons["Kvitton"].configure(fg_color=COLORS["card"])

    def _show_report(self):
        self._show_page("Månadsrapport")
        self.nav_buttons["Månadsrapport"].configure(fg_color=COLORS["card"])

    def _show_accounts(self):
        self._show_page("Konton")
        self.nav_buttons["Konton"].configure(fg_color=COLORS["card"])

    def _show_stats(self):
        self.pages["Statistik"].destroy()
        self._build_stats_page()
        self._show_page("Statistik")
        self.nav_buttons["Statistik"].configure(fg_color=COLORS["card"])

    # ══════════════════════════════════════════════════════════════
    #  RECEIPT LIST
    # ══════════════════════════════════════════════════════════════

    def _refresh_list(self):
        for w in self.receipt_list.winfo_children():
            w.destroy()

        query  = self.search_var.get().lower()
        source = self.filter_var.get()

        receipts = self.storage.get_receipts()
        filtered = []
        for r in receipts:
            if query and query not in r.get("sender","").lower() \
                    and query not in r.get("subject","").lower():
                continue
            if source == "Gmail"   and r.get("source") != "gmail":   continue
            if source == "Outlook" and r.get("source") != "outlook": continue
            if source == "iCloud"  and r.get("source") != "icloud":  continue
            if source == "Okänd avsändare" and r.get("known_sender"): continue
            filtered.append(r)

        self.all_receipts = filtered

        if not filtered:
            ctk.CTkLabel(self.receipt_list,
                         text="Inga kvitton hittades.\nTryck på 'Hämta kvitton' för att söka.",
                         font=("SF Pro Display", 12), text_color=COLORS["muted"],
                         justify="center").pack(pady=40)
            return

        for r in filtered:
            self._receipt_row(r)

    def _receipt_row(self, receipt):
        is_known = receipt.get("known_sender", False)
        card = ctk.CTkFrame(self.receipt_list, fg_color=COLORS["card"],
                             corner_radius=8, cursor="hand2")
        card.pack(fill="x", pady=3, padx=2)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 2))

        icon_map = {"gmail": "📧", "outlook": "📨", "icloud": "☁️"}
        src_icon = icon_map.get(receipt.get("source", ""), "✉️")
        dot_col  = COLORS["accent2"] if is_known else COLORS["muted"]

        ctk.CTkLabel(top, text=f"{src_icon}  {receipt.get('sender','Okänd')}",
                     font=("SF Pro Display", 12, "bold"),
                     text_color=COLORS["text"]).pack(side="left")

        def _delete(r=receipt):
            self.storage.delete_receipt(r.get("message_id", ""))
            self.storage.log_activity("🗑️", f"Tog bort: {r.get('subject','')[:40]}")
            card.destroy()
            if self.selected_receipt and self.selected_receipt.get("message_id") == r.get("message_id"):
                self.selected_receipt = None
                self._show_empty_preview()

        ctk.CTkButton(top, text="✕", width=24, height=24, corner_radius=6,
                      fg_color="transparent", hover_color=COLORS["danger"],
                      text_color=COLORS["muted"], font=("SF Pro Display", 12),
                      command=_delete).pack(side="right", padx=(4, 0))
        ctk.CTkLabel(top, text="●" if is_known else "○",
                     font=("SF Pro Display", 10),
                     text_color=dot_col).pack(side="right")

        bot = ctk.CTkFrame(card, fg_color="transparent")
        bot.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(bot, text=receipt.get("subject","")[:45],
                     font=("SF Pro Display", 11),
                     text_color=COLORS["text_dim"]).pack(side="left")
        ctk.CTkLabel(bot, text=(receipt.get("date","")[:10]),
                     font=("SF Pro Display", 11),
                     text_color=COLORS["muted"]).pack(side="right")

        def on_click(r=receipt):
            self._show_preview(r)

        for w in [card, top, bot] + list(bot.winfo_children()):
            w.bind("<Button-1>", lambda e, r=receipt: on_click(r))

    # ══════════════════════════════════════════════════════════════
    #  PREVIEW
    # ══════════════════════════════════════════════════════════════

    def _show_empty_preview(self):
        for w in self.preview_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.preview_frame,
                     text="Välj ett kvitto för att förhandsgranska",
                     font=("SF Pro Display", 13),
                     text_color=COLORS["muted"]).pack(expand=True)

    def _show_preview(self, receipt):
        for w in self.preview_frame.winfo_children():
            w.destroy()

        header = ctk.CTkFrame(self.preview_frame, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 12))
        ctk.CTkLabel(header, text=receipt.get("sender","Okänd"),
                     font=("SF Pro Display", 15, "bold"),
                     text_color=COLORS["text"]).pack(side="left")
        ctk.CTkButton(header, text="Spara PDF",
                      font=("SF Pro Display", 12),
                      fg_color=COLORS["accent2"], hover_color="#22a373",
                      text_color="#000", height=32, width=100, corner_radius=8,
                      command=lambda: self._save_receipt_pdf(receipt)).pack(side="right")

        ctk.CTkFrame(self.preview_frame, height=1,
                     fg_color=COLORS["border"]).pack(fill="x", padx=20)

        meta = ctk.CTkScrollableFrame(self.preview_frame, fg_color="transparent")
        meta.pack(fill="both", expand=True, padx=20, pady=12)

        src_label = {"gmail":"Gmail","outlook":"Outlook","icloud":"iCloud"}.get(
            receipt.get("source",""), "–")
        fields = [
            ("Avsändare",       receipt.get("sender","–")),
            ("Ämne",            receipt.get("subject","–")),
            ("Datum",           (receipt.get("date","–") or "–")[:19].replace("T"," ")),
            ("Källa",           src_label),
            ("Känd avsändare",  "Ja ✓" if receipt.get("known_sender") else "Ny avsändare"),
            ("Bilagor",         str(len(receipt.get("attachments",[]))) + " st"),
        ]
        for label, value in fields:
            row = ctk.CTkFrame(meta, fg_color=COLORS["card"], corner_radius=8)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=label, font=("SF Pro Display", 11),
                         text_color=COLORS["muted"], width=120, anchor="w").pack(
                side="left", padx=12, pady=8)
            ctk.CTkLabel(row, text=str(value), font=("SF Pro Display", 12),
                         text_color=COLORS["text"], anchor="w").pack(side="left", padx=8)

        # Bilagor med öppna-knapp
        attachments = [a for a in receipt.get("attachments", []) if a.get("path")]
        if attachments:
            ctk.CTkLabel(meta, text="Bilagor",
                         font=("SF Pro Display", 13, "bold"),
                         text_color=COLORS["text"]).pack(anchor="w", pady=(14, 4))
            for att in attachments:
                att_row = ctk.CTkFrame(meta, fg_color=COLORS["card"], corner_radius=8)
                att_row.pack(fill="x", pady=2)
                ctk.CTkLabel(att_row, text=f"📎  {att['name']}",
                             font=("SF Pro Display", 11),
                             text_color=COLORS["text_dim"]).pack(side="left", padx=12, pady=6)
                def make_open(path=att["path"]):
                    def _open():
                        import subprocess
                        subprocess.Popen(["open", path])
                    return _open
                ctk.CTkButton(att_row, text="Öppna",
                              font=("SF Pro Display", 11),
                              fg_color=COLORS["accent"], hover_color="#3a72d8",
                              height=26, width=70, corner_radius=6,
                              command=make_open()).pack(side="right", padx=8, pady=4)

        ctk.CTkLabel(meta, text="Innehåll",
                     font=("SF Pro Display", 13, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", pady=(14, 6))
        body_box = ctk.CTkTextbox(meta, height=160, font=("SF Mono", 11),
                                   fg_color=COLORS["card"],
                                   border_color=COLORS["border"],
                                   border_width=1, corner_radius=8)
        body_box.pack(fill="x")
        body_box.insert("1.0", receipt.get("body_preview","Inget innehåll"))
        body_box.configure(state="disabled")

        if not receipt.get("known_sender"):
            ctk.CTkButton(meta, text="Markera som känd avsändare",
                          font=("SF Pro Display", 12),
                          fg_color=COLORS["card"],
                          border_width=1, border_color=COLORS["accent"],
                          text_color=COLORS["accent"],
                          hover_color=COLORS["border"],
                          height=36, corner_radius=8,
                          command=lambda: self._mark_known(receipt)).pack(
                fill="x", pady=(12, 0))

    # ══════════════════════════════════════════════════════════════
    #  ACTIONS
    # ══════════════════════════════════════════════════════════════

    def _start_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self.scan_btn.configure(text="  Hämtar…", state="disabled")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        new_count = 0
        new_ids = []
        clients = [
            ("Gmail",   self.gmail_client),
            ("Outlook", self.outlook_client),
            ("iCloud",  self.icloud_client),
        ]
        try:
            for name, client in clients:
                if not client.is_connected():
                    continue
                self._set_status(f"Hämtar mail från {name}…")
                emails = client.fetch_emails()
                self._set_status(f"Granskar {len(emails)} mail från {name}…")
                for em in emails:
                    if self.receipt_detector.is_receipt(em):
                        before = self.storage.get_stats()["total"]
                        self.storage.save_receipt(em)
                        if self.storage.get_stats()["total"] > before:
                            new_count += 1
                            if em.get("message_id"):
                                new_ids.append(em["message_id"])
                            self._set_status(f"Sparar kvitton… ({new_count} nya)")
                        msg_id = em.get("message_id")
                        if msg_id:
                            client.tag_as_receipt(msg_id)
            self.storage.log_activity("📥", f"Hittade {new_count} nya kvitton", message_ids=new_ids)
            self._set_status(f"✓ Klart – {new_count} nya kvitton")
        except Exception as e:
            self._set_status(f"Fel: {str(e)[:50]}")
        finally:
            self._scanning = False
            self.root.after(0, lambda: self.scan_btn.configure(
                text="  Hämta kvitton", state="normal"))
            self.root.after(0, self._refresh_list)

    def _connect_account(self, client, status_lbl, provider):
        try:
            email_addr = client.connect()
            self.root.after(0, lambda: status_lbl.configure(
                text=f"✓  {email_addr}", text_color=COLORS["accent2"]))
            self.storage.log_activity("🔗", f"Anslöt {provider}: {email_addr}")
            self._set_status(f"✓ Anslöt {provider}")
        except Exception as e:
            err = str(e)
            self.root.after(0, lambda: status_lbl.configure(
                text=f"Fel: {err[:40]}", text_color=COLORS["danger"]))
            self._set_status(f"Fel vid anslutning")

    def _mark_known(self, receipt):
        self.storage.add_known_sender(receipt["sender"])
        receipt["known_sender"] = True
        self._refresh_list()
        self._show_preview(receipt)
        self._refresh_senders()

    def _save_receipt_pdf(self, receipt):
        import tkinter.filedialog as fd
        path = fd.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=f"kvitto_{receipt.get('sender','okand')[:20]}_{(receipt.get('date',''))[:10]}.pdf"
        )
        if path:
            self.pdf_exporter.export(receipt, path)
            self.storage.log_activity("💾", f"Sparade {os.path.basename(path)}")
            self._set_status("✓ Sparad")

    def _export_selected(self):
        import tkinter.filedialog as fd
        folder = fd.askdirectory(title="Välj mapp att exportera till")
        if folder:
            for i, r in enumerate(self.all_receipts):
                fname = f"kvitto_{r.get('sender','okand')[:20]}_{(r.get('date',''))[:10]}_{i}.pdf"
                self.pdf_exporter.export(r, os.path.join(folder, fname))
            self.storage.log_activity("📦", f"Exporterade {len(self.all_receipts)} kvitton")
            self._set_status(f"✓ {len(self.all_receipts)} filer exporterade")

    def _refresh_senders(self):
        for w in self.senders_frame.winfo_children():
            w.destroy()
        senders = self.storage.get_known_senders()
        if not senders:
            ctk.CTkLabel(self.senders_frame,
                         text="Inga kända avsändare ännu.",
                         font=("SF Pro Display", 12),
                         text_color=COLORS["muted"]).pack(pady=16)
            return
        cadence_colors = {
            "Veckovis":       COLORS["accent2"],
            "Varannan vecka": COLORS["accent"],
            "Månadsvis":      COLORS["muted"],
            "Oregelbunden":   COLORS["warning"],
            "Ny":             COLORS["muted"],
        }

        for sender in senders:
            cadence = self.missing_checker.get_sender_cadence(sender)
            profile = self.storage.get_sender_profile(sender)

            row = ctk.CTkFrame(self.senders_frame, fg_color="transparent",
                                cursor="hand2")
            row.pack(fill="x", padx=12, pady=4)

            name_lbl = ctk.CTkLabel(row, text=f"●  {profile['display_name']}",
                         font=("SF Pro Display", 12),
                         text_color=COLORS["accent2"])
            name_lbl.pack(side="left")

            badge = ctk.CTkLabel(
                row, text=f"  {cadence['label']}  ",
                font=("SF Pro Display", 10, "bold"),
                fg_color=COLORS["card"],
                text_color=cadence_colors.get(cadence["label"], COLORS["muted"]),
                corner_radius=6)
            badge.pack(side="left", padx=8)

            def make_remove(s=sender):
                def remove():
                    self.storage.remove_known_sender(s)
                    self._refresh_senders()
                return remove

            ctk.CTkButton(row, text="Ta bort",
                          font=("SF Pro Display", 11),
                          fg_color="transparent",
                          text_color=COLORS["danger"],
                          hover_color=COLORS["card"],
                          height=24, width=70,
                          command=make_remove()).pack(side="right")

            def make_open(s=sender):
                def _open():
                    self._open_sender_profile(s)
                return _open
            for w in (row, name_lbl, badge):
                w.bind("<Button-1>", lambda e, f=make_open(): f())

    # ══════════════════════════════════════════════════════════════
    #  AVSÄNDARPROFIL
    # ══════════════════════════════════════════════════════════════

    def _open_sender_profile(self, sender_key):
        profile = self.storage.get_sender_profile(sender_key)
        stats = self.missing_checker.get_sender_stats(sender_key)

        win = ctk.CTkToplevel(self.root)
        win.title(profile["display_name"])
        win.geometry("480x640")
        win.configure(fg_color=COLORS["bg"])
        win.transient(self.root)
        win.grab_set()

        scroll = ctk.CTkScrollableFrame(win, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(scroll, text="Visningsnamn",
                     font=("SF Pro Display", 12), text_color=COLORS["muted"],
                     anchor="w").pack(fill="x")
        name_var = ctk.StringVar(value=profile["display_name"])
        name_entry = ctk.CTkEntry(scroll, textvariable=name_var,
                                   font=("SF Pro Display", 13), height=36,
                                   fg_color=COLORS["card"], border_color=COLORS["border"],
                                   corner_radius=8)
        name_entry.pack(fill="x", pady=(4, 4))

        def save_name():
            self.storage.set_sender_display_name(sender_key, name_var.get())
            win.title(name_var.get())
            self._refresh_senders()
            name_status.configure(text="✓ Sparat")

        ctk.CTkButton(scroll, text="Spara namn", font=("SF Pro Display", 11),
                      fg_color=COLORS["accent"], hover_color="#3a72d8",
                      height=30, corner_radius=8,
                      command=save_name).pack(anchor="w")
        name_status = ctk.CTkLabel(scroll, text="", font=("SF Pro Display", 11),
                                    text_color=COLORS["accent2"])
        name_status.pack(anchor="w", pady=(2, 4))

        ctk.CTkLabel(scroll, text=sender_key, font=("SF Pro Display", 10),
                     text_color=COLORS["muted"], anchor="w").pack(fill="x", pady=(0, 16))

        ctk.CTkFrame(scroll, height=1, fg_color=COLORS["border"]).pack(fill="x", pady=8)

        # Statistik
        ctk.CTkLabel(scroll, text="Statistik", font=("SF Pro Display", 14, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", pady=(8, 8))

        stat_rows = [
            ("Totalt antal kvitton", str(stats["total"])),
            ("Frekvens",             f"{stats['cadence']['label']}" +
                                      (f" (var {stats['cadence']['days']}:e dag)" if stats['cadence']['days'] else "")),
            ("Först sett",           stats["first_seen"]),
            ("Senast sett",          stats["last_seen"]),
        ]
        for label, value in stat_rows:
            r = ctk.CTkFrame(scroll, fg_color=COLORS["card"], corner_radius=8)
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=label, font=("SF Pro Display", 11),
                         text_color=COLORS["muted"], width=140, anchor="w").pack(
                side="left", padx=12, pady=8)
            ctk.CTkLabel(r, text=value, font=("SF Pro Display", 12),
                         text_color=COLORS["text"], anchor="w").pack(side="left")

        if stats["missing_months"]:
            ctk.CTkLabel(scroll, text=f"Saknade månader ({len(stats['missing_months'])})",
                         font=("SF Pro Display", 13, "bold"),
                         text_color=COLORS["warning"]).pack(anchor="w", pady=(14, 6))
            months_text = ", ".join(stats["missing_months"])
            ctk.CTkLabel(scroll, text=months_text, font=("SF Pro Display", 11),
                         text_color=COLORS["text_dim"], anchor="w",
                         wraplength=420, justify="left").pack(fill="x")
        elif stats["total"] > 0:
            ctk.CTkLabel(scroll, text="✓  Inga saknade månader",
                         font=("SF Pro Display", 12),
                         text_color=COLORS["accent2"]).pack(anchor="w", pady=(14, 0))

        ctk.CTkFrame(scroll, height=1, fg_color=COLORS["border"]).pack(fill="x", pady=16)

        # Sammanslagna alias
        ctk.CTkLabel(scroll, text="Sammanslagna avsändare",
                     font=("SF Pro Display", 14, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", pady=(0, 6))
        ctk.CTkLabel(scroll,
                     text="Mail från dessa räknas som samma avsändare som ovan.",
                     font=("SF Pro Display", 11), text_color=COLORS["muted"],
                     anchor="w").pack(fill="x", pady=(0, 8))

        alias_frame = ctk.CTkFrame(scroll, fg_color=COLORS["surface"], corner_radius=8)
        alias_frame.pack(fill="x", pady=(0, 8))

        def refresh_aliases():
            for w in alias_frame.winfo_children():
                w.destroy()
            aliases = self.storage.get_sender_profile(sender_key)["aliases"]
            if not aliases:
                ctk.CTkLabel(alias_frame, text="Inga sammanslagna ännu.",
                             font=("SF Pro Display", 11),
                             text_color=COLORS["muted"]).pack(pady=10)
                return
            for a in aliases:
                ar = ctk.CTkFrame(alias_frame, fg_color="transparent")
                ar.pack(fill="x", padx=10, pady=4)
                ctk.CTkLabel(ar, text=a, font=("SF Pro Display", 11),
                             text_color=COLORS["text_dim"]).pack(side="left")

                def make_unmerge(alias=a):
                    def _unmerge():
                        self.storage.unmerge_alias(sender_key, alias)
                        refresh_aliases()
                        self._refresh_senders()
                    return _unmerge

                ctk.CTkButton(ar, text="Ta bort", font=("SF Pro Display", 10),
                              fg_color="transparent", text_color=COLORS["danger"],
                              hover_color=COLORS["card"], height=22, width=60,
                              command=make_unmerge()).pack(side="right")

        refresh_aliases()

        # Slå ihop med annan känd avsändare
        ctk.CTkLabel(scroll, text="Slå ihop med en annan avsändare",
                     font=("SF Pro Display", 12, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", pady=(10, 4))

        other_senders = [
            s for s in self.storage.get_known_senders()
            if self.storage._pkey(s) != self.storage._pkey(sender_key)
        ]
        if other_senders:
            merge_var = ctk.StringVar(value=other_senders[0])
            merge_row = ctk.CTkFrame(scroll, fg_color="transparent")
            merge_row.pack(fill="x", pady=(0, 8))
            ctk.CTkOptionMenu(merge_row, values=other_senders, variable=merge_var,
                               font=("SF Pro Display", 11),
                               fg_color=COLORS["card"], button_color=COLORS["card"],
                               button_hover_color=COLORS["border"],
                               dropdown_fg_color=COLORS["surface"],
                               height=32, corner_radius=8).pack(side="left",
                                                                 fill="x", expand=True, padx=(0, 8))

            def do_merge():
                self.storage.merge_sender(sender_key, merge_var.get())
                refresh_aliases()
                self._refresh_senders()
                other = [s for s in self.storage.get_known_senders()
                         if self.storage._pkey(s) != self.storage._pkey(sender_key)]
                merge_var.set(other[0] if other else "")

            ctk.CTkButton(merge_row, text="Slå ihop", font=("SF Pro Display", 11),
                          fg_color=COLORS["accent"], hover_color="#3a72d8",
                          height=32, width=90, corner_radius=8,
                          command=do_merge).pack(side="left")
        else:
            ctk.CTkLabel(scroll, text="Inga andra kända avsändare att slå ihop med.",
                         font=("SF Pro Display", 11),
                         text_color=COLORS["muted"]).pack(anchor="w")

        ctk.CTkButton(scroll, text="Stäng", font=("SF Pro Display", 12),
                      fg_color=COLORS["card"], hover_color=COLORS["border"],
                      border_width=1, border_color=COLORS["border"],
                      height=34, corner_radius=8,
                      command=win.destroy).pack(fill="x", pady=(20, 0))

    def _show_activity_receipts(self, message_ids):
        receipts = self.storage.get_receipts_by_ids(message_ids)

        win = ctk.CTkToplevel(self.root)
        win.title(f"{len(receipts)} kvitton hittade")
        win.geometry("460x560")
        win.configure(fg_color=COLORS["bg"])
        win.transient(self.root)
        win.grab_set()

        ctk.CTkLabel(win, text=f"{len(receipts)} kvitton hittade",
                     font=("SF Pro Display", 16, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w", padx=20, pady=(20, 12))

        if not receipts:
            ctk.CTkLabel(win, text="Kvittona finns inte längre (kan ha tagits bort).",
                         font=("SF Pro Display", 12),
                         text_color=COLORS["muted"]).pack(padx=20, pady=20)
            return

        list_frame = ctk.CTkScrollableFrame(win, fg_color=COLORS["surface"], corner_radius=12)
        list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        icon_map = {"gmail": "📧", "outlook": "📨", "icloud": "☁️"}
        for r in receipts:
            card = ctk.CTkFrame(list_frame, fg_color=COLORS["card"], corner_radius=8,
                                 cursor="hand2")
            card.pack(fill="x", pady=3, padx=2)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 2))
            src_icon = icon_map.get(r.get("source", ""), "✉️")
            ctk.CTkLabel(top, text=f"{src_icon}  {r.get('sender','Okänd')}",
                         font=("SF Pro Display", 12, "bold"),
                         text_color=COLORS["text"]).pack(side="left")

            bot = ctk.CTkFrame(card, fg_color="transparent")
            bot.pack(fill="x", padx=12, pady=(0, 10))
            ctk.CTkLabel(bot, text=r.get("subject", "")[:45],
                         font=("SF Pro Display", 11),
                         text_color=COLORS["text_dim"]).pack(side="left")
            ctk.CTkLabel(bot, text=(r.get("date", "") or "")[:10],
                         font=("SF Pro Display", 11),
                         text_color=COLORS["muted"]).pack(side="right")

            def make_view(receipt=r):
                def _view():
                    win.destroy()
                    self._show_receipts()
                    self._show_preview(receipt)
                return _view
            for w in [card, top, bot] + list(top.winfo_children()) + list(bot.winfo_children()):
                w.bind("<Button-1>", lambda e, f=make_view(): f())

    def _set_status(self, msg):
        self.root.after(0, lambda: self.status_label.configure(text=msg))

    def run(self):
        self.root.mainloop()
