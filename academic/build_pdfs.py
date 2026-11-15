"""Gera PDFs simples e legíveis usando apenas a biblioteca padrão."""

from pathlib import Path
import textwrap


def pdf_from_markdown(source: Path, target: Path) -> None:
    linhas = []
    for raw in source.read_text(encoding="utf-8").splitlines():
        texto = raw.replace("**", "").replace("`", "")
        if texto.startswith("#"):
            texto = texto.lstrip("# ").upper()
        if texto.startswith("|"):
            texto = texto.replace("|", "  ")
        linhas.extend(textwrap.wrap(texto, width=92) or [""])

    paginas = [linhas[i : i + 52] for i in range(0, len(linhas), 52)] or [[""]]
    objetos = []
    paginas_obj = []
    for pagina in paginas:
        comandos = ["BT", "/F1 10 Tf", "50 790 Td"]
        for linha in pagina:
            seguro = linha.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            comandos.append(f"({seguro}) Tj")
            comandos.append("0 -14 Td")
        comandos.append("ET")
        stream = "\n".join(comandos).encode("latin-1", "replace")
        objetos.append(stream)

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    def obj(numero, conteudo):
        offsets.append(len(pdf))
        pdf.extend(f"{numero} 0 obj\n".encode())
        pdf.extend(conteudo)
        pdf.extend(b"\nendobj\n")

    obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{4 + i * 2} 0 R" for i in range(len(objetos)))
    obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {len(objetos)} >>".encode())
    obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, stream in enumerate(objetos):
        page_num = 4 + i * 2
        content_num = page_num + 1
        obj(page_num, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>".encode())
        obj(content_num, f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")

    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    target.write_bytes(pdf)


if __name__ == "__main__":
    base = Path(__file__).parent
    pdf_from_markdown(base / "PRODUTO_FINAL.md", base / "Frequencia_UFMG_Produto_Final.pdf")
    pdf_from_markdown(base / "VERIFICACAO.md", base / "Frequencia_UFMG_Verificacao.pdf")
