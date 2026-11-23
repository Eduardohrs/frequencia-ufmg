"""Extrai o ZIP final e testa exatamente os arquivos que serão enviados."""

import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile

import fitz

BASE = Path(__file__).parent
ARCHIVE = BASE / "Frequencia_UFMG_Entrega_Final.zip"
VERSION = "PF-03-WEB"


def conferir_pdf(path, paginas_minimas, identificadores):
    with fitz.open(path) as pdf:
        assert len(pdf) >= paginas_minimas, (path.name, len(pdf))
        texto = "\n".join(pagina.get_text() for pagina in pdf)
        for trecho in identificadores:
            assert trecho in texto, (path.name, trecho)
        for numero, pagina in enumerate(pdf, 1):
            assert len(pagina.get_text().strip()) > 300, (path.name, numero)
            assert f"Página {numero}" in pagina.get_text()


def main():
    obrigatorios = {
        "LEIA-ME.md",
        "demo/README.md",
        "demo/web.py",
        "demo/models.py",
        "demo/database.py",
        "demo/exemplo.py",
        "demo/frequencia.db",
        "demo/test_models.py",
        "demo/test_web.py",
        "demo/web/index.html",
        "demo/web/app.css",
        "demo/web/app.js",
        "evidencias/unittest.txt",
        "relatorio/Frequencia_UFMG_Produto_Final.pdf",
        "relatorio/Frequencia_UFMG_Verificacao.pdf",
    }
    with ZipFile(ARCHIVE) as arquivo:
        nomes = set(arquivo.namelist())
        assert obrigatorios <= nomes, f"Ausentes: {sorted(obrigatorios - nomes)}"
        assert "demo/main.py" not in nomes and "demo/test_main.py" not in nomes
        with tempfile.TemporaryDirectory() as pasta:
            arquivo.extractall(pasta)
            raiz = Path(pasta)
            conferir_pdf(
                raiz / "relatorio/Frequencia_UFMG_Produto_Final.pdf",
                5,
                [f"F0{i}" for i in range(1, 9)],
            )
            conferir_pdf(
                raiz / "relatorio/Frequencia_UFMG_Verificacao.pdf",
                6,
                [VERSION, *[f"F0{i}" for i in range(1, 9)], "Ran 28 tests", "OK"],
            )
            evidencia = (raiz / "evidencias/unittest.txt").read_text(encoding="utf-8")
            assert "Ran 28 tests" in evidencia and evidencia.rstrip().endswith("OK")
            execucao = subprocess.run(
                ["py", "-m", "unittest", "discover", "-v"],
                cwd=raiz / "demo",
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            assert execucao.returncode == 0, execucao.stdout + execucao.stderr
            assert "Ran 28 tests" in execucao.stdout + execucao.stderr
    print(f"ZIP, PDFs e 28 testes aprovados: {VERSION}")


if __name__ == "__main__":
    main()
