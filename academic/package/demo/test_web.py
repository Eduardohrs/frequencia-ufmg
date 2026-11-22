"""Percorre a interface HTTP real com banco temporário, sem tocar na demo."""

import io
import json
import runpy
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from web import criar_servidor, executar_acao


class InterfaceWebTest(unittest.TestCase):
    def test_botoes_exemplo_e_testes_nao_exigem_preparo(self):
        status, state = self.post("/api/exemplo", {})
        self.assertEqual(status, 200)
        self.assertEqual(state["disciplinas"][0]["codigo"], "DEMO01")
        self.assertEqual(state["disciplinas"][0]["resumo"]["faltas"], 2)
        self.assertEqual(len(state["atividades"]), 1)
        self.assertEqual(self.post("/api/exemplo", {})[0], 400)
        self.assertEqual(self.post("/api/reset", {"confirmacao": "APAGAR"})[0], 200)
        self.assertEqual(self.post("/api/exemplo", {})[0], 200)

        with patch(
            "subprocess.run",
            return_value=SimpleNamespace(
                returncode=0, stdout="", stderr="Ran 25 tests in 1.0s\n\nOK\n"
            ),
        ) as executar:
            status, body = self.post("/api/testes", {})
        self.assertEqual((status, body["ok"], body["quantidade"]), (200, True, 25))
        self.assertEqual(executar.call_args.kwargs["cwd"], Path(__file__).parent)
        with patch(
            "subprocess.run",
            return_value=SimpleNamespace(returncode=1, stdout="", stderr="FAILED"),
        ):
            status, body = self.post("/api/testes", {})
        self.assertEqual((status, body["ok"], body["quantidade"]), (200, False, None))
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("test", 60)):
            status, body = self.post("/api/testes", {})
        self.assertEqual(status, 503)
        self.assertIn("um minuto", body["erro"])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.server = criar_servidor(Path(self.temporary.name) / "web.db", 0)
        self.server.RequestHandlerClass.log_message = lambda *args: None
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def get(self, route):
        try:
            with urlopen(self.url + route, timeout=5) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def post(self, route, payload, content_type="application/json"):
        request = Request(
            self.url + route,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_fluxo_completo_e_reabertura(self):
        status, page = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Suas disciplinas", page)
        for asset in ("/app.css", "/app.js"):
            self.assertEqual(self.get(asset)[0], 200)
        status, state = self.post(
            "/api/disciplinas",
            {
                "codigo": "demo01",
                "nome": "Circuitos",
                "chamadas": 2,
                "aulas": 2,
                "datas": ["2026-11-02", "2026-11-04", "2026-11-09", "2026-11-11"],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(state["disciplinas"][0]["resumo"]["pendentes"], 8)
        self.assertEqual(state["disciplinas"][0]["codigo"], "DEMO01")

        status, state = self.post(
            "/api/registros",
            {
                "codigo": "DEMO01",
                "dia": "2026-11-02",
                "situacao": "ausente",
                "corrigir": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(state["disciplinas"][0]["resumo"]["faltas"], 2)
        status, state = self.post(
            "/api/registros",
            {
                "codigo": "DEMO01",
                "dia": "2026-11-02",
                "situacao": "presente",
                "corrigir": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(state["disciplinas"][0]["resumo"]["faltas"], 0)
        status, state = self.post(
            "/api/atividades",
            {"codigo": "DEMO01", "dia": "2026-11-10", "tipo": "prova", "titulo": "P1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(state["atividades"][0]["nome_disciplina"], "Circuitos")
        status, state = self.post(
            "/api/renomear", {"codigo": "DEMO01", "nome": "Circuitos 2"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(state["atividades"][0]["nome_disciplina"], "Circuitos 2")

        # Novo pedido reconstrói o domínio a partir do SQLite, como reabrir o site.
        _, saved = self.get("/api/estado")
        saved = json.loads(saved)
        self.assertEqual(saved["disciplinas"][0]["nome"], "Circuitos 2")
        self.assertEqual(
            saved["disciplinas"][0]["registros"][0]["situacao"], "presente"
        )
        self.assertEqual(saved["disciplinas"][0]["registros"][0]["dia"], "2026-11-02")
        self.assertEqual(saved["atividades"][0]["titulo"], "P1")

        status, state = self.post("/api/reset", {"confirmacao": "APAGAR"})
        self.assertEqual(status, 200)
        self.assertEqual(state, {"disciplinas": [], "atividades": []})
        self.assertEqual(json.loads(self.get("/api/estado")[1]), state)

    def test_entradas_invalidas_preservam_estado(self):
        self.post(
            "/api/disciplinas",
            {
                "codigo": "D1",
                "nome": "Teste",
                "chamadas": 1,
                "aulas": 2,
                "datas": ["2026-11-02"],
            },
        )
        before = json.loads(self.get("/api/estado")[1])
        for route, payload, status in (
            (
                "/api/registros",
                {"codigo": "D1", "dia": "2026-11-03", "situacao": "ausente"},
                400,
            ),
            (
                "/api/registros",
                {"codigo": "D1", "dia": None, "situacao": "ausente"},
                400,
            ),
            (
                "/api/registros",
                {
                    "codigo": "D1",
                    "dia": "2026-11-02",
                    "situacao": "ausente",
                    "corrigir": "sim",
                },
                400,
            ),
            (
                "/api/atividades",
                {"codigo": "D1", "dia": "xxx", "tipo": "prova", "titulo": "P1"},
                400,
            ),
            ("/api/disciplinas", {"codigo": "D2", "datas": "2026-11-02"}, 400),
            ("/api/reset", {"confirmacao": "apagar"}, 400),
            ("/api/reset", [], 400),
        ):
            with self.subTest(route=route):
                code, body = self.post(route, payload)
                self.assertEqual(code, status)
                self.assertIn("erro", body)
                self.assertEqual(json.loads(self.get("/api/estado")[1]), before)
        self.assertEqual(self.post("/api/reset", {}, "text/plain")[0], 415)
        self.assertEqual(self.post("/api/nao-existe", {})[0], 404)
        self.assertEqual(self.get("/nao-existe")[0], 404)
        empty = Request(
            self.url + "/api/reset",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(empty, timeout=5)
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(LookupError):
            executar_acao(None, "/api/nao-existe", {})

    def test_falhas_de_leitura_e_gravacao_sao_visiveis(self):
        handler = self.server.RequestHandlerClass
        with patch.object(
            handler, "controle", side_effect=sqlite3.OperationalError("disco")
        ):
            status, body = self.get("/api/estado")
        self.assertEqual(status, 503)
        self.assertIn("disco", json.loads(body)["erro"])
        with patch.object(handler, "controle", side_effect=OSError("disco")):
            status, body = self.post("/api/reset", {"confirmacao": "APAGAR"})
        self.assertEqual(status, 503)
        self.assertIn("disco", body["erro"])

    def test_ponto_de_entrada_pode_ser_encerrado(self):
        class ServidorFalso:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def serve_forever(self):
                raise KeyboardInterrupt

        with (
            patch("http.server.ThreadingHTTPServer", return_value=ServidorFalso()),
            patch("sys.stdout", new_callable=io.StringIO) as output,
            patch("webbrowser.open") as browser,
        ):
            output.isatty = lambda: True
            runpy.run_path(str(Path(__file__).with_name("web.py")), run_name="__main__")
        self.assertIn("http://127.0.0.1:8878", output.getvalue())
        self.assertIn("Encerrado", output.getvalue())
        browser.assert_called_once_with("http://127.0.0.1:8878")


if __name__ == "__main__":
    unittest.main()
