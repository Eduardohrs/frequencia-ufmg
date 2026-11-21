"""Menu de terminal: python main.py. O banco local preserva a sessão entre aberturas."""

import os
import sqlite3
from datetime import datetime

from models import SITUACOES, ControleAcademico


def ler_data(texto):
    """Converte DD/MM/AAAA em data; recusa datas impossíveis e texto inválido."""
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date()
    except ValueError:
        raise ValueError("Use uma data válida no formato DD/MM/AAAA.") from None


def ler_inteiro(rotulo):
    """Lê uma quantidade inteira; o domínio valida os valores permitidos."""
    try:
        return int(input(rotulo))
    except ValueError:
        raise ValueError("Informe um número inteiro.") from None


def formatar_aulas(valor):
    """Mostra a unidade dos totais, inclusive no singular."""
    return f"{valor} {'aula' if valor == 1 else 'aulas'}"


def mostrar(disciplina):
    """Exibe a grade e os totais calculados no estado atual da disciplina."""
    chamadas = (
        f"{disciplina.chamadas} {'chamada' if disciplina.chamadas == 1 else 'chamadas'}"
    )
    print(f"{disciplina.nome} ({disciplina.codigo}; {chamadas})")
    for r in disciplina.registros:
        faltas = "-" if r.faltas is None else str(r.faltas)
        print(
            f"{r.dia:%d/%m/%Y} | {formatar_aulas(r.aulas)} | "
            f"{r.situacao} | faltas: {faltas}"
        )
    resumo = disciplina.resumo()
    print(
        f"Base: {formatar_aulas(resumo['aulas'])} | "
        f"Pendentes: {formatar_aulas(resumo['pendentes'])}"
    )
    print(
        f"Faltas: {formatar_aulas(resumo['faltas'])} | "
        f"Limite: {formatar_aulas(resumo['limite'])} | "
        f"Restantes: {formatar_aulas(resumo['restantes'])}"
    )
    if resumo["excesso"]:
        print(f"Limite excedido em {formatar_aulas(resumo['excesso'])}.")
    percentual = resumo["frequencia"]
    print(
        "Frequência: pendente"
        if percentual is None
        else f"Frequência: {percentual:.1f}%"
    )


def escolher_disciplina(controle):
    """Mostra nomes numerados e devolve a disciplina escolhida ou None.

    O código continua visível como referência, mas o estudante não precisa
    decorá-lo nem digitá-lo. Zero volta ao menu sem alterar dados.
    """
    disciplinas = sorted(
        controle.disciplinas,
        key=lambda disciplina: (disciplina.nome.casefold(), disciplina.codigo),
    )
    if not disciplinas:
        print("Nenhuma disciplina cadastrada. Escolha 1 para criar uma.")
        return None
    print("Escolha a disciplina:")
    for numero, disciplina in enumerate(disciplinas, 1):
        print(f"{numero} {disciplina.nome} ({disciplina.codigo})")
    print("0 Voltar ao menu")
    escolha = input("Número: ").strip()
    if escolha == "0":
        return None
    if not escolha.isdecimal() or not 1 <= int(escolha) <= len(disciplinas):
        raise ValueError("Escolha um número da lista ou 0 para voltar.")
    return disciplinas[int(escolha) - 1]


