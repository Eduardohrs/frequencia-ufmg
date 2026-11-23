"""Monta os artefatos da entrega a partir dos fontes atuais."""

import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ACADEMIC = ROOT / "academic"
DEMO = ROOT / "demo"
PACKAGE = ACADEMIC / "package"


def main():
    # O ZIP é a entrega da professora: remove artefatos de apoio e deixa
    # somente produto/, evidencias/ e documentos/entregas/.
    for stale in ("demo", "relatorio", "LEIA-ME.md", "GUIA_APRESENTACAO.md"):
        path = PACKAGE / stale
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    target_product = PACKAGE / "produto"
    target_product.mkdir(parents=True, exist_ok=True)
    for stale in ("main.py", "test_main.py"):
        (target_product / stale).unlink(missing_ok=True)
    for source in [*DEMO.glob("*.py"), DEMO / "README.md", DEMO / "frequencia.db"]:
        destination = target_product / source.name
        if source.name == "README.md":
            texto = source.read_text(encoding="utf-8")
            texto = texto.replace("`demo/`", "`produto/`")
            texto = texto.replace("dados da demo", "dados do produto")
            texto = texto.replace("esta demo", "este produto")
            texto = texto.replace("essa demo", "esse produto")
            destination.write_text(texto, encoding="utf-8")
        else:
            shutil.copy2(source, destination)
    target_web = target_product / "web"
    target_web.mkdir(exist_ok=True)
    for source in (DEMO / "web").iterdir():
        if source.is_file():
            shutil.copy2(source, target_web / source.name)

    result = subprocess.run(
        ["py", "-m", "unittest", "discover", "-v"],
        cwd=DEMO,
        capture_output=True,
        text=True,
        check=True,
    )
    evidence = result.stdout + result.stderr
    assert "Ran 28 tests" in evidence and evidence.rstrip().endswith("OK")
    (PACKAGE / "evidencias").mkdir(exist_ok=True)
    (PACKAGE / "evidencias/unittest.txt").write_text(evidence, encoding="utf-8")

    subprocess.run(["py", "academic/build_pdfs.py"], cwd=ROOT, check=True)
    target_reports = PACKAGE / "documentos/entregas"
    target_reports.mkdir(parents=True, exist_ok=True)
    for name in (
        "Frequencia_UFMG_Produto_Final.pdf",
        "Frequencia_UFMG_Verificacao.pdf",
    ):
        shutil.copy2(ACADEMIC / name, target_reports / name)
    archive = ACADEMIC / "Frequencia_UFMG_Entrega_Final.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for source in sorted(PACKAGE.rglob("*")):
            if source.is_file():
                output.write(source, source.relative_to(PACKAGE).as_posix())
    print("Pacote atualizado:", archive)


if __name__ == "__main__":
    main()
