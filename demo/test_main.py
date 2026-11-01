"""Exercita o menu a partir de uma instalação vazia."""

import io
import runpy
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from main import executar


class TesteMenu(unittest.TestCase):
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
        self.assertIn("Cadastro vazio", saida)
        self.assertIn("Disciplina criada", saida)
        self.assertIn("Limite excedido", saida)
        self.assertIn("Frequência: 50.0%", saida)
        self.assertIn("Frequência: 100.0%", saida)
        self.assertIn("Frequência: pendente", saida)

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

    def test_fim_de_entrada_e_interrupcao_encerram(self):
        for erro in (EOFError(), KeyboardInterrupt()):
            self.assertIn("Encerrado", self.rodar([erro]))

    def test_ponto_de_entrada(self):
        with patch("builtins.input", return_value="0"), redirect_stdout(io.StringIO()):
            runpy.run_path(
                str(Path(__file__).with_name("main.py")), run_name="__main__"
            )
