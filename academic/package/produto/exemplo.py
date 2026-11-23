"""Dados fictícios da apresentação; não fazem parte das regras do domínio."""

from datetime import date

import database
from models import ControleAcademico


def criar_exemplo(caminho_banco):
    """Valida a amostra pelas classes normais e grava tudo numa transação.

    A função é separada de Disciplina e ControleAcademico porque carregar uma
    demonstração é uma tarefa de apresentação, não uma operação de uma matéria.
    Uma base parcialmente preenchida nunca recebe o exemplo por cima.
    """
    caminho_banco = caminho_banco or database.DB_PATH
    atual = ControleAcademico(persistente=True, caminho_banco=caminho_banco)
    if atual.disciplinas or atual.atividades:
        raise ValueError("Os dados de exemplo exigem uma demo vazia.")

    amostra = ControleAcademico()
    dias = [date(2026, 11, dia) for dia in (2, 4, 9, 11)]
    disciplina = amostra.criar_disciplina("DEMO01", "Disciplina fictícia", 2, 2, dias)
    amostra.registrar_presenca("DEMO01", dias[0], "presente")
    amostra.registrar_presenca("DEMO01", dias[1], "ausente")
    atividade = amostra.adicionar_atividade(
        "DEMO01", date(2026, 11, 10), "prova", "Avaliação fictícia"
    )
    database.salvar_exemplo(disciplina, atividade, caminho_banco)
