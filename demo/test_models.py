"""Cenários do recorte de frequência, com dados novos e fictícios em cada teste."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import date

from models import (
    ChamadaDupla,
    ChamadaUnica,
    Disciplina,
    Evidencia,
    Momento,
    PoliticaFrequencia,
    SessaoAula,
    Situacao,
)


class TestFrequencia(unittest.TestCase):
    def sessao(self, politica=None, aulas=4, **kwargs):
        return SessaoAula(
            "S1", date(2026, 10, 20), aulas, politica or ChamadaDupla(), **kwargs
        )

    def test_polimorfismo_mesma_chamada_resultados_diferentes(self):
        for politica, faltas in [(ChamadaUnica(), 0), (ChamadaDupla(), 2)]:
            with self.subTest(politica=type(politica).__name__):
                resultado = politica.classificar(4, Evidencia.NO_CAMPUS, Evidencia.FORA)
                self.assertEqual(resultado.situacao, Situacao.SAIU_MAIS_CEDO)
                self.assertEqual(resultado.faltas, faltas)
        with self.assertRaises(TypeError):
            PoliticaFrequencia()

    def test_pings_validos_e_consulta_sem_alteracao(self):
        sessao = self.sessao()
        disciplina = Disciplina("DEMO01", "Disciplina fictícia", [sessao])
        sessao.registrar_ping(Momento.INICIO, Evidencia.NO_CAMPUS)
        self.assertIsNone(sessao.registro.faltas)
        resultado = sessao.registrar_ping(Momento.FIM, Evidencia.NO_CAMPUS)
        self.assertEqual((resultado.situacao, resultado.faltas), (Situacao.PRESENTE, 0))
        antes = (sessao.pings, sessao.registro)
        resumo = disciplina.resumo()
        self.assertEqual(resumo.frequencia_percentual, 100)
        self.assertEqual(antes, (sessao.pings, sessao.registro))
        with self.assertRaises(FrozenInstanceError):
            resultado.faltas = 4

    def test_ping_duplicado_preserva_todo_estado(self):
        sessao = self.sessao()
        sessao.registrar_ping(Momento.INICIO, Evidencia.FORA)
        antes = (sessao.pings, sessao.registro)
        with self.assertRaisesRegex(ValueError, "já registrado"):
            sessao.registrar_ping(Momento.INICIO, Evidencia.NO_CAMPUS)
        self.assertEqual(antes, (sessao.pings, sessao.registro))

    def test_tabela_de_classificacao(self):
        for politica in [ChamadaUnica(), ChamadaDupla()]:
            for primeiro, segundo, situacao in [
                (Evidencia.NO_CAMPUS, Evidencia.NO_CAMPUS, Situacao.PRESENTE),
                (Evidencia.FORA, Evidencia.NO_CAMPUS, Situacao.ATRASADO),
                (Evidencia.FORA, Evidencia.FORA, Situacao.AUSENTE),
                (Evidencia.INDISPONIVEL, Evidencia.FORA, Situacao.PENDENTE),
            ]:
                with self.subTest(politica=politica, situacao=situacao):
                    r = politica.classificar(4, primeiro, segundo)
                    self.assertEqual(r.situacao, situacao)
            r = politica.classificar(4, Evidencia.NO_CAMPUS, Evidencia.INDISPONIVEL)
            self.assertEqual(
                r.faltas, 0 if isinstance(politica, ChamadaUnica) else None
            )
        self.assertEqual(
            ChamadaDupla().classificar(4, Evidencia.FORA, Evidencia.NO_CAMPUS).faltas, 2
        )

    def test_correcao_substitui_sem_acumular_e_preserva_pings(self):
        sessao = self.sessao()
        disciplina = Disciplina("DEMO01", "Fictícia", [sessao])
        sessao.registrar_ping(Momento.INICIO, Evidencia.FORA)
        sessao.registrar_ping(Momento.FIM, Evidencia.FORA)
        self.assertEqual(disciplina.resumo().faltas_consumidas, 4)
        pings = sessao.pings
        sessao.corrigir(Situacao.PRESENTE, 0)
        sessao.corrigir(Situacao.ATRASADO, 1)
        self.assertEqual(disciplina.resumo().faltas_consumidas, 1)
        self.assertEqual(disciplina.resumo().faltas_restantes, 0)
        self.assertEqual(pings, sessao.pings)
        self.assertTrue(sessao.registro.manual)

    def test_correcao_invalida_preserva_estado(self):
        sessao = self.sessao()
        antes = (sessao.pings, sessao.registro)
        for situacao, faltas in [
            ("presente", 0),
            (Situacao.PENDENTE, 0),
            (Situacao.PRESENTE, -1),
            (Situacao.AUSENTE, 5),
            (Situacao.PRESENTE, True),
            (Situacao.PRESENTE, 1.5),
        ]:
            with self.subTest(faltas=faltas), self.assertRaises(ValueError):
                sessao.corrigir(situacao, faltas)
            self.assertEqual(antes, (sessao.pings, sessao.registro))
        sessao.corrigir(Situacao.PENDENTE, None)
        self.assertIsNone(sessao.registro.faltas)
        with self.assertRaisesRegex(ValueError, "manual"):
            sessao.registrar_ping(Momento.FIM, Evidencia.NO_CAMPUS)

    def test_limite_pendencias_cancelada_sem_chamada(self):
        sessoes = [
            self.sessao(aulas=4),
            SessaoAula(
                "S2", date(2026, 10, 21), 2, ChamadaUnica(), natureza="sem_chamada"
            ),
            SessaoAula(
                "S3", date(2026, 10, 22), 2, ChamadaUnica(), natureza="cancelada"
            ),
        ]
        disciplina = Disciplina("DEMO01", "Fictícia", sessoes)
        r = disciplina.resumo()
        self.assertEqual(
            (r.aulas_elegiveis, r.aulas_pendentes, r.aulas_presentes), (6, 4, 2)
        )
        self.assertIsNone(r.frequencia_percentual)
        sessoes[0].corrigir(Situacao.AUSENTE, 4)
        r = disciplina.resumo()
        self.assertEqual(
            (r.limite_faltas, r.faltas_restantes, r.excedeu_limite), (1, 0, True)
        )
        self.assertAlmostEqual(r.frequencia_percentual, 100 / 3)
        for sessao in sessoes[1:]:
            with self.assertRaises(ValueError):
                sessao.corrigir(Situacao.AUSENTE, 2)
            with self.assertRaises(ValueError):
                sessao.registrar_ping(Momento.INICIO, Evidencia.FORA)
        vazio = Disciplina("D", "Vazia", []).resumo()
        self.assertIsNone(vazio.frequencia_percentual)
        self.assertEqual(vazio.faltas_restantes, 0)

    def test_arredondamento_em_61_unidades(self):
        sessoes = [
            SessaoAula(str(i), date(2026, 10, 20), 1, ChamadaUnica()) for i in range(61)
        ]
        disciplina = Disciplina("LIMITE", "Fictícia", sessoes)
        for i, sessao in enumerate(sessoes):
            sessao.corrigir(
                Situacao.AUSENTE if i < 15 else Situacao.PRESENTE, 1 if i < 15 else 0
            )
        resumo = disciplina.resumo()
        self.assertEqual((resumo.limite_faltas, resumo.faltas_restantes), (15, 0))
        self.assertGreaterEqual(resumo.frequencia_percentual, 75)
        sessoes[15].corrigir(Situacao.AUSENTE, 1)
        self.assertTrue(disciplina.resumo().excedeu_limite)
        self.assertLess(disciplina.resumo().frequencia_percentual, 75)

    def test_validacao_dados_iniciais_e_colecoes(self):
        for aulas, politica in [
            (0, ChamadaUnica()),
            (3, ChamadaUnica()),
            (True, ChamadaUnica()),
            (1, ChamadaDupla()),
            (2, object()),
        ]:
            with self.subTest(aulas=aulas), self.assertRaises(ValueError):
                self.sessao(politica, aulas)
        for kwargs in [
            {"identificador": ""},
            {"dia": "2026-10-20"},
            {"natureza": "outra"},
        ]:
            valores = dict(
                identificador="S",
                dia=date(2026, 10, 20),
                aulas=2,
                politica=ChamadaUnica(),
            )
            valores.update(kwargs)
            with self.assertRaises(ValueError):
                SessaoAula(**valores)
        sessao = self.sessao()
        for momento, evidencia in [("inicio", Evidencia.FORA), (Momento.INICIO, True)]:
            with self.assertRaises(ValueError):
                sessao.registrar_ping(momento, evidencia)
        for codigo, nome, sessoes in [
            ("", "D", []),
            ("D", "", []),
            ("D", "D", [object()]),
            ("D", "D", [sessao, sessao]),
        ]:
            with self.assertRaises(ValueError):
                Disciplina(codigo, nome, sessoes)
        d = Disciplina("D", "D", [sessao])
        self.assertEqual(d.obter_sessao("S1"), sessao)
        with self.assertRaises(ValueError):
            d.obter_sessao("inexistente")
        with self.assertRaises(AttributeError):
            d.sessoes.append(sessao)


if __name__ == "__main__":
    unittest.main(verbosity=2)
