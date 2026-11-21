"""Interface HTTP local para a mesma aplicação acadêmica de domínio e SQLite.

Execute ``python web.py`` e abra http://127.0.0.1:8878. Este módulo apenas
converte JSON e serve a apresentação: validação, cálculos e persistência ficam
em models.py e database.py. O servidor escuta só o próprio computador.
"""

import json
import os
import sqlite3
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from models import ControleAcademico

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
MAX_BODY = 64 * 1024


def ler_data(valor):
    """Converte uma data ISO vinda de um campo HTML em date para o domínio."""
    if not isinstance(valor, str):
        raise TypeError("Informe uma data válida.")
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValueError("Informe uma data válida.") from None


def estado(controle):
    """Expõe somente valores de leitura, calculados pelas classes Python."""
    disciplinas = []
    for disciplina in sorted(
        controle.disciplinas,
        key=lambda item: (item.nome.casefold(), item.codigo),
    ):
        disciplinas.append(
            {
                "codigo": disciplina.codigo,
                "nome": disciplina.nome,
                "chamadas": disciplina.chamadas,
                "registros": [
                    {
                        "dia": registro.dia.isoformat(),
                        "aulas": registro.aulas,
                        "situacao": registro.situacao,
                        "faltas": registro.faltas,
                    }
                    for registro in disciplina.registros
                ],
                "resumo": disciplina.resumo(),
            }
        )
    nomes = {item["codigo"]: item["nome"] for item in disciplinas}
    return {
        "disciplinas": disciplinas,
        "atividades": [
            {
                "id": atividade.identificador,
                "codigo_disciplina": atividade.codigo_disciplina,
                "nome_disciplina": nomes[atividade.codigo_disciplina],
                "dia": atividade.dia.isoformat(),
                "tipo": atividade.tipo,
                "titulo": atividade.titulo,
            }
            for atividade in controle.atividades
        ],
    }


def executar_acao(controle, rota, dados):
    """Encaminha uma ação ao domínio; não calcula faltas nem altera SQL."""
    if rota == "/api/disciplinas":
        if not isinstance(dados.get("datas"), list):
            raise ValueError("Adicione ao menos uma data de aula.")
        controle.criar_disciplina(
            dados.get("codigo"),
            dados.get("nome"),
            dados.get("chamadas"),
            dados.get("aulas"),
            [ler_data(valor) for valor in dados["datas"]],
        )
    elif rota == "/api/registros":
        corrigir = dados.get("corrigir", False)
        if type(corrigir) is not bool:
            raise ValueError("A correção deve ser indicada como verdadeiro ou falso.")
        controle.obter_disciplina(dados.get("codigo")).registrar_presenca(
            ler_data(dados.get("dia")),
            dados.get("situacao"),
            corrigir=corrigir,
        )
    elif rota == "/api/atividades":
        controle.adicionar_atividade(
            dados.get("codigo"),
            ler_data(dados.get("dia")),
            dados.get("tipo"),
            dados.get("titulo"),
        )
    elif rota == "/api/renomear":
        controle.renomear_disciplina(dados.get("codigo"), dados.get("nome"))
    elif rota == "/api/remarcar":
        controle.remarcar_encontro(
            dados.get("codigo"),
            ler_data(dados.get("dia_anterior")),
            ler_data(dados.get("novo_dia")),
        )
    elif rota == "/api/reset":
        if dados.get("confirmacao") != "APAGAR":
            raise ValueError("Digite APAGAR para confirmar.")
        controle.apagar_tudo()
    else:
        raise LookupError("Ação inexistente.")


class DemoHandler(BaseHTTPRequestHandler):
    """Serve três arquivos locais e cinco ações JSON sem dependência externa."""

    caminho_banco = None

    def responder(self, codigo, corpo, tipo="application/json; charset=utf-8"):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(corpo)

    def json(self, codigo, dados):
        self.responder(codigo, json.dumps(dados, ensure_ascii=False).encode("utf-8"))

    def controle(self):
        # Reabrir o SQLite por pedido também enxerga alterações feitas no terminal.
        return ControleAcademico(persistente=True, caminho_banco=self.caminho_banco)

    def do_GET(self):
        rota = urlsplit(self.path).path
        if rota == "/api/estado":
            try:
                self.json(200, estado(self.controle()))
            except (sqlite3.Error, OSError, ValueError) as erro:
                self.json(503, {"erro": f"Não foi possível carregar os dados: {erro}"})
            return
        if rota in ASSETS:
            nome, tipo = ASSETS[rota]
            self.responder(
                200, (Path(__file__).with_name("web") / nome).read_bytes(), tipo
            )
            return
        self.json(404, {"erro": "Página não encontrada."})

    def do_POST(self):
        rota = urlsplit(self.path).path
        if rota not in {
            "/api/disciplinas",
            "/api/registros",
            "/api/atividades",
            "/api/renomear",
            "/api/remarcar",
            "/api/reset",
        }:
            self.json(404, {"erro": "Ação inexistente."})
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.json(415, {"erro": "Envie os dados em JSON."})
            return
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            if not 0 < tamanho <= MAX_BODY:
                raise ValueError("Pedido vazio ou grande demais.")
            dados = json.loads(self.rfile.read(tamanho))
            if not isinstance(dados, dict):
                raise TypeError("Informe um objeto de dados válido.")
            controle = self.controle()
            executar_acao(controle, rota, dados)
            self.json(200, estado(controle))
        except (TypeError, ValueError) as erro:
            self.json(400, {"erro": str(erro)})
        except (sqlite3.Error, OSError) as erro:
            self.log_error("Falha de persistência em %s: %s", rota, erro)
            self.json(503, {"erro": f"Não foi possível salvar os dados: {erro}"})


def criar_servidor(caminho_banco=None, porta=8878):
    """Cria servidor restrito a 127.0.0.1, permitindo porta 0 nos testes."""

    class Handler(DemoHandler):
        pass

    Handler.caminho_banco = caminho_banco or os.environ.get("FREQUENCIA_DB_PATH")
    return ThreadingHTTPServer(("127.0.0.1", porta), Handler)


if __name__ == "__main__":
    with criar_servidor() as servidor:
        print("Frequência UFMG: http://127.0.0.1:8878")
        print("Use Ctrl+C para encerrar. Os dados ficam no SQLite local.")
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nEncerrado.")
