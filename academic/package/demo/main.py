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


def mostrar(disciplina):
    """Exibe a grade e os totais calculados no estado atual da disciplina."""
    print(f"{disciplina.codigo} - {disciplina.nome} ({disciplina.chamadas} chamada(s))")
    for r in disciplina.registros:
        faltas = "-" if r.faltas is None else str(r.faltas)
        print(f"{r.dia:%d/%m/%Y} | {r.aulas} aulas | {r.situacao} | faltas: {faltas}")
    resumo = disciplina.resumo()
    print(f"Base: {resumo['aulas']} aulas | Pendentes: {resumo['pendentes']}")
    print(
        f"Faltas: {resumo['faltas']} | Limite: {resumo['limite']} | "
        f"Restantes: {resumo['restantes']}"
    )
    if resumo["excesso"]:
        print(f"Limite excedido em {resumo['excesso']} aula(s).")
    percentual = resumo["frequencia"]
    print(
        "Frequência: pendente"
        if percentual is None
        else f"Frequência: {percentual:.1f}%"
    )


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
            if controle.disciplinas:
                nomes = ", ".join(
                    f"{disciplina.codigo} — {disciplina.nome}"
                    for disciplina in controle.disciplinas
                )
                print(f"Disciplinas: {nomes}")
            print(
                "\n1 Criar disciplina | 2 Registrar presença | 3 Consultar"
                " | 4 Corrigir registro | 5 Adicionar atividade"
                " | 6 Ver agenda | 7 Renomear disciplina | 0 Sair"
            )
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
                disciplina = controle.obter_disciplina(input("Código da disciplina: "))
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
                atividade = controle.adicionar_atividade(
                    input("Código da disciplina: "),
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
                    print(
                        f"{atividade.dia:%d/%m/%Y} | {atividade.codigo_disciplina} | "
                        f"{atividade.tipo} | {atividade.titulo}"
                    )
                continue
            elif acao == "7":
                disciplina = controle.renomear_disciplina(
                    input("Código da disciplina: "), input("Novo nome: ")
                )
                print("Disciplina renomeada.")
            else:
                raise ValueError("Escolha uma opção de 0 a 7.")
            mostrar(disciplina)
        except ValueError as erro:
            print(f"Operação rejeitada: {erro}")
        except (sqlite3.Error, OSError) as erro:
            # A operação de domínio só publica o novo estado após o commit.
            # Mostramos o problema sem encerrar o menu nem fingir que salvou.
            print(f"Não foi possível salvar no banco; nada foi alterado: {erro}")
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrado.")
            return


if __name__ == "__main__":
    executar()
