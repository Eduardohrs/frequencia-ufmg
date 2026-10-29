"""Teste do menu como interface pública, com entradas e saídas reais do terminal."""

import io
import runpy
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from main import executar, mostrar_resumo, preparar_dados
from models import Situacao


class TestTerminal(unittest.TestCase):
    def rodar(self, entradas):
        saida = io.StringIO()
        with patch("builtins.input", side_effect=entradas), redirect_stdout(saida):
            executar()
        return saida.getvalue()

    def test_menu_demonstra_as_duas_funcionalidades(self):
        saida = self.rodar(
            [
                "1",
                "1",  # consultar
                "2",
                "2",
                "S1",
                "1",
                "2",  # início fora
                "2",
                "2",
                "S1",
                "2",
                "2",  # fim fora =>4faltas
                "1",
                "2",  # exibir pings
                "3",
                "2",
                "S1",
                "1",
                "0",  # corrigir presente
                "3",
                "2",
                "S1",
                "5",  # corrigir pendente
                "4",
                "2",
                "0",
            ]
        )
        self.assertIn("Registro atualizado: ausente; faltas: 4", saida)
        self.assertIn("limite de faltas excedido", saida)
        self.assertIn("Registro atualizado: presente; faltas: 0", saida)
        self.assertIn("Frequência final: pendente", saida)
        self.assertIn("20 minutos após o início: fora do campus", saida)
        self.assertIn("Dados da demo descartados", saida)

    def test_erros_nao_encerram_o_menu(self):
        saida = self.rodar(
            [
                "banana",
                "1",
                "abc",
                "1",
                "0",  # ação, conversão, índice
                "2",
                "1",
                "naoexiste",  # sessão inexistente
                "3",
                "1",
                "S1",
                "1",
                "abc",  # faltas não numéricas
                "3",
                "1",
                "S1",
                "1",
                "99",  # faltas fora do limite
                "1",
                "1",
                "0",
            ]
        )
        self.assertEqual(saida.count("Operação rejeitada"), 6)
        self.assertIn("faltas: não definidas | manual: False", saida)

    def test_terminar_entrada_e_interrupcao(self):
        for erro in (EOFError(), KeyboardInterrupt()):
            with self.subTest(erro=erro):
                self.assertIn("Encerrado", self.rodar([erro]))

    def test_percentual_final_e_dados_independentes(self):
        disciplina = preparar_dados()[0]
        for s in disciplina.sessoes[:2]:
            s.corrigir(Situacao.PRESENTE, 0)
        saida = io.StringIO()
        with redirect_stdout(saida):
            mostrar_resumo(disciplina)
        self.assertIn("100.00%", saida.getvalue())
        self.assertIsNone(preparar_dados()[0].sessoes[0].registro.faltas)

    def test_ponto_de_entrada_documentado(self):
        with patch("builtins.input", return_value="0"), redirect_stdout(io.StringIO()):
            runpy.run_path(
                str(Path(__file__).with_name("main.py")), run_name="__main__"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
