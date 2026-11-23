"""Diagramação reproduzível dos relatórios acadêmicos em A4."""

from math import atan2, cos, sin
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

BASE = Path(__file__).parent
VERSION = "PF-03-WEB"
INK = colors.HexColor("#243447")
BLUE = colors.HexColor("#284D6C")
ACCENT = colors.HexColor("#276F7B")
FAINT = colors.HexColor("#ECF3F5")
RULE = colors.HexColor("#C7D5DB")

pdfmetrics.registerFont(TTFont("Body", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("Bold", "C:/Windows/Fonts/arialbd.ttf"))
styles = getSampleStyleSheet()
for name, size, leading, font, color, before, after in [
    ("TitleX", 23, 29, "Bold", INK, 0, 12),
    ("SubtitleX", 12.5, 18, "Body", ACCENT, 0, 15),
    ("H1X", 15, 20, "Bold", INK, 0, 11),
    ("H2X", 11.5, 16, "Bold", BLUE, 11, 5),
    ("BodyX", 10.1, 15.2, "Body", INK, 0, 8),
    ("SmallX", 8.8, 12.4, "Body", INK, 0, 5),
    ("CellX", 8.6, 12.1, "Body", INK, 0, 0),
    ("HeadX", 8.6, 12.1, "Bold", colors.white, 0, 0),
]:
    styles.add(
        ParagraphStyle(
            name=name,
            fontName=font,
            fontSize=size,
            leading=leading,
            textColor=color,
            spaceBefore=before,
            spaceAfter=after,
        )
    )


def P(value, style="BodyX"):
    return Paragraph(str(value), styles[style])


def section(story, title, body=None):
    block = [P(title, "H2X")]
    if body:
        block.append(P(body))
    story.append(KeepTogether(block))


def page(story, label, title, intro=None):
    if story:
        story.append(PageBreak())
    story.extend([P(label.upper(), "SmallX"), P(title, "H1X")])
    if intro:
        story.append(P(intro))


def table(headers, rows, widths, *, dense=False):
    data = [[P(h, "HeadX") for h in headers]]
    data.extend([[P(x, "CellX") for x in row] for row in rows])
    result = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    padding = 2 if dense == "tight" else (4 if dense else 7)
    result.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, FAINT]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, -1), (-1, -1), 0.5, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
            ]
        )
    )
    return result


def footer(canvas, doc):
    canvas.saveState()
    width, height = doc.pagesize
    canvas.setStrokeColor(ACCENT)
    canvas.line(
        doc.leftMargin, height - 1.55 * cm, width - doc.rightMargin, height - 1.55 * cm
    )
    canvas.setFillColor(BLUE)
    canvas.setFont("Body", 8)
    canvas.drawString(doc.leftMargin, 1.12 * cm, "Frequência UFMG  |  APPOO 2026/2")
    canvas.drawRightString(width - doc.rightMargin, 1.12 * cm, f"Página {doc.page}")
    canvas.restoreState()


def build(filename, story, wide=False):
    size = landscape(A4) if wide else A4
    margin = 1.8 * cm if wide else 2 * cm
    SimpleDocTemplate(
        str(BASE / filename),
        pagesize=size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=2.05 * cm,
        bottomMargin=1.85 * cm,
        title="Frequência UFMG - " + filename,
        author="Eduardo Henrique Rodrigues Silva",
    ).build(story, onFirstPage=footer, onLaterPages=footer)


