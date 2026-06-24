"""Skapar en månadsrapport i PDF-format för revisorn."""
import io
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    Image as RLImage
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from datetime import datetime
from PyPDF2 import PdfMerger
from PIL import Image


ACCENT   = colors.HexColor("#4F8EF7")
GREEN    = colors.HexColor("#2DC98E")
DARK     = colors.HexColor("#111318")
MUTED    = colors.HexColor("#6B7280")
ALT_BG   = colors.HexColor("#F3F4F6")
BORDER   = colors.HexColor("#E5E7EB")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}


def _style(name, **kwargs):
    base = getSampleStyleSheet()["Normal"]
    s = ParagraphStyle(name, parent=base, **kwargs)
    return s


class MonthlyReportExporter:
    def export(self, receipts: list, month: str,
               company_name: str, output_path: str, logo_path: str = None):
        """
        receipts    – lista med kvittodicts för månaden
        month       – "2024-03" format
        company_name– företagsnamn för rubriken
        output_path – var PDF:en sparas
        logo_path   – sökväg till företagslogga (valfri)
        """
        year_int, month_int = map(int, month.split("-"))
        month_name_sv = _swedish_month(month_int)
        full_title = f"{month_name_sv} {year_int}"

        main_buf = io.BytesIO()
        self._build_main_report(main_buf, receipts, full_title, company_name, logo_path)
        main_buf.seek(0)

        merger = PdfMerger()
        merger.append(main_buf)

        attachment_files = self._collect_attachment_files(receipts)
        if attachment_files:
            divider_buf = io.BytesIO()
            self._build_divider(divider_buf, full_title, len(attachment_files))
            divider_buf.seek(0)
            merger.append(divider_buf)

            for path in attachment_files:
                self._append_attachment(merger, path)

        with open(output_path, "wb") as f:
            merger.write(f)
        merger.close()

    def _collect_attachment_files(self, receipts: list) -> list:
        """Samlar sökvägar till bilagor (PDF/bild) som faktiskt finns på disk, i kvittoordning."""
        paths = []
        for r in receipts:
            for att in r.get("attachments", []):
                path = att.get("path")
                if path and os.path.exists(path):
                    ext = os.path.splitext(path)[1].lower()
                    if ext == ".pdf" or ext in IMAGE_EXTENSIONS:
                        paths.append(path)
        return paths

    def _append_attachment(self, merger: PdfMerger, path: str):
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".pdf":
                merger.append(path)
            elif ext in IMAGE_EXTENSIONS:
                img_buf = io.BytesIO()
                with Image.open(path) as img:
                    img.convert("RGB").save(img_buf, format="PDF")
                img_buf.seek(0)
                merger.append(img_buf)
        except Exception:
            pass  # Skadad/olämplig bilaga ska inte stoppa hela rapporten

    def _build_main_report(self, buf, receipts: list, full_title: str,
                            company_name: str, logo_path: str = None):
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            rightMargin=20*mm, leftMargin=20*mm,
            topMargin=20*mm,   bottomMargin=20*mm,
        )

        story = []

        # ── Försättsblad ────────────────────────────────────────
        story.append(Spacer(1, 10*mm))

        if logo_path and os.path.exists(logo_path):
            try:
                with Image.open(logo_path) as img:
                    w, h = img.size
                max_h = 18*mm
                max_w = 50*mm
                scale = min(max_h / h, max_w / w)
                story.append(RLImage(logo_path, width=w*scale, height=h*scale))
                story.append(Spacer(1, 4*mm))
            except Exception:
                pass

        story.append(Paragraph("⬡  Kvittosammanställning", _style(
            "Logo", fontSize=13, textColor=ACCENT, fontName="Helvetica-Bold"
        )))
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph(full_title, _style(
            "MainTitle", fontSize=32, leading=38, textColor=DARK,
            fontName="Helvetica-Bold", spaceAfter=2
        )))
        story.append(Paragraph(company_name, _style(
            "Company", fontSize=14, leading=18, textColor=MUTED, fontName="Helvetica"
        )))
        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width="100%", thickness=2, color=ACCENT))
        story.append(Spacer(1, 8*mm))

        # ── Kvittoförteckning ────────────────────────────────────
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
        story.append(Spacer(1, 5*mm))
        story.append(Paragraph("Kvitton", _style(
            "SH", fontSize=15, textColor=DARK,
            fontName="Helvetica-Bold", spaceAfter=6
        )))

        receipt_data = [["#", "Datum", "Avsändare", "Ämne", "Källa", "Bilaga"]]
        for i, r in enumerate(receipts, 1):
            source_label = {"gmail": "Gmail", "outlook": "Outlook",
                            "icloud": "iCloud"}.get(r.get("source", ""), "–")
            date_str = (r.get("date") or "")[:10].replace("T", " ")
            sender   = (r.get("sender") or "")[:30]
            subject  = (r.get("subject") or "")[:38]
            has_att  = any(
                a.get("path") and os.path.exists(a["path"])
                for a in r.get("attachments", [])
            )
            receipt_data.append(
                [str(i), date_str, sender, subject, source_label, "📎" if has_att else "–"])

        col_w = [9*mm, 24*mm, 50*mm, 58*mm, 15*mm, 13*mm]
        receipt_table = Table(receipt_data, colWidths=col_w, repeatRows=1)
        receipt_table.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  ACCENT),
            ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
            ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",       (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_BG]),
            ("GRID",           (0, 0), (-1, -1), 0.3, BORDER),
            ("PADDING",        (0, 0), (-1, -1), 5),
            ("VALIGN",         (0, 0), (-1, -1), "TOP"),
            ("ALIGN",          (5, 0), (5, -1),  "CENTER"),
        ]))
        story.append(receipt_table)

        # ── Sidfot ──────────────────────────────────────────────
        story.append(Spacer(1, 10*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(
            f"Genererat av Kvitto-appen  ·  {datetime.now().strftime('%d %B %Y, %H:%M')}",
            _style("Footer", fontSize=8, textColor=MUTED,
                   fontName="Helvetica", alignment=TA_CENTER)
        ))

        doc.build(story)

    def _build_divider(self, buf, full_title: str, attachment_count: int):
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            rightMargin=20*mm, leftMargin=20*mm,
            topMargin=20*mm,   bottomMargin=20*mm,
        )
        story = [
            Spacer(1, 60*mm),
            Paragraph("Bilagor", _style(
                "DividerTitle", fontSize=26, textColor=DARK,
                fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=6
            )),
            Paragraph(f"{attachment_count} originalkvitton för {full_title}", _style(
                "DividerSub", fontSize=12, textColor=MUTED,
                fontName="Helvetica", alignment=TA_CENTER
            )),
        ]
        doc.build(story)


def _swedish_month(m: int) -> str:
    names = ["Januari","Februari","Mars","April","Maj","Juni",
             "Juli","Augusti","September","Oktober","November","December"]
    return names[m - 1]
