"""Cenários independentes: cada teste começa com um cadastro vazio."""

import sqlite3
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from unittest.mock import patch

import database
from models import SITUACOES, ControleAcademico, Disciplina, PoliticaChamada

DIAS = [date(2026, 11, d) for d in (2, 4, 9, 11)]


class TesteFrequencia(unittest.TestCase):
    def test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste.db"
            controle = ControleAcademico(persistente=True, caminho_banco=caminho)
            disciplina = controle.criar_disciplina("D", "Teste", 1, 2, [DIAS[0]])
            disciplina.registrar_presenca(DIAS[0], "ausente")
            controle.adicionar_atividade("D", DIAS[1], "prova", "P1")
            with database.conexao(caminho) as banco:
                banco.execute("""
                    CREATE TRIGGER impedir_reset BEFORE DELETE ON registros
                    BEGIN SELECT RAISE(ABORT, 'falha simulada'); END
                """)
            with self.assertRaises(sqlite3.IntegrityError):
                controle.apagar_tudo()
            self.assertEqual(len(controle.disciplinas), 1)
            self.assertEqual(len(controle.atividades), 1)
            reaberto = ControleAcademico(persistente=True, caminho_banco=caminho)
            self.assertEqual(reaberto.obter_disciplina("D").resumo()["faltas"], 2)
            self.assertEqual(len(reaberto.atividades), 1)
            with database.conexao(caminho) as banco:
                banco.execute("DROP TRIGGER impedir_reset")
            controle.apagar_tudo()
            self.assertEqual((controle.disciplinas, controle.atividades), ((), ()))
            reaberto = ControleAcademico(persistente=True, caminho_banco=caminho)
            self.assertEqual((reaberto.disciplinas, reaberto.atividades), ((), ()))
            reaberto.criar_disciplina("D", "Novo começo", 1, 2, [DIAS[0]])

    def test_renomear_disciplina_valida_e_persiste(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste.db"
            controle = ControleAcademico(persistente=True, caminho_banco=caminho)
            disciplina = controle.criar_disciplina("DEMO01", "Nome antigo", 1, 2, DIAS)
            disciplina.registrar_presenca(DIAS[0], "ausente")
            controle.adicionar_atividade("DEMO01", date(2026, 11, 3), "prova", "P1")
            grade_antes = disciplina.registros
            resumo_antes = disciplina.resumo()
            atividades_antes = controle.atividades
            disciplina.nome = " Nome pelo setter "
            controle.disciplinas[0].nome = "Nome pela lista"
            controle.obter_disciplina("DEMO01").nome = "Nome pela busca"
            self.assertEqual(
                ControleAcademico(persistente=True, caminho_banco=caminho)
                .obter_disciplina("DEMO01")
                .nome,
                "Nome pela busca",
            )
            controle.renomear_disciplina("demo01", " Nome novo ")
            self.assertEqual(disciplina.nome, "Nome novo")
            self.assertEqual(disciplina.registros, grade_antes)
            self.assertEqual(disciplina.resumo(), resumo_antes)
            self.assertEqual(controle.atividades, atividades_antes)
            reaberto = ControleAcademico(persistente=True, caminho_banco=caminho)
            self.assertEqual(reaberto.obter_disciplina("DEMO01").nome, "Nome novo")
            self.assertEqual(reaberto.obter_disciplina("DEMO01").registros, grade_antes)
            self.assertEqual(reaberto.obter_disciplina("DEMO01").resumo(), resumo_antes)
            self.assertEqual(reaberto.atividades, atividades_antes)
            with self.assertRaises(AttributeError):
                disciplina.codigo = "OUTRA"

    def test_renomear_invalido_ou_falha_de_banco_preserva_nome(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste.db"
            controle = ControleAcademico(persistente=True, caminho_banco=caminho)
            disciplina = controle.criar_disciplina("DEMO01", "Original", 1, 2, DIAS)
            with self.assertRaisesRegex(ValueError, "não encontrada"):
                controle.renomear_disciplina("OUTRA", "Novo")
            self.assertEqual(disciplina.nome, "Original")
            self.assertEqual(
                ControleAcademico(persistente=True, caminho_banco=caminho)
                .obter_disciplina("DEMO01")
                .nome,
                "Original",
            )
            for invalido in ("", "   ", None):
                with self.subTest(invalido=invalido):
                    with self.assertRaises(ValueError):
                        controle.renomear_disciplina("DEMO01", invalido)
                    with self.assertRaises(ValueError):
                        disciplina.nome = invalido
                    self.assertEqual(disciplina.nome, "Original")
                    self.assertEqual(
                        ControleAcademico(persistente=True, caminho_banco=caminho)
                        .obter_disciplina("DEMO01")
                        .nome,
                        "Original",
                    )
            puro = Disciplina("D", "Original", 1, 2, DIAS)
            with self.assertRaises(ValueError):
                puro.nome = " "
            self.assertEqual(puro.nome, "Original")
            with (
                patch(
                    "database.atualizar_nome", side_effect=OSError("disco indisponível")
                ),
                self.assertRaises(OSError),
            ):
                controle.renomear_disciplina("DEMO01", "Novo")
            self.assertEqual(
                ControleAcademico(persistente=True, caminho_banco=caminho)
                .obter_disciplina("DEMO01")
                .nome,
                "Original",
            )
            with (
                patch(
                    "database.atualizar_nome", side_effect=OSError("disco indisponível")
                ),
                self.assertRaises(OSError),
            ):
                disciplina.nome = "Novo"
            self.assertEqual(disciplina.nome, "Original")
            self.assertEqual(
                ControleAcademico(persistente=True, caminho_banco=caminho)
                .obter_disciplina("DEMO01")
                .nome,
                "Original",
            )

    def test_nome_inexistente_no_banco_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste.db"
            database.inicializar_banco(caminho)
            with self.assertRaises(ValueError):
                database.atualizar_nome("OUTRA", "Nome", caminho)
            self.assertEqual(database.listar_disciplinas(caminho), [])

    def test_falha_no_segundo_insert_desfaz_cadastro_e_grade(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste.db"
            controle = ControleAcademico(persistente=True, caminho_banco=caminho)
            with database.conexao(caminho) as banco:
                banco.execute("""
                    CREATE TRIGGER falhar_grade BEFORE INSERT ON registros
                    WHEN NEW.dia = '2026-11-04'
                    BEGIN SELECT RAISE(FAIL, 'falha injetada'); END
                """)
            with self.assertRaises(sqlite3.IntegrityError):
                controle.criar_disciplina("DEMO01", "Teste", 1, 2, DIAS[:2])
            self.assertEqual(controle.disciplinas, ())
            self.assertEqual(database.listar_disciplinas(caminho), [])

    def test_atividade_valida_persiste_sem_alterar_frequencia(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste.db"
            controle = ControleAcademico(persistente=True, caminho_banco=caminho)
            disciplina = controle.criar_disciplina("DEMO01", "Teste", 1, 2, DIAS)
            antes = (disciplina.registros, disciplina.resumo())
            atividade = controle.adicionar_atividade(
                "demo01", date(2026, 11, 3), "prova", "P1"
            )
            self.assertEqual(
                (atividade.codigo_disciplina, atividade.titulo), ("DEMO01", "P1")
            )
            self.assertEqual(atividade.dia, date(2026, 11, 3))
            self.assertEqual((disciplina.registros, disciplina.resumo()), antes)
            reaberto = ControleAcademico(persistente=True, caminho_banco=caminho)
            self.assertEqual(reaberto.atividades, (atividade,))
            self.assertEqual(reaberto.obter_disciplina("DEMO01").resumo(), antes[1])

    def test_atividade_invalida_e_falha_de_escrita_preservam_agenda(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste.db"
            controle = ControleAcademico(persistente=True, caminho_banco=caminho)
            disciplina = controle.criar_disciplina("DEMO01", "Teste", 1, 2, DIAS)
            frequencia_antes = (disciplina.registros, disciplina.resumo())
            for codigo, dia, tipo, titulo in [
                ("OUTRA", DIAS[0], "prova", "P1"),
                ("DEMO01", "02/11/2026", "prova", "P1"),
                ("DEMO01", DIAS[0], "seminário", "P1"),
                ("DEMO01", DIAS[0], "prova", "   "),
            ]:
                with self.subTest(codigo=codigo, dia=dia, tipo=tipo, titulo=titulo):
                    with self.assertRaises(ValueError):
                        controle.adicionar_atividade(codigo, dia, tipo, titulo)
                    self.assertEqual(controle.atividades, ())
                    self.assertEqual(
                        (disciplina.registros, disciplina.resumo()), frequencia_antes
                    )
            with (
                patch(
                    "database.salvar_atividade",
                    side_effect=OSError("disco indisponível"),
                ),
                self.assertRaises(OSError),
            ):
                controle.adicionar_atividade("DEMO01", DIAS[0], "prova", "P1")
            self.assertEqual(controle.atividades, ())
            self.assertEqual(
                (disciplina.registros, disciplina.resumo()), frequencia_antes
            )
            self.assertEqual(
                ControleAcademico(persistente=True, caminho_banco=caminho).atividades,
                (),
            )

    def test_correcao_invalida_preserva_registro_e_resumo(self):
        disciplina = Disciplina("D", "Teste", 2, 2, DIAS)
        inicial = (disciplina.registros, disciplina.resumo())
        with self.assertRaisesRegex(ValueError, "pendente"):
            disciplina.registrar_presenca(DIAS[0], "presente", corrigir=True)
        self.assertEqual((disciplina.registros, disciplina.resumo()), inicial)
        disciplina.registrar_presenca(DIAS[0], "ausente")
        antes = (disciplina.registros, disciplina.resumo())
        with self.assertRaises(ValueError):
            disciplina.registrar_presenca(DIAS[0], "desconhecida", corrigir=True)
        self.assertEqual((disciplina.registros, disciplina.resumo()), antes)
        with self.assertRaises(ValueError):
            disciplina.registrar_presenca(date(2026, 12, 1), "presente", corrigir=True)
        self.assertEqual((disciplina.registros, disciplina.resumo()), antes)

    def test_consulta_nao_altera_registros(self):
        controle = ControleAcademico()
        disciplina = controle.criar_disciplina("D", "Teste", 1, 2, DIAS)
        antes = (disciplina.registros, disciplina.resumo())
        self.assertEqual(controle.obter_disciplina("d").resumo(), antes[1])
        self.assertEqual((disciplina.registros, disciplina.resumo()), antes)
        with self.assertRaises(ValueError):
            controle.obter_disciplina("OUTRA")
        for codigo in (None, 123, "", "  "):
            with (
                self.subTest(codigo=codigo),
                self.assertRaisesRegex(ValueError, "Informe o código"),
            ):
                controle.obter_disciplina(codigo)
        self.assertEqual(
            (controle.disciplinas, disciplina.registros, disciplina.resumo()),
            ((disciplina,), *antes),
        )

    def test_sqlite_preserva_disciplina_entre_aberturas(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste.db"
            primeiro = ControleAcademico(persistente=True, caminho_banco=caminho)
            disciplina = primeiro.criar_disciplina(
                "DB01", "Persistente", 1, 1, [DIAS[0]]
            )
            primeiro.disciplinas[0].registrar_presenca(DIAS[0], "presente")
            self.assertEqual(disciplina.registros[0].situacao, "presente")
            segundo = ControleAcademico(persistente=True, caminho_banco=caminho)
            recuperada = segundo.obter_disciplina("DB01")
            self.assertEqual(recuperada.nome, "Persistente")
            self.assertEqual(recuperada.registros[0].situacao, "presente")

    def test_falha_na_gravacao_preserva_memoria_e_banco(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste.db"
            controle = ControleAcademico(persistente=True, caminho_banco=caminho)
            disciplina = controle.criar_disciplina("DB02", "Teste", 1, 2, [DIAS[0]])
            antes = (disciplina.registros, disciplina.resumo())
            with (
                patch(
                    "database.salvar_registro",
                    side_effect=OSError("disco indisponível"),
                ),
                self.assertRaises(OSError),
            ):
                disciplina.registrar_presenca(DIAS[0], "ausente")
            self.assertEqual((disciplina.registros, disciplina.resumo()), antes)
            reaberto = ControleAcademico(persistente=True, caminho_banco=caminho)
            self.assertEqual(
                reaberto.obter_disciplina("DB02").registros[0].situacao, "pendente"
            )

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
            ("D", "T", 1, 2, None),
            ("D", "T", 1, 2, 123),
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
