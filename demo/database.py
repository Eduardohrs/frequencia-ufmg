"""Persistência SQLite para o protótipo de frequência.

Este módulo implementa a camada de persistência local usando SQLite.
Responsabilidades:
- Criar e inicializar o banco de dados automaticamente
- Fornecer operações CRUD para disciplinas e registros
- Manipular conversões entre tipos Python e SQL
- Garantir atomicidade das operações
- Fornecer mecanismos de reset para testes

O banco usa um único arquivo 'frequencia.db' na pasta demo/.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date
from typing import Optional
from pathlib import Path

# Caminho do banco de dados
DB_PATH = Path(__file__).with_name("frequencia.db")


def _criar_tabelas(conexao: sqlite3.Connection) -> None:
    """Cria as tabelas do banco se não existirem.
    
    Tabelas:
    - disciplinas: armazena metadados da disciplina
    - registros: armazena registros de frequência por data
    """
    cursor = conexao.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS disciplinas (
            codigo TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            chamadas INTEGER NOT NULL CHECK (chamadas IN (1, 2)),
            aulas INTEGER NOT NULL CHECK (aulas IN (1, 2, 4))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registros (
            disciplina_codigo TEXT NOT NULL,
            dia TEXT NOT NULL,
            situacao TEXT NOT NULL,
            faltas INTEGER,
            PRIMARY KEY (disciplina_codigo, dia),
            FOREIGN KEY (disciplina_codigo) REFERENCES disciplinas(codigo)
                ON DELETE CASCADE
        )
    """)
    conexao.commit()


@contextmanager
def obter_conexao(caminho: str | Path = DB_PATH):
    """Contexto para obter uma conexão com o banco de dados.
    
    Garante que a conexão é fechada automaticamente após o uso,
    mesmo em caso de exceções.
    
    Yields:
        sqlite3.Connection: Conexão ativa com o banco de dados
    """
    conexao = sqlite3.connect(str(caminho), detect_types=sqlite3.PARSE_DECLTYPES)
    try:
        yield conexao
    finally:
        conexao.close()


def inicializar_banco(caminho: str | Path = DB_PATH) -> None:
    """Inicializa o banco de dados, criando as tabelas se necessário.
    
    Chamada automaticamente ao importar este módulo ou ao criar
    uma instância de ControleAcademico.
    """
    with obter_conexao(caminho) as conexao:
        _criar_tabelas(conexao)


def resetar_banco(caminho: str | Path = DB_PATH) -> None:
    """Apaga todas as tabelas e recria o schema.
    
    Uso: apenas para testes e desenvolvimento.
    ADVERTÊNCIA: Esta operação é destrutiva e não pode ser desfeita.
    """
    caminho = Path(caminho)
    if caminho.exists():
        caminho.unlink()
    with obter_conexao(caminho) as conexao:
        _criar_tabelas(conexao)


def disciplinas_existem(caminho: str | Path = DB_PATH) -> bool:
    """Verifica se existem disciplinas cadastradas no banco.
    
    Returns:
        bool: True se existirem disciplinas, False caso contrário
    """
    with obter_conexao(caminho) as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT COUNT(*) FROM disciplinas")
        return cursor.fetchone()[0] > 0


def salvar_disciplina(codigo: str, nome: str, chamadas: int, aulas: int, datas: list, caminho: str | Path = DB_PATH) -> None:
    """Salva uma disciplina e seus registros iniciais (pendentes).
    
    Args:
        codigo: Código da disciplina (chave primária)
        nome: Nome da disciplina
        chamadas: Número de chamadas (1 ou 2)
        aulas: Número de aulas por encontro (1, 2 ou 4)
        datas: Lista de datas das aulas
        
    Raises:
        sqlite3.IntegrityError: Se o código já existir
    """
    with obter_conexao(caminho) as conexao:
        cursor = conexao.cursor()
        cursor.execute(
            "INSERT INTO disciplinas (codigo, nome, chamadas, aulas) VALUES (?, ?, ?, ?)",
            (codigo, nome, chamadas, aulas)
        )
        for dia in datas:
            cursor.execute(
                "INSERT INTO registros (disciplina_codigo, dia, situacao, faltas) VALUES (?, ?, ?, ?)",
                (codigo, str(dia), "pendente", None)
            )
        conexao.commit()


def obter_disciplina(codigo: str, caminho: str | Path = DB_PATH) -> Optional[tuple]:
    """Obtém os metadados de uma disciplina.
    
    Args:
        codigo: Código da disciplina a buscar
        
    Returns:
        tuple: (codigo, nome, chamadas, aulas) ou None se não encontrar
    """
    with obter_conexao(caminho) as conexao:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT codigo, nome, chamadas, aulas FROM disciplinas WHERE codigo = ?",
            (codigo,)
        )
        return cursor.fetchone()


def listar_disciplinas(caminho: str | Path = DB_PATH) -> list:
    """Lista todas as disciplinas cadastradas.
    
    Returns:
        list: Lista de tuplas (codigo, nome, chamadas, aulas)
    """
    with obter_conexao(caminho) as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT codigo, nome, chamadas, aulas FROM disciplinas ORDER BY codigo")
        return cursor.fetchall()


def obter_registros(codigo: str, caminho: str | Path = DB_PATH) -> list:
    """Obtém todos os registros de uma disciplina.
    
    Args:
        codigo: Código da disciplina
        
    Returns:
        list: Lista de tuplas (dia, situacao, faltas)
    """
    with obter_conexao(caminho) as conexao:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT dia, situacao, faltas FROM registros WHERE disciplina_codigo = ? ORDER BY dia",
            (codigo,)
        )
        return cursor.fetchall()


def salvar_registro(codigo: str, dia: date, situacao: str, faltas: Optional[int], caminho: str | Path = DB_PATH) -> None:
    """Atualiza ou insere um registro de frequência.
    
    Args:
        codigo: Código da disciplina
        dia: Data do registro
        situacao: Situação do registro
        faltas: Número de faltas (None para pendente)
    """
    with obter_conexao(caminho) as conexao:
        cursor = conexao.cursor()
        cursor.execute(
            """INSERT INTO registros (disciplina_codigo, dia, situacao, faltas) 
               VALUES (?, ?, ?, ?)
               ON CONFLICT(disciplina_codigo, dia) 
               DO UPDATE SET situacao = excluded.situacao, faltas = excluded.faltas""",
            (codigo, str(dia), situacao, faltas)
        )
        conexao.commit()


def apagar_disciplina(codigo: str, caminho: str | Path = DB_PATH) -> None:
    """Apaga uma disciplina e todos os seus registros.
    
    Args:
        codigo: Código da disciplina a apagar
    """
    with obter_conexao(caminho) as conexao:
        cursor = conexao.cursor()
        cursor.execute("DELETE FROM disciplinas WHERE codigo = ?", (codigo,))
        conexao.commit()


