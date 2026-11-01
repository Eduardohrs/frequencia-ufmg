"""Menu de terminal: python main.py. Começa sem disciplinas cadastradas."""

from datetime import datetime

from models import SITUACOES, ControleAcademico


def ler_data(texto):
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date()
    except ValueError:
        raise ValueError("Use uma data válida no formato DD/MM/AAAA.") from None


def ler_inteiro(rotulo):
    try:
        return int(input(rotulo))
    except ValueError:
        raise ValueError("Informe um número inteiro.") from None


def mostrar(disciplina):
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
    controle = ControleAcademico()
    print("Frequência UFMG - protótipo de POO")
    print("Cadastro vazio. Dados em memória; ao sair, as alterações são perdidas.")
    while True:
        try:
            print(
                "\n1 Criar disciplina | 2 Registrar presença | 3 Consultar"
                " | 4 Corrigir registro | 0 Sair"
            )
            acao = input("Ação: ").strip()
            if acao == "0":
                print("Encerrado.")
                return
            if acao == "1":
                codigo = input("Código: ")
                nome = input("Nome: ")
                chamadas = ler_inteiro("Chamadas por encontro (1 ou 2): ")
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
            else:
                raise ValueError("Escolha uma opção de 0 a 4.")
            mostrar(disciplina)
        except ValueError as erro:
            print(f"Operação rejeitada: {erro}")
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrado.")
            return


if __name__ == "__main__":
    executar()
