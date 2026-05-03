# ─── INVENTURA ───────────────────────────────────────────────────────────────
# Dodaj te endpointe v main.py (na konec, pred zadnjo vrstico)

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT

INVENTURA_DIR = DATA_DIR / "inventura"
INVENTURA_DIR.mkdir(exist_ok=True, parents=True)


@app.post("/inventura-upload")
async def inventura_upload(file: UploadFile = File(...)):
    """Sprejme CSV izvoz, združi po SKU, vrne strukturiran seznam."""
    try:
        import csv
        from io import StringIO

        content = (await file.read()).decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(StringIO(content))

        rows = []
        for row in reader:
            norm = {k.strip().replace('\ufeff', ''): (v or '').strip() for k, v in row.items()}
            rows.append(norm)

        if not rows:
            return JSONResponse({"error": "Prazen CSV."}, status_code=400)

        sample = rows[0]
        keys = list(sample.keys())

        def find_col(*candidates):
            for c in candidates:
                for k in keys:
                    if c.lower() in k.lower():
                        return k
            return None

        sku_col   = find_col("sku", "SKU")
        naziv_col = find_col("naziv", "name", "Naziv")
        qty_col   = find_col("količina", "kolicina", "qty", "Količina")
        pos_col   = find_col("pozicija", "position", "Pozicija")
        opomba_col = find_col("opomba", "note", "Opomba")
        prodano_col = find_col("prodano", "sold", "Prodano")

        if not sku_col:
            return JSONResponse({"error": f"Ne najdem SKU stolpca. Najdeni: {keys}"}, status_code=400)

        # Združi po SKU
        sku_map = {}
        for row in rows:
            sku = (row.get(sku_col) or "").strip()
            if not sku:
                continue
            try:
                qty = int(float((row.get(qty_col) or "0").replace(",", "."))) if qty_col else 0
            except:
                qty = 0

            naziv = (row.get(naziv_col) or "").strip() if naziv_col else ""
            pozicija = (row.get(pos_col) or "").strip() if pos_col else ""
            opomba = (row.get(opomba_col) or "").strip() if opomba_col else ""
            try:
                prodano = int(float((row.get(prodano_col) or "0").replace(",", "."))) if prodano_col else 0
            except:
                prodano = 0

            if sku not in sku_map:
                sku_map[sku] = {
                    "sku": sku,
                    "naziv": naziv,
                    "kolicina": 0,
                    "pozicija": pozicija,
                    "opomba": opomba,
                    "prodano": prodano,
                }
            sku_map[sku]["kolicina"] += qty
            # Ohrani pozicijo / naziv če je nov zapis ima vrednost in original nima
            if not sku_map[sku]["pozicija"] and pozicija:
                sku_map[sku]["pozicija"] = pozicija
            if not sku_map[sku]["naziv"] and naziv:
                sku_map[sku]["naziv"] = naziv
            if prodano > sku_map[sku]["prodano"]:
                sku_map[sku]["prodano"] = prodano

        items = sorted(sku_map.values(), key=lambda x: (x["pozicija"] or "zzz", x["sku"]))

        return {
            "ok": True,
            "total_skus": len(items),
            "filename": file.filename,
            "items": items,
        }

    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/inventura-pdf")
async def inventura_pdf(data: dict):
    """Generira PDF inventurni list iz podanih postavk."""
    try:
        items = data.get("items", [])
        title_text = data.get("title", "Inventurni list")
        datum = data.get("datum", datetime.now().strftime("%d. %m. %Y"))

        if not items:
            return JSONResponse({"error": "Ni postavk."}, status_code=400)

        import io
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=1.5*cm, rightMargin=1.5*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )

        styles = getSampleStyleSheet()
        style_title = ParagraphStyle("title", fontSize=16, fontName="Helvetica-Bold",
                                     spaceAfter=4, alignment=TA_LEFT)
        style_sub = ParagraphStyle("sub", fontSize=9, fontName="Helvetica",
                                   textColor=colors.HexColor("#64748b"), spaceAfter=12)
        style_cell = ParagraphStyle("cell", fontSize=8, fontName="Helvetica",
                                    leading=11, wordWrap='LTR')
        style_sku = ParagraphStyle("sku", fontSize=8, fontName="Helvetica-Bold",
                                   leading=11)

        story = []

        # Header
        story.append(Paragraph(title_text, style_title))
        story.append(Paragraph(f"Datum: {datum}  |  Skupaj SKU-jev: {len(items)}", style_sub))

        # Tabela
        col_widths = [3.8*cm, 7.5*cm, 2.2*cm, 2.0*cm, 1.8*cm, 1.5*cm]
        header = ["SKU", "Naziv", "Pozicija", "Naroč. kol.", "Prodano", "Fizično ✓"]

        table_data = [header]
        for item in items:
            naziv_para = Paragraph(str(item.get("naziv") or "")[:120], style_cell)
            sku_para = Paragraph(str(item.get("sku") or ""), style_sku)
            row = [
                sku_para,
                naziv_para,
                str(item.get("pozicija") or "—"),
                str(item.get("kolicina") or 0),
                str(item.get("prodano") or 0),
                "",  # prazno polje za fizično preverjanje
            ]
            table_data.append(row)

        tbl = Table(table_data, colWidths=col_widths, repeatRows=1)

        # Barve — izmenjujoče vrstice
        row_styles = [
            # Header
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUND", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
            ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#1e293b")),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            # Količina + prodano — desno poravnano
            ("ALIGN", (3, 1), (4, -1), "CENTER"),
            ("ALIGN", (2, 1), (2, -1), "CENTER"),
            # Fizično polje — border za pisanje
            ("BOX", (5, 1), (5, -1), 0.8, colors.HexColor("#94a3b8")),
            ("BACKGROUND", (5, 1), (5, -1), colors.HexColor("#f0fdf4")),
        ]

        # Izmenjujoče barve vrstic
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                row_styles.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8fafc")))

        tbl.setStyle(TableStyle(row_styles))
        story.append(tbl)

        # Footer note
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph(
            "Navodilo: V stolpec 'Fizično ✓' vpišite dejansko zalogo na polici. "
            "Prazno = ni pregledano. ✓ = zalogo potrjeno. 0 = ni na zalogi.",
            ParagraphStyle("footer", fontSize=7, fontName="Helvetica",
                           textColor=colors.HexColor("#94a3b8"))
        ))

        doc.build(story)
        buf.seek(0)

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"inventura_{ts}.pdf"
        pdf_path = INVENTURA_DIR / filename
        pdf_path.write_bytes(buf.getvalue())

        from fastapi.responses import StreamingResponse
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)
