"""Camada de dados: armazenamento SQLite local do produto acadêmico.

Este módulo não decide quantas faltas uma situação produz. Recebe valores já
validados por models.py, usa parâmetros SQL e conclui cada gravação em uma
transação. Se qualquer comando falhar, o contexto desfaz a operação inteira.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

# O menu usa este arquivo por padrão. Os testes passam caminhos temporários.
DB_PATH = Path(__file__).with_name("frequencia.db")


@contextmanager
def conexao(caminho: str | Path = DB_PATH):
    """Abre conexão, ativa chaves estrangeiras e faz commit ou rollback.

    O bloco ``with`` da conexão confirma se não houver erro. Se surgir uma
    exceção, inclusive no segundo INSERT de um cadastro, ele desfaz tudo.
    Fechar no ``finally`` evita deixar o banco bloqueado após falhas.
    """
    banco = sqlite3.connect(str(caminho))
    try:
        banco.execute("PRAGMA foreign_keys = ON")
        with banco:
            yield banco
    finally:
        banco.close()


def inicializar_banco(caminho: str | Path = DB_PATH) -> None:
    """Cria as três tabelas se ainda não existirem; preserva dados existentes."""
    with conexao(caminho) as banco:
        banco.execute("""
            CREATE TABLE IF NOT EXISTS disciplinas (
                codigo TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                chamadas INTEGER NOT NULL CHECK (chamadas IN (1, 2)),
                aulas INTEGER NOT NULL CHECK (aulas IN (1, 2, 4))
            )
        """)
        banco.execute("""
            CREATE TABLE IF NOT EXISTS registros (
                disciplina_codigo TEXT NOT NULL,
                dia TEXT NOT NULL,
                situacao TEXT NOT NULL,
                faltas INTEGER,
                PRIMARY KEY (disciplina_codigo, dia),
                FOREIGN KEY (disciplina_codigo) REFERENCES disciplinas(codigo)
            )
        """)
        banco.execute("""
            CREATE TABLE IF NOT EXISTS atividades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                disciplina_codigo TEXT NOT NULL,
                dia TEXT NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('prova', 'trabalho')),
                titulo TEXT NOT NULL CHECK (length(trim(titulo)) > 0),
                FOREIGN KEY (disciplina_codigo) REFERENCES disciplinas(codigo)
            )
        """)


def salvar_disciplina(
    codigo: str,
    nome: str,
    chamadas: int,
    aulas: int,
    datas: list[date],
    caminho: str | Path = DB_PATH,
) -> None:
    """Grava disciplina e grade pendente juntas, ou nenhuma das duas.

    ``datas`` já foi validada pelo domínio. O par (código, dia) impede dois
    registros para a mesma aula. Um erro no meio do laço faz rollback de todos
    os INSERTs, inclusive do cadastro da disciplina.
    """
    with conexao(caminho) as banco:
        banco.execute(
            "INSERT INTO disciplinas (codigo, nome, chamadas, aulas) VALUES (?, ?, ?, ?)",
            (codigo, nome, chamadas, aulas),
        )
        for dia in datas:
            banco.execute(
                "INSERT INTO registros (disciplina_codigo, dia, situacao, faltas) "
                "VALUES (?, ?, 'pendente', NULL)",
                (codigo, dia.isoformat()),
            )


def listar_disciplinas(caminho: str | Path = DB_PATH) -> list[tuple]:
    """Devolve código, nome, chamadas e aulas das disciplinas cadastradas."""
    with conexao(caminho) as banco:
        return banco.execute(
            "SELECT codigo, nome, chamadas, aulas FROM disciplinas ORDER BY codigo"
        ).fetchall()


def atualizar_nome(codigo: str, nome: str, caminho: str | Path = DB_PATH) -> None:
    """Troca só o nome de uma disciplina já validada pela camada de negócio."""
    with conexao(caminho) as banco:
        cursor = banco.execute(
            "UPDATE disciplinas SET nome = ? WHERE codigo = ?", (nome, codigo)
        )
        if cursor.rowcount != 1:
            raise ValueError("Disciplina não encontrada no banco de dados.")


def obter_registros(codigo: str, caminho: str | Path = DB_PATH) -> list[tuple]:
    """Devolve data ISO, situação e faltas, inclusive encontros pendentes."""
    with conexao(caminho) as banco:
        return banco.execute(
            "SELECT dia, situacao, faltas FROM registros "
            "WHERE disciplina_codigo = ? ORDER BY dia",
            (codigo,),
        ).fetchall()


def salvar_registro(
    codigo: str, dia: date, situacao: str, faltas: int, caminho: str | Path = DB_PATH
) -> None:
    """Substitui a situação de um encontro após a validação no domínio.

    A cláusula UPSERT mantém uma única linha por data; uma correção não soma
    outra falta. A camada de negócio só publica o Registro após este commit.
    """
    with conexao(caminho) as banco:
        banco.execute(
            """
            INSERT INTO registros (disciplina_codigo, dia, situacao, faltas)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(disciplina_codigo, dia)
            DO UPDATE SET situacao=excluded.situacao, faltas=excluded.faltas
        """,
            (codigo, dia.isoformat(), situacao, faltas),
        )


def salvar_atividade(
    codigo: str, dia: date, tipo: str, titulo: str, caminho: str | Path = DB_PATH
) -> int:
    """Grava uma prova ou trabalho e retorna o ID criado pelo SQLite."""
    with conexao(caminho) as banco:
        cursor = banco.execute(
            "INSERT INTO atividades (disciplina_codigo, dia, tipo, titulo) "
            "VALUES (?, ?, ?, ?)",
            (codigo, dia.isoformat(), tipo, titulo),
        )
        return cursor.lastrowid


def listar_atividades(caminho: str | Path = DB_PATH) -> list[tuple]:
    """Devolve agenda por prazo e, no empate, pela ordem de inserção."""
    with conexao(caminho) as banco:
        return banco.execute(
            "SELECT id, disciplina_codigo, dia, tipo, titulo FROM atividades "
            "ORDER BY dia, id"
        ).fetchall()


def apagar_tudo(caminho: str | Path = DB_PATH) -> None:
    """Apaga os dados da demo em uma transação, preservando as tabelas.

    As tabelas dependentes são limpas primeiro por causa das chaves estrangeiras.
    Se qualquer comando falhar, o SQLite desfaz os anteriores.
    """
    with conexao(caminho) as banco:
        banco.execute("DELETE FROM atividades")
        banco.execute("DELETE FROM registros")
        banco.execute("DELETE FROM disciplinas")