def executar():
    """Conduz o menu; cada opção chama uma operação de domínio independente.

    O arquivo SQLite é reaberto a cada execução. O tratamento de erros mantém
    o menu disponível e explica uma rejeição sem inventar um salvamento.
    """
    try:
        controle = ControleAcademico(
            persistente=True,
            caminho_banco=os.environ.get("FREQUENCIA_DB_PATH"),
        )
    except (sqlite3.Error, OSError) as erro:
        print(f"Não foi possível abrir o banco local: {erro}")
        return
    print("Frequência UFMG - produto acadêmico")
    print(
        "Os dados ficam em SQLite local e continuam disponíveis ao reabrir o programa."
    )
    while True:
        try:
            if not controle.disciplinas:
                print("Nenhuma disciplina cadastrada.")
            print(
                "\n1 Criar disciplina | 2 Registrar presença | 3 Consultar frequência"
            )
            print("4 Corrigir registro | 5 Adicionar atividade | 6 Ver agenda")
            print("7 Renomear disciplina | 8 Recomeçar do zero | 0 Sair")
            acao = input("Ação: ").strip()
            if acao == "0":
                print("Encerrado.")
                return
            if acao == "1":
                codigo = input("Código: ")
                nome = input("Nome: ")
                chamadas = ler_inteiro(
                    "Chamadas por encontro (1: encontro inteiro; 2: início e fim): "
                )
                aulas = ler_inteiro("Aulas de 50 min por encontro (1, 2 ou 4): ")
                datas = [
                    ler_data(d)
                    for d in input(
                        "Datas das aulas (DD/MM/AAAA, separadas por vírgula): "
                    ).split(",")
                ]
                disciplina = controle.criar_disciplina(
                    codigo, nome, chamadas, aulas, datas
                )
                print("Disciplina criada.")
            elif acao in ("2", "3", "4"):
                disciplina = escolher_disciplina(controle)
                if disciplina is None:
                    continue
                if acao != "3":
                    dia = ler_data(input("Data da aula (DD/MM/AAAA): "))
                    print("Situações: " + ", ".join(SITUACOES))
                    situacao = input("Situação: ").strip().lower()
                    registro = disciplina.registrar_presenca(
                        dia, situacao, corrigir=acao == "4"
                    )
                    print(
                        f"Registro salvo: {registro.situacao}; faltas: {registro.faltas}."
                    )
            elif acao == "5":
                disciplina = escolher_disciplina(controle)
                if disciplina is None:
                    continue
                atividade = controle.adicionar_atividade(
                    disciplina.codigo,
                    ler_data(input("Data da atividade (DD/MM/AAAA): ")),
                    input("Tipo (prova ou trabalho): ").strip().lower(),
                    input("Título: "),
                )
                print(
                    f"Atividade salva: {atividade.titulo} ({atividade.dia:%d/%m/%Y})."
                )
                continue
            elif acao == "6":
                if not controle.atividades:
                    print("Agenda vazia.")
                for atividade in controle.atividades:
                    disciplina = controle.obter_disciplina(atividade.codigo_disciplina)
                    print(
                        f"{atividade.dia:%d/%m/%Y} | {disciplina.nome} ({disciplina.codigo}) | "
                        f"{atividade.tipo} | {atividade.titulo}"
                    )
                continue
            elif acao == "7":
                disciplina = escolher_disciplina(controle)
                if disciplina is None:
                    continue
                disciplina = controle.renomear_disciplina(
                    disciplina.codigo, input("Novo nome: ")
                )
                print("Disciplina renomeada.")
            elif acao == "8":
                print(
                    "Isso apaga TODAS as disciplinas, presenças e atividades desta demo."
                )
                confirmacao = input(
                    "Digite APAGAR para confirmar (ou Enter para voltar): "
                )
                if confirmacao != "APAGAR":
                    print("Cancelado. Nenhum dado foi alterado.")
                    continue
                controle.apagar_tudo()
                print("Dados apagados. Você pode criar uma nova disciplina.")
                continue
            else:
                raise ValueError("Escolha uma opção de 0 a 8.")
            mostrar(disciplina)
        except ValueError as erro:
            print(f"Operação rejeitada: {erro}")
        except (sqlite3.Error, OSError) as erro:
            # A operação de domínio só publica o novo estado após o commit.
            # Mostramos o problema sem encerrar o menu nem fingir que salvou.
            print(f"Não foi possível concluir no banco; nada foi alterado: {erro}")
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrado.")
            return


if __name__ == "__main__":
    executar()
