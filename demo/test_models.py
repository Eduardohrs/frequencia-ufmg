"""Cenários independentes: cada teste começa com um cadastro vazio."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import date

from models import SITUACOES, ControleAcademico, Disciplina, PoliticaChamada

DIAS = [date(2026, 11, d) for d in (2, 4, 9, 11)]


class TesteFrequencia(unittest.TestCase):
    def test_criar_e_registrar_do_zero(self):
        controle = ControleAcademico()
        self.assertEqual(controle.disciplinas, ())
        d = controle.criar_disciplina(" demo01 ", "Teste", 2, 2, DIAS)
        self.assertEqual((d.codigo, d.nome, d.chamadas), ("DEMO01", "Teste", 2))
        self.assertIs(controle.obter_disciplina("demo01"), d)
        self.assertEqual(d.registrar_presenca(DIAS[0], "presente").faltas, 0)
        self.assertEqual(d.registrar_presenca(DIAS[1], "ausente").faltas, 2)
        self.assertEqual(
            d.resumo(),
            dict(
                aulas=8,
                pendentes=4,
                faltas=2,
                limite=2,
                restantes=0,
                excesso=0,
                frequencia=None,
            ),
        )

    def test_codigo_duplicado_preserva_cadastro_e_frequencia(self):
        c = ControleAcademico()
        d = c.criar_disciplina("DEMO01", "Teste", 1, 2, DIAS)
        d.registrar_presenca(DIAS[0], "presente")
        antes = (c.disciplinas, d.registros, d.resumo())
        with self.assertRaises(ValueError):
            c.criar_disciplina("demo01", "Outro nome", 2, 4, DIAS)
        self.assertEqual((c.disciplinas, d.registros, d.resumo()), antes)
        with self.assertRaises(ValueError):
            c.obter_disciplina("NAOEXISTE")

    def test_entrada_invalida_nao_cria_disciplina(self):
        for valores in [
            ("", "Teste", 1, 2, DIAS),
            (None, "Teste", 1, 2, DIAS),
            ("D", "", 1, 2, DIAS),
            ("D", None, 1, 2, DIAS),
            ("D", "T", 3, 2, DIAS),
            ("D", "T", True, 2, DIAS),
            ("D", "T", 1, 3, DIAS),
            ("D", "T", 1, True, DIAS),
            ("D", "T", 2, 1, DIAS),
            ("D", "T", 1, 2, []),
            ("D", "T", 1, 2, ["02/11/2026"]),
            ("D", "T", 1, 2, [DIAS[0], DIAS[0]]),
        ]:
            with self.subTest(valores=valores):
                c = ControleAcademico()
                with self.assertRaises(ValueError):
                    c.criar_disciplina(*valores)
                self.assertEqual(c.disciplinas, ())
        with self.assertRaises(TypeError):
            PoliticaChamada()

    def test_registro_invalido_nao_muda_grade_nem_totais(self):
        d = Disciplina("D", "Teste", 2, 2, DIAS)
        antes = (d.registros, d.resumo())
        for dia, situacao in [
            (date(2026, 12, 1), "presente"),
            ("02/11/2026", "presente"),
            (DIAS[0], "errada"),
        ]:
            with self.assertRaises(ValueError):
                d.registrar_presenca(dia, situacao)
            self.assertEqual((d.registros, d.resumo()), antes)
        d.registrar_presenca(DIAS[0], "ausente")
        antes = (d.registros, d.resumo())
        with self.assertRaises(ValueError):
            d.registrar_presenca(DIAS[0], "presente")
        self.assertEqual((d.registros, d.resumo()), antes)
        with self.assertRaises(FrozenInstanceError):
            d.registros[0].faltas = 99

    def test_mesma_operacao_tem_resultado_conforme_chamada(self):
        for chamadas, esperado in [(1, 0), (2, 2)]:
            for situacao in ("atrasado", "saiu mais cedo"):
                d = Disciplina("D", "Teste", chamadas, 4, [DIAS[0]])
                self.assertEqual(
                    d.registrar_presenca(DIAS[0], situacao).faltas, esperado
                )
        for chamadas in (1, 2):
            for situacao in SITUACOES:
                d = Disciplina("D", "Teste", chamadas, 2, [DIAS[0]])
                self.assertIsNotNone(d.registrar_presenca(DIAS[0], situacao))

    def test_correcao_substitui_e_recalcula(self):
        d = Disciplina("D", "Teste", 2, 2, DIAS)
        d.registrar_presenca(DIAS[0], "ausente")
        d.registrar_presenca(DIAS[1], "ausente")
        self.assertEqual(d.resumo()["excesso"], 2)
        d.registrar_presenca(DIAS[0], "presente", corrigir=True)
        self.assertEqual(d.resumo()["faltas"], 2)
        d.registrar_presenca(DIAS[1], "presente", corrigir=True)
        self.assertEqual(d.resumo()["restantes"], 2)
        d.registrar_presenca(DIAS[2], "sem chamada")
        d.registrar_presenca(DIAS[3], "cancelada")
        self.assertEqual(
            d.resumo(),
            dict(
                aulas=6,
                pendentes=0,
                faltas=0,
                limite=1,
                restantes=1,
                excesso=0,
                frequencia=100.0,
            ),
        )
        antes = d.registros
        d.resumo()
        self.assertEqual(d.registros, antes)
        d.registrar_presenca(DIAS[0], "cancelada", corrigir=True)
        d.registrar_presenca(DIAS[1], "cancelada", corrigir=True)
        d.registrar_presenca(DIAS[2], "cancelada", corrigir=True)
        self.assertIsNone(d.resumo()["frequencia"])
