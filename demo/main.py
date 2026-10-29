"""Interface de terminal. Execute: python main.py (Python3.11+; sem instalações)."""

from datetime import date

from models import (
    ChamadaDupla,
    ChamadaUnica,
    Disciplina,
    Evidencia,
    Momento,
    SessaoAula,
    Situacao,
)


def preparar_dados():
    """Objetos novos por execução: códigos, nomes e sessões totalmente fictícios."""
    disciplinas = []
    for codigo, politica in [("DEMO01", ChamadaUnica()), ("DEMO02", ChamadaDupla())]:
        sessoes = [
            SessaoAula("S1", date(2026, 10, 20), 4, politica),
            SessaoAula("S2", date(2026, 10, 22), 2, politica),
            SessaoAula("S3", date(2026, 10, 27), 2, politica, "sem_chamada"),
            SessaoAula("S4", date(2026, 10, 29), 2, politica, "cancelada"),
        ]
        disciplinas.append(Disciplina(codigo, f"Disciplina fictícia {codigo}", sessoes))
    return disciplinas


def escolher(rotulo, opcoes):
    """Interprete um índice; conversão inválida é tratada pelo laço principal."""
    for indice, (texto, _) in enumerate(opcoes, 1):
        print(f"{indice}. {texto}")
    indice = int(input(f"{rotulo}: "))
    if not 1 <= indice <= len(opcoes):
        raise ValueError("Opção fora da lista.")
    return opcoes[indice - 1][1]


def mostrar_sessoes(disciplina):
    """Apresente o estado recebido do domínio, sem alterá-lo."""
    print(f"\n{disciplina.codigo} — {disciplina.nome}")
    for s in disciplina.sessoes:
        r = s.registro
        faltas = "não definidas" if r.faltas is None else str(r.faltas)
        print(
            f"{s.identificador} | {s.dia:%d/%m/%Y} | {s.aulas} aulas | {s.modalidade} | "
            f"{s.natureza} | {r.situacao.value} | faltas: {faltas} | manual: {r.manual}"
        )
        for momento, evidencia in s.pings:
            print(f"  {momento.value}: {evidencia.value}")


def mostrar_resumo(disciplina):
    """Separe unidades confirmadas, pendentes e ausentes; não invente percentual."""
    r = disciplina.resumo()
    print(
        f"Aulas elegíveis (50min): {r.aulas_elegiveis}; presenças: {r.aulas_presentes}; "
        f"pendentes: {r.aulas_pendentes}"
    )
    print(
        f"Faltas usadas: {r.faltas_consumidas}; limite: {r.limite_faltas}; "
        f"faltas restantes: {r.faltas_restantes}"
    )
    print(
        "Frequência final: pendente"
        if r.frequencia_percentual is None
        else f"Frequência final: {r.frequencia_percentual:.2f}%"
    )
    if r.excedeu_limite:
        print("ATENÇÃO: limite de faltas excedido.")


def executar():
    """Ponto de entrada: F01registrar evidência; F02corrigir; consultas apoiam ambos."""
    disciplinas = preparar_dados()
    print("Frequência UFMG — protótipo didático de POO")
    print("DADOS FICTÍCIOS. Pings SIMULADOS, sem GPS/login/rede. Controle pessoal.")
    print(
        "Alterações apenas em memória: ao sair, todos os dados da demo são reiniciados."
    )
    while True:
        try:
            print(
                "\n1 Consultar sessões | 2 Registrar ping | 3 Corrigir frequência"
                " | 4 Resumo | 0 Sair"
            )
            acao = input("Ação: ").strip()
            if acao == "0":
                print("Encerrado. Dados da demo descartados.")
                return
            if acao not in ("1", "2", "3", "4"):
                raise ValueError("Ação inválida.")
            disciplina = escolher("Disciplina", [(d.codigo, d) for d in disciplinas])
            if acao == "4":
                mostrar_resumo(disciplina)
                continue
            mostrar_sessoes(disciplina)
            if acao == "1":
                continue
            sessao = disciplina.obter_sessao(input("ID da sessão (ex.: S1): ").strip())
            if acao == "2":
                momento = escolher("Momento", [(m.value, m) for m in Momento])
                evidencia = escolher(
                    "Evidência SIMULADA", [(e.value, e) for e in Evidencia]
                )
                resultado = sessao.registrar_ping(momento, evidencia)
            else:
                situacao = escolher("Situação", [(s.value, s) for s in Situacao])
                faltas = (
                    None
                    if situacao == Situacao.PENDENTE
                    else int(input("Faltas (aulas de 50 min): "))
                )
                resultado = sessao.corrigir(situacao, faltas)
            print(
                f"Registro atualizado: {resultado.situacao.value}; faltas: {resultado.faltas}"
            )
            mostrar_resumo(disciplina)
        except ValueError as erro:
            print(f"Operação rejeitada: {erro} Estado anterior preservado.")
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrado. Dados da demo descartados.")
            return


if __name__ == "__main__":
    executar()
