"""Skapar en månadsrapport i PDF-format för revisorn."""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from datetime import datetime
import calendar


ACCENT   = colors.HexColor("#4F8EF7")
GREEN    = colors.HexColor("#2DC98E")
DARK     = colors.HexColor("#111318")
MUTED    = colors.HexColor("#6B7280")
LIGHT_BG = colors.HexColor("#F9FAFB")
ALT_BG   = colors.HexColor("#F3F4F6")
BORDER   = colors.HexColor("#E5E7EB")
WARNING  = colors.HexColor("#FBBF24")


def _style(name, **kwargs):
    base = getSampleStyleSheet()["Normal"]
    s = ParagraphStyle(name, parent=base, **kwargs)
    return s


class MonthlyReportExporter:
    def export(self, receipts: list, missing: list, month: str,
               company_name: str, output_path: str):
        """
        receipts    – lista med kvittodicts för månaden
        missing     – lista med avsändarnamn som saknas
        month       – "2024-03" format
        company_name– företagsnamn för rubriken
        output_path – var PDF:en sparas
        """
        year_int, month_int = map(int, month.split("-"))
        month_name_sv = _swedish_month(month_int)
        full_title = f"{month_name_sv} {year_int}"

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=20*mm, leftMargin=20*mm,
            topMargin=20*mm,   bottomMargin=20*mm,
        )

        story = []

        # ── Försättsblad ────────────────────────────────────────
        story.append(Spacer(1, 10*mm))

        story.append(Paragraph("⬡  Kvittosammanställning", _style(
            "Logo", fontSize=13, textColor=ACCENT, fontName="Helvetica-Bold"
        )))
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph(full_title, _style(
            "MainTitle", fontSize=32, textColor=DARK,
            fontName="Helvetica-Bold", spaceAfter=2
        )))
        story.append(Paragraph(company_name, _style(
            "Company", fontSize=14, textColor=MUTED, fontName="Helvetica"
        )))
        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width="100%", thickness=2, color=ACCENT))
        story.append(Spacer(1, 8*mm))

        # Sammanfattningskort
        sources = {}
        for r in receipts:
            s = r.get("source", "okänd")
            sources[s] = sources.get(s, 0) + 1

        summary_data = [
            ["Totalt kvitton", "Gmail", "Outlook", "iCloud", "Saknade"],
            [
                str(len(receipts)),
                str(sources.get("gmail", 0)),
                str(sources.get("outlook", 0)),
                str(sources.get("icloud", 0)),
                str(len(missing)),
            ]
        ]
        summary_table = Table(summary_data, colWidths=[35*mm]*5)
        summary_table.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0),  ACCENT),
            ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
            ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, 0),  9),
            ("BACKGROUND",  (0, 1), (-1, 1),  LIGHT_BG),
            ("FONTNAME",    (0, 1), (-1, 1),  "Helvetica-Bold"),
            ("FONTSIZE",    (0, 1), (-1, 1),  18),
            ("TEXTCOLOR",   (0, 1), (-1, 1),  DARK),
            ("TEXTCOLOR",   (4, 1), (4, 1),   WARNING),
            ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
            ("ROWHEIGHT",   (0, 0), (-1, 0),  8*mm),
            ("ROWHEIGHT",   (0, 1), (-1, 1),  14*mm),
            ("GRID",        (0, 0), (-1, -1), 0.5, BORDER),
            ("ROUNDEDCORNERS", [4]),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 8*mm))

        # ── Saknade kvitton-varning ──────────────────────────────
        if missing:
            story.append(KeepTogether([
                Paragraph("⚠  Saknade kvitton", _style(
                    "WarnHead", fontSize=13, textColor=WARNING,
                    fontName="Helvetica-Bold", spaceAfter=4
                )),
                Paragraph(
                    f"Följande {len(missing)} kända avsändare har inte "
                    f"skickat något kvitto under {full_title}. "
                    "Kontrollera om något saknas.",
                    _style("WarnBody", fontSize=10, textColor=MUTED,
                           fontName="Helvetica", spaceAfter=6)
                ),
            ]))

            warn_data = [["Avsändare", "Senast sedd"]]
            for m in missing:
                warn_data.append([m.get("sender", m), m.get("last_seen", "–")])

            warn_table = Table(warn_data, colWidths=[100*mm, 65*mm])
            warn_table.setStyle(TableStyle([
                ("BACKGROUND",  (0, 0), (-1, 0),  WARNING),
                ("TEXTCOLOR",   (0, 0), (-1, 0),  DARK),
                ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
                ("FONTSIZE",    (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_BG]),
                ("GRID",        (0, 0), (-1, -1), 0.5, BORDER),
                ("PADDING",     (0, 0), (-1, -1), 7),
            ]))
            story.append(warn_table)
            story.append(Spacer(1, 8*mm))

        # ── Kvittoförteckning ────────────────────────────────────
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
        story.append(Spacer(1, 5*mm))
        story.append(Paragraph("Kvitton", _style(
            "SH", fontSize=15, textColor=DARK,
            fontName="Helvetica-Bold", spaceAfter=6
        )))

        receipt_data = [["#", "Datum", "Avsändare", "Ämne", "Källa"]]
        for i, r in enumerate(receipts, 1):
            source_label = {"gmail": "Gmail", "outlook": "Outlook",
                            "icloud": "iCloud"}.get(r.get("source", ""), "–")
            date_str = (r.get("date") or "")[:10].replace("T", " ")
            sender   = (r.get("sender") or "")[:30]
            subject  = (r.get("subject") or "")[:42]
            receipt_data.append([str(i), date_str, sender, subject, source_label])

        col_w = [10*mm, 24*mm, 52*mm, 62*mm, 17*mm]
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


def _swedish_month(m: int) -> str:
    names = ["Januari","Februari","Mars","April","Maj","Juni",
             "Juli","Augusti","September","Oktober","November","December"]
    return names[m - 1]
