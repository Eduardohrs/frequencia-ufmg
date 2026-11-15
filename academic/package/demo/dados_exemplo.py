"""Cria uma base fictícia separada para demonstração da entrega acadêmica.

O arquivo padrão frequencia.db do estudante não é tocado. Execute esta rotina
uma vez em demo/; para usá-la no menu, defina FREQUENCIA_DB_PATH=exemplo.db.
"""

import os
from datetime import date
from pathlib import Path

from models import ControleAcademico


def criar_exemplo(caminho=None):
    """Prepara uma disciplina, uma frequência e uma prova em banco próprio."""
    destino = (
        Path(caminho)
        if caminho
        else Path(
            os.environ.get(
                "FREQUENCIA_EXEMPLO_DB_PATH", Path(__file__).with_name("exemplo.db")
            )
        )
    )
    if destino.exists():
        print(f"A base fictícia já existe: {destino}")
        return destino
    controle = ControleAcademico(persistente=True, caminho_banco=destino)
    dias = [date(2026, 11, dia) for dia in (2, 4, 9, 11)]
    disciplina = controle.criar_disciplina("DEMO01", "Disciplina fictícia", 2, 2, dias)
    disciplina.registrar_presenca(dias[0], "presente")
    disciplina.registrar_presenca(dias[1], "ausente")
    controle.adicionar_atividade(
        "DEMO01", date(2026, 11, 10), "prova", "Avaliação fictícia"
    )
    print(f"Base fictícia criada: {destino}")
    return destino


if __name__ == "__main__":
    criar_exemplo()