def class_diagram():
    """Diagrama vetorial, com cada rótulo em área própria e sem cruzamentos."""
    d = Drawing(470, 248)

    def box(x, y, w, h, title, detail):
        d.add(
            Rect(
                x,
                y,
                w,
                h,
                rx=4,
                ry=4,
                fillColor=FAINT,
                strokeColor=ACCENT,
                strokeWidth=1,
            )
        )
        d.add(Line(x, y + h - 27, x + w, y + h - 27, strokeColor=ACCENT))
        d.add(
            String(
                x + w / 2,
                y + h - 17,
                title,
                textAnchor="middle",
                fontName="Bold",
                fontSize=8.3,
                fillColor=INK,
            )
        )
        d.add(
            String(
                x + w / 2,
                y + h - 44,
                detail,
                textAnchor="middle",
                fontName="Body",
                fontSize=7.1,
                fillColor=INK,
            )
        )

    box(5, 170, 135, 60, "ControleAcademico", "criar / obter / apagar_tudo")
    box(170, 170, 135, 60, "Disciplina", "registrar / resumo")
    box(335, 170, 130, 60, "Registro", "dia / situação / faltas")
    box(5, 85, 135, 60, "Atividade", "data / tipo / título")
    box(170, 85, 135, 60, "PoliticaChamada", "calcular_faltas()")
    box(92, 5, 125, 51, "ChamadaUnica", "calcular_faltas()")
    box(258, 5, 125, 51, "ChamadaDupla", "calcular_faltas()")

    def association(a, b, c, e):
        """Desenha uma associação navegável com a ponta no destino."""
        d.add(Line(a, b, c, e, strokeColor=ACCENT, strokeWidth=1.2))
        angle = atan2(e - b, c - a)
        back_x = c - 6 * cos(angle)
        back_y = e - 6 * sin(angle)
        wing_x = 2.7 * sin(angle)
        wing_y = 2.7 * cos(angle)
        d.add(
            Polygon(
                [
                    c,
                    e,
                    back_x + wing_x,
                    back_y - wing_y,
                    back_x - wing_x,
                    back_y + wing_y,
                ],
                fillColor=ACCENT,
                strokeColor=ACCENT,
            )
        )

    for a, b, c, e in [
        (140, 200, 170, 200),
        (305, 200, 335, 200),
        (72, 170, 72, 145),
        (140, 145, 170, 170),
        (238, 170, 238, 145),
    ]:
        association(a, b, c, e)
    # A herança usa triângulo vazio apontado para a classe base.
    for a, b, c, e in [(155, 56, 238, 75), (320, 56, 238, 75)]:
        d.add(Line(a, b, c, e, strokeColor=ACCENT, strokeWidth=1.2))
    d.add(
        Polygon(
            [238, 85, 232, 75, 244, 75],
            fillColor=colors.white,
            strokeColor=ACCENT,
            strokeWidth=1.1,
        )
    )
    for x, y, label in [
        (149, 208, "0..*"),
        (313, 208, "1..*"),
        (79, 151, "0..*"),
        (244, 152, "1 política"),
    ]:
        d.add(String(x, y, label, fontName="Body", fontSize=7, fillColor=INK))
    return d


def sequence_diagram(steps, labels=None):
    """Uma linha por mensagem; alturas fixas deixam todos os textos legíveis."""
    d = Drawing(470, 37 + 18 * len(steps))
    labels = labels or ["Estudante", "Menu", "Controle", "Disciplina", "SQLite"]
    xs = [25 + i * 420 / (len(labels) - 1) for i in range(len(labels))]
    top = d.height - 17
    for x, label in zip(xs, labels, strict=True):
        d.add(
            String(
                x,
                top,
                label,
                textAnchor="middle",
                fontName="Bold",
                fontSize=8,
                fillColor=INK,
            )
        )
        d.add(Line(x, top - 9, x, 8, strokeColor=RULE, strokeWidth=0.8))
    for n, (source, target, label) in enumerate(steps):
        y = top - 18 * (n + 1)
        d.add(Line(xs[source], y, xs[target], y, strokeColor=ACCENT, strokeWidth=1.1))
        direction = 1 if target > source else -1
        tip = xs[target]
        d.add(
            Polygon(
                [tip, y, tip - direction * 5, y + 2.8, tip - direction * 5, y - 2.8],
                fillColor=ACCENT,
                strokeColor=ACCENT,
            )
        )
        d.add(
            String(
                (xs[source] + xs[target]) / 2,
                y + 5,
                label,
                textAnchor="middle",
                fontName="Body",
                fontSize=7.1,
                fillColor=INK,
            )
        )
    return d
