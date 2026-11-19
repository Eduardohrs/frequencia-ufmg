"""Confere o pacote final como uma pessoa que acabou de baixar o ZIP."""

import os
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile

import fitz

BASE = Path(__file__).parent
ARCHIVE = BASE / "Frequencia_UFMG_Entrega_Final.zip"
VERSION = "PF-02-AGENDA"


def check_pdf(path, min_pages, functions):
    with fitz.open(path) as pdf:
        assert len(pdf) >= min_pages, (path.name, len(pdf))
        text = "\n".join(page.get_text() for page in pdf)
        assert VERSION in text, path.name
        for label in functions:
            assert label in text, (path.name, label)
        for page_number, page in enumerate(pdf, 1):
            assert len(page.get_text().strip()) > 300, (path.name, page_number)
            assert f"Página {page_number}" in page.get_text(), (path.name, page_number)


def main():
    names = {
        "LEIA-ME.md",
        "demo/README.md",
        "demo/main.py",
        "demo/web.py",
        "demo/web/index.html",
        "demo/web/app.css",
        "demo/web/app.js",
        "demo/models.py",
        "demo/database.py",
        "demo/dados_exemplo.py",
        "demo/frequencia.db",
        "demo/test_main.py",
        "demo/test_models.py",
        "demo/test_web.py",
        "evidencias/unittest.txt",
        "relatorio/Frequencia_UFMG_Produto_Final.pdf",
        "relatorio/Frequencia_UFMG_Verificacao.pdf",
    }
    with ZipFile(ARCHIVE) as package:
        missing = names - set(package.namelist())
        assert not missing, f"Arquivos ausentes no ZIP: {sorted(missing)}"
        with tempfile.TemporaryDirectory() as folder:
            package.extractall(folder)
            root = Path(folder)
            demo = root / "demo"
            product = root / "relatorio" / "Frequencia_UFMG_Produto_Final.pdf"
            verification = root / "relatorio" / "Frequencia_UFMG_Verificacao.pdf"
            check_pdf(product, 10, [*[f"F0{i}" for i in range(1, 9)], ARCHIVE.name])
            check_pdf(verification, 9, [f"F0{i}" for i in range(1, 9)])
            evidence = (root / "evidencias" / "unittest.txt").read_text(
                encoding="utf-8-sig"
            )
            assert "Ran 31 tests" in evidence and evidence.rstrip().endswith("OK")
            tests = subprocess.run(
                ["py", "-m", "unittest", "discover", "-v"],
                cwd=demo,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert tests.returncode == 0, tests.stdout + tests.stderr
            env = os.environ.copy()
            env["FREQUENCIA_DB_PATH"] = str(root / "smoke.db")
            actions = "\n".join(
                [
                    "1",
                    "DEMO01",
                    "Disciplina teste",
                    "2",
                    "2",
                    "02/11/2026,04/11/2026",
                    "2",
                    "1",
                    "02/11/2026",
                    "ausente",
                    "5",
                    "1",
                    "03/11/2026",
                    "prova",
                    "P1",
                    "7",
                    "1",
                    "Nome corrigido",
                    "6",
                    "3",
                    "1",
                    "0",
                    "",
                ]
            )
            run = subprocess.run(
                ["py", "main.py"],
                input=actions,
                cwd=demo,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert run.returncode == 0, run.stderr
            for phrase in [
                "Disciplina criada",
                "Registro salvo",
                "Atividade salva",
                "Disciplina renomeada",
                "03/11/2026 | Nome corrigido (DEMO01) | prova | P1",
                "Nome corrigido",
            ]:
                assert phrase in run.stdout, (phrase, run.stdout)
            again = subprocess.run(
                ["py", "main.py"],
                input="3\n1\n6\n0\n",
                cwd=demo,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert again.returncode == 0, again.stderr
            assert "Nome corrigido" in again.stdout and "P1" in again.stdout
            reset = subprocess.run(
                ["py", "main.py"],
                input="8\nAPAGAR\n0\n",
                cwd=demo,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert reset.returncode == 0, reset.stderr
            assert "Dados apagados" in reset.stdout
            vazio = subprocess.run(
                ["py", "main.py"],
                input="3\n6\n0\n",
                cwd=demo,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert vazio.returncode == 0, vazio.stderr
            assert "Nenhuma disciplina cadastrada" in vazio.stdout
            assert "Agenda vazia" in vazio.stdout
            print(
                "ZIP íntegro; PDFs, 31 testes, interface local, persistência e reset aprovados."
            )


if __name__ == "__main__":
    main()
