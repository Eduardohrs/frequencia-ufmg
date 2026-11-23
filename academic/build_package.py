"""Monta relatórios, evidência e ZIP da demo a partir dos fontes atuais."""

import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ACADEMIC = ROOT / "academic"
DEMO = ROOT / "demo"
PACKAGE = ACADEMIC / "package"


def main():
    target_demo = PACKAGE / "demo"
    target_demo.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ACADEMIC / "GUIA_APRESENTACAO.md", PACKAGE / "GUIA_APRESENTACAO.md")
    for stale in ("main.py", "test_main.py"):
        (target_demo / stale).unlink(missing_ok=True)
    for source in [*DEMO.glob("*.py"), DEMO / "README.md", DEMO / "frequencia.db"]:
        shutil.copy2(source, target_demo / source.name)
    target_web = target_demo / "web"
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
    (PACKAGE / "relatorio").mkdir(exist_ok=True)
    for name in (
        "Frequencia_UFMG_Produto_Final.pdf",
        "Frequencia_UFMG_Verificacao.pdf",
    ):
        shutil.copy2(ACADEMIC / name, PACKAGE / "relatorio" / name)
    archive = ACADEMIC / "Frequencia_UFMG_Entrega_Final.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for source in sorted(PACKAGE.rglob("*")):
            if source.is_file():
                output.write(source, source.relative_to(PACKAGE).as_posix())
    print("Pacote atualizado:", archive)


if __name__ == "__main__":
    main()
