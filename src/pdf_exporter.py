"""Exporterar kvitton till välformaterade PDF-filer."""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from datetime import datetime


class PDFExporter:
    def export(self, receipt: dict, output_path: str):
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=20*mm,
            leftMargin=20*mm,
            topMargin=20*mm,
            bottomMargin=20*mm,
        )

        styles = getSampleStyleSheet()
        accent = colors.HexColor("#4F8EF7")
        dark   = colors.HexColor("#111318")
        muted  = colors.HexColor("#6B7280")

        title_style = ParagraphStyle(
            "Title", parent=styles["Heading1"],
            fontSize=22, textColor=accent,
            spaceAfter=4, fontName="Helvetica-Bold"
        )
        sub_style = ParagraphStyle(
            "Sub", parent=styles["Normal"],
            fontSize=10, textColor=muted,
            spaceAfter=2, fontName="Helvetica"
        )
        label_style = ParagraphStyle(
            "Label", parent=styles["Normal"],
            fontSize=10, textColor=muted,
            fontName="Helvetica-Bold"
        )
        value_style = ParagraphStyle(
            "Value", parent=styles["Normal"],
            fontSize=10, textColor=dark,
            fontName="Helvetica"
        )
        body_style = ParagraphStyle(
            "Body", parent=styles["Normal"],
            fontSize=9, textColor=colors.HexColor("#374151"),
            leading=14, fontName="Helvetica"
        )

        story = []

        # Header
        story.append(Paragraph("Kvitto", title_style))
        story.append(Paragraph(
            f"Exporterat {datetime.now().strftime('%d %B %Y, %H:%M')}",
            sub_style
        ))
        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width="100%", thickness=1, color=accent))
        story.append(Spacer(1, 6*mm))

        # Meta table
        source_icon = "Gmail" if receipt.get("source") == "gmail" else "Outlook"
        known = "Ja ✓" if receipt.get("known_sender") else "Ny avsändare"

        meta_data = [
            ["Avsändare",        receipt.get("sender", "–")],
            ["Ämne",             receipt.get("subject", "–")],
            ["Datum",            receipt.get("date", "–")[:19].replace("T", " ")],
            ["Källa",            source_icon],
            ["Känd avsändare",   known],
            ["Bilagor",          str(len(receipt.get("attachments", []))) + " st"],
        ]

        table_data = [
            [Paragraph(label, label_style), Paragraph(str(value), value_style)]
            for label, value in meta_data
        ]

        table = Table(table_data, colWidths=[45*mm, 120*mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F9FAFB")),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1),
             [colors.white, colors.HexColor("#F3F4F6")]),
            ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
            ("PADDING",    (0, 0), (-1, -1), 8),
            ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
        story.append(Spacer(1, 8*mm))

        # Attachments list
        attachments = receipt.get("attachments", [])
        if attachments:
            story.append(Paragraph("Bilagor", ParagraphStyle(
                "SH", parent=styles["Heading3"],
                fontSize=12, textColor=dark, fontName="Helvetica-Bold",
                spaceBefore=4, spaceAfter=4
            )))
            for att in attachments:
                story.append(Paragraph(
                    f"📎  {att.get('name', 'okänd')}  ({att.get('mimeType', '')})",
                    body_style
                ))
            story.append(Spacer(1, 6*mm))

        # Body preview
        body = receipt.get("body_preview", "")
        if body:
            story.append(HRFlowable(width="100%", thickness=0.5,
                                     color=colors.HexColor("#E5E7EB")))
            story.append(Spacer(1, 4*mm))
            story.append(Paragraph("Innehåll (utdrag)", ParagraphStyle(
                "SH2", parent=styles["Heading3"],
                fontSize=12, textColor=dark, fontName="Helvetica-Bold",
                spaceBefore=4, spaceAfter=4
            )))
            # Escapea specialtecken
            safe_body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(safe_body[:1200], body_style))

        # Footer
        story.append(Spacer(1, 10*mm))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                 color=colors.HexColor("#E5E7EB")))
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(
            "Genererat av Kvitto-appen",
            ParagraphStyle("Footer", parent=styles["Normal"],
                           fontSize=8, textColor=muted,
                           alignment=TA_CENTER, fontName="Helvetica")
        ))

        doc.build(story)
