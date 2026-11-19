"""Exercita o menu a partir de uma instalação vazia."""

import io
import os
import runpy
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

from dados_exemplo import criar_exemplo
from main import executar
from models import ControleAcademico


class TesteMenu(unittest.TestCase):
    def test_banco_inacessivel_mostra_erro_sem_abrir_menu(self):
        with patch(
            "main.ControleAcademico",
            side_effect=sqlite3.OperationalError("arquivo inacessível"),
        ):
            saida = self.rodar([])
        self.assertIn("Não foi possível abrir o banco local", saida)
        self.assertIn("arquivo inacessível", saida)
        self.assertNotIn("Ação:", saida)

    def test_falha_de_gravacao_mostra_erro_e_mantem_aula_pendente(self):
        with patch(
            "database.salvar_registro", side_effect=OSError("disco indisponível")
        ):
            saida = self.rodar(
                [
                    "1",
                    "DEMO01",
                    "Teste",
                    "1",
                    "2",
                    "02/11/2026",
                    "2",
                    "DEMO01",
                    "02/11/2026",
                    "ausente",
                    "0",
                ]
            )
        self.assertIn("Não foi possível salvar no banco", saida)
        controle = ControleAcademico(persistente=True, caminho_banco=self._db_path)
        registro = controle.obter_disciplina("DEMO01").registros[0]
        self.assertEqual(
            (registro.dia, registro.situacao), (date(2026, 11, 2), "pendente")
        )

    def test_agenda_pelo_menu_vazia_e_atividades_ordenadas(self):
        saida = self.rodar(
            [
                "6",
                "1",
                "DEMO01",
                "Teste",
                "1",
                "2",
                "02/11/2026",
                "5",
                "DEMO01",
                "05/11/2026",
                "trabalho",
                "Relatório",
                "5",
                "DEMO01",
                "03/11/2026",
                "prova",
                "Avaliação 1",
                "5",
                "DEMO01",
                "03/11/2026",
                "trabalho",
                "Lista 1",
                "7",
                "DEMO01",
                "Nome corrigido",
                "6",
                "0",
            ]
        )
        self.assertIn("Agenda vazia", saida)
        self.assertIn("Atividade salva: Avaliação 1", saida)
        self.assertIn("Disciplina renomeada", saida)
        self.assertIn("Nome corrigido", saida)
        linhas = (
            "03/11/2026 | DEMO01 | prova | Avaliação 1",
            "03/11/2026 | DEMO01 | trabalho | Lista 1",
            "05/11/2026 | DEMO01 | trabalho | Relatório",
        )
        self.assertTrue(all(linha in saida for linha in linhas))
        self.assertEqual(
            [saida.index(linha) for linha in linhas],
            sorted(saida.index(linha) for linha in linhas),
        )
        reaberto = self.rodar(["6", "0"])
        self.assertIn("Disciplinas: DEMO01 — Nome corrigido", reaberto)
        self.assertTrue(all(linha in reaberto for linha in linhas))
        self.assertEqual(
            [reaberto.index(linha) for linha in linhas],
            sorted(reaberto.index(linha) for linha in linhas),
        )

    def setUp(self):
        self._db_path = (
            Path(self.enterContext(tempfile.TemporaryDirectory())) / "teste.db"
        )
        os.environ["FREQUENCIA_DB_PATH"] = str(self._db_path)

    def tearDown(self):
        os.environ.pop("FREQUENCIA_DB_PATH", None)

    def test_dados_exemplo_criam_arquivo_isolado_e_nao_duplicam(self):
        caminho = self._db_path.with_name("exemplo.db")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(criar_exemplo(caminho), caminho)
            self.assertEqual(criar_exemplo(caminho), caminho)
        controle = ControleAcademico(persistente=True, caminho_banco=caminho)
        self.assertEqual(len(controle.disciplinas), 1)
        self.assertEqual(len(controle.atividades), 1)
        with (
            patch.dict(os.environ, {"FREQUENCIA_EXEMPLO_DB_PATH": str(caminho)}),
            redirect_stdout(io.StringIO()),
        ):
            runpy.run_path(
                str(Path(__file__).with_name("dados_exemplo.py")),
                run_name="__main__",
            )

    def rodar(self, entradas):
        saida = io.StringIO()
        with patch("builtins.input", side_effect=entradas), redirect_stdout(saida):
            executar()
        return saida.getvalue()

    def test_fluxo_completo_sem_dados_preparados(self):
        saida = self.rodar(
            [
                "1",
                "D",
                "Teste",
                "2",
                "2",
                "02/11/2026,04/11/2026",
                "4",
                "D",
                "02/11/2026",
                "presente",
                "2",
                "D",
                "02/11/2026",
                "ausente",
                "2",
                "D",
                "04/11/2026",
                "presente",
                "3",
                "D",
                "4",
                "D",
                "02/11/2026",
                "presente",
                "0",
            ]
        )
        self.assertIn("SQLite local", saida)
        self.assertIn("Disciplina criada", saida)
        self.assertIn("Esta data está pendente. Use Registrar presença.", saida)
        self.assertIn("Limite excedido", saida)
        self.assertIn("Frequência: 50.0%", saida)
        self.assertIn("Frequência: 100.0%", saida)
        self.assertIn("Frequência: pendente", saida)
        self.assertIn("Base: 4 aulas | Pendentes: 4 aulas", saida)
        self.assertIn("Faltas: 2 aulas | Limite: 1 aula | Restantes: 0 aulas", saida)

    def test_rejeicoes_e_conversoes_sao_tratadas(self):
        saida = self.rodar(
            [
                "9",
                "3",
                "NAOEXISTE",
                "1",
                "D",
                "Teste",
                "texto",
                "1",
                "D",
                "Teste",
                "1",
                "2",
                "31/02/2026",
                "0",
            ]
        )
        self.assertEqual(saida.count("Operação rejeitada:"), 4)
        self.assertIn("Encerrado", saida)
        self.assertEqual(
            ControleAcademico(
                persistente=True, caminho_banco=self._db_path
            ).disciplinas,
            (),
        )

    def test_fim_de_entrada_e_interrupcao_encerram(self):
        for erro in (EOFError(), KeyboardInterrupt()):
            self.assertIn("Encerrado", self.rodar([erro]))

    def test_ponto_de_entrada(self):
        with patch("builtins.input", return_value="0"), redirect_stdout(io.StringIO()):
            runpy.run_path(
                str(Path(__file__).with_name("main.py")), run_name="__main__"
            )
