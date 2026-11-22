"""Domínio e coordenação do Frequência UFMG acadêmico.

Uma aula equivale a 50 minutos. As classes validam e calculam o estado; o
ControleAcademico coordena as operações. SQL e teclado ficam em outros módulos.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import database

SITUACOES = (
    "presente",
    "ausente",
    "atrasado",
    "saiu mais cedo",
    "cancelada",
    "sem chamada",
)


class PoliticaChamada(ABC):
    """Contrato comum para políticas de chamada diferentes.

    A disciplina usa sempre ``calcular_faltas``. A subclasse escolhida muda o
    resultado, demonstrando polimorfismo sem espalhar condições pelo domínio.
    """

    @abstractmethod
    def calcular_faltas(self, situacao: str, aulas: int) -> int:
        """Retorna faltas em unidades de 50 minutos."""


class ChamadaUnica(PoliticaChamada):
    """Uma chamada registra o encontro inteiro; atraso não fraciona faltas."""

    def calcular_faltas(self, situacao, aulas):
        """Ausência perde o encontro inteiro; demais situações não geram falta."""
        return aulas if situacao == "ausente" else 0


class ChamadaDupla(PoliticaChamada):
    """Duas chamadas representam início e fim; atraso/saída perde metade."""

    def calcular_faltas(self, situacao, aulas):
        """Ausência perde tudo; atraso ou saída perde metade das aulas."""
        if situacao == "ausente":
            return aulas
        return aulas // 2 if situacao in ("atrasado", "saiu mais cedo") else 0


@dataclass(frozen=True)
class Registro:
    """Retrato imutável de um encontro da grade e de sua situação.

    ``faltas=None`` significa pendente. O valor zero é diferente: indica que
    a aula foi resolvida sem gerar falta.
    """

    dia: date
    aulas: int
    situacao: str = "pendente"
    faltas: int | None = None


@dataclass(frozen=True)
class Atividade:
    """Prova ou trabalho associado a uma disciplina, sem alterar faltas.

    O identificador é criado pelo SQLite; nos testes sem banco ele fica ausente.
    O objeto é imutável para que título, data e vínculo não mudem sem validação.
    """

    codigo_disciplina: str
    dia: date
    tipo: str
    titulo: str
    identificador: int | None = None

    def __post_init__(self):
        if type(self.dia) is not date:
            raise ValueError("Informe uma data válida para a atividade.")
        if self.tipo not in ("prova", "trabalho"):
            raise ValueError("O tipo deve ser prova ou trabalho.")
        if not isinstance(self.titulo, str) or not self.titulo.strip():
            raise ValueError("Informe o título da atividade.")
        object.__setattr__(self, "titulo", self.titulo.strip())


class Disciplina:
    """Agregado de domínio que protege a grade e seus registros.

    Aqui ficam as invariantes de uma matéria: datas únicas, duração válida e
    política de chamada compatível. A interface não escreve em ``_registros``;
    pede à classe para registrar ou corrigir. Toda validação ocorre antes da
    troca, então uma entrada inválida não muda os totais.
    """

    def __init__(self, codigo, nome, chamadas, aulas, datas, registros=None):
        """Monta a grade após validar todos os campos.

        ``aulas`` é a duração de cada encontro em unidades de 50 minutos;
        ``chamadas`` define se atraso e saída antecipada contam meia aula.
        ``registros`` é usado apenas ao reconstruir uma disciplina do banco.
        O cadastro começa com todas as datas pendentes quando ele é omitido.
        """
        if not isinstance(codigo, str) or not codigo.strip():
            raise ValueError("Informe o código da disciplina.")
        if not isinstance(nome, str) or not nome.strip():
            raise ValueError("Informe o nome da disciplina.")
        if type(chamadas) is not int or chamadas not in (1, 2):
            raise ValueError("Escolha uma ou duas chamadas.")
        if type(aulas) is not int or aulas not in (1, 2, 4):
            raise ValueError("Cada encontro deve ter 1, 2 ou 4 aulas de 50 minutos.")
        if aulas == 1 and chamadas == 2:
            raise ValueError("Um encontro de uma aula aceita apenas uma chamada.")
        try:
            dias = tuple(datas)
        except TypeError:
            raise ValueError("Informe ao menos uma data válida.") from None
        if not dias or any(type(d) is not date for d in dias):
            raise ValueError("Informe ao menos uma data válida.")
        if len(set(dias)) != len(dias):
            raise ValueError("A grade não pode repetir uma data.")
        # A chave normalizada impede que "ele065" e "ELE065" virem duas matérias.
        self._codigo = codigo.strip().upper()
        self.nome = nome
        self._chamadas = chamadas
        # A escolha ocorre uma vez; depois registrar_presenca usa o mesmo
        # contrato, sem repetir um if para cada situação e tipo de chamada.
        self._politica = ChamadaUnica() if chamadas == 1 else ChamadaDupla()
        self._registros = {d: Registro(d, aulas) for d in sorted(dias)}
        if registros:
            self._registros.update(registros)

    @property
    def codigo(self):
        """Chave estável e normalizada da disciplina; não admite setter."""
        return self._codigo

    @property
    def nome(self):
        """Nome visível da disciplina, que pode ser corrigido pelo setter."""
        return self._nome

    @nome.setter
    def nome(self, valor):
        """Permite corrigir só o nome; rejeição preserva o valor anterior.

        Código, grade e faltas exigem operações próprias e não têm setter.
        O controle salva no banco antes de usar este setter na versão persistente.
        """
        if not isinstance(valor, str) or not valor.strip():
            raise ValueError("Informe o nome da disciplina.")
        self._nome = valor.strip()

    @property
    def chamadas(self):
        """Quantidade de chamadas definida no cadastro."""
        return self._chamadas

    @property
    def registros(self):
        """A tupla e seus registros não permitem alterar a coleção interna."""
        return tuple(self._registros.values())

    def registrar_presenca(
        self, dia: date, situacao: str, *, corrigir=False, salvar=None
    ):
        """Resolve uma aula da grade e devolve o novo registro.

        ``corrigir=True`` substitui apenas um registro já resolvido; sem
        isso, uma segunda gravação é rejeitada. ``salvar`` é a operação de
        persistência opcional: ela deve terminar antes da troca em memória.
        Assim, erro de validação ou do banco preserva o estado anterior.
        """
        if type(dia) is not date or dia not in self._registros:
            raise ValueError("A data não faz parte da grade desta disciplina.")
        if situacao not in SITUACOES:
            raise ValueError("Situação de frequência inválida.")
        anterior = self._registros[dia]
        if corrigir and anterior.situacao == "pendente":
            raise ValueError("Esta data está pendente. Use Registrar presença.")
        if anterior.situacao != "pendente" and not corrigir:
            raise ValueError("Esta data já foi registrada. Use Corrigir registro.")
        # A chamada polimórfica devolve faltas em aulas de 50 minutos.
        faltas = self._politica.calcular_faltas(situacao, anterior.aulas)
        novo = Registro(dia, anterior.aulas, situacao, faltas)
        # A gravação, quando existe, ocorre antes da troca em memória. Uma falha
        # no disco não deixa a interface mostrando um estado que não foi salvo.
        if salvar is not None:
            salvar(novo)
        self._registros[dia] = novo
        return novo

    def remarcar_encontro(self, dia_anterior: date, novo_dia: date, *, salvar=None):
        """Corrige uma data da grade sem mudar a presença já registrada.

        A operação troca só a chave da grade. Valida antes de gravar e publica
        a mudança em memória apenas depois do commit, evitando perda de faltas
        quando a nova data é inválida, duplicada ou o disco falha.
        """
        if type(dia_anterior) is not date or dia_anterior not in self._registros:
            raise ValueError("A data anterior não faz parte desta disciplina.")
        if type(novo_dia) is not date:
            raise ValueError("Informe uma nova data válida.")
        if novo_dia != dia_anterior and novo_dia in self._registros:
            raise ValueError("Já existe um encontro nessa data.")
        anterior = self._registros[dia_anterior]
        if novo_dia == dia_anterior:
            return anterior
        novo = Registro(novo_dia, anterior.aulas, anterior.situacao, anterior.faltas)
        if salvar is not None:
            salvar(dia_anterior, novo_dia)
        atualizados = {
            dia: registro
            for dia, registro in self._registros.items()
            if dia != dia_anterior
        }
        atualizados[novo_dia] = novo
        self._registros = dict(sorted(atualizados.items()))
        return novo

    def resumo(self):
        """Recalcula totais em aulas de 50 minutos a partir da grade atual.

        O limite é o piso de 25% da base sem aulas canceladas. Pendências
        continuam na base, mas não viram presença nem falta presumida; por
        isso a frequência percentual só aparece quando todas são resolvidas.
        """
        # Cancelada não integra a base; sem chamada integra, com zero faltas.
        ativos = [r for r in self.registros if r.situacao != "cancelada"]
        total = sum(r.aulas for r in ativos)
        pendentes = sum(r.aulas for r in ativos if r.faltas is None)
        faltas = sum(r.faltas or 0 for r in ativos)
        # // faz o piso de 25%: 7 aulas permitem 1 falta, não 1,75 nem 2.
        limite = total // 4
        return {
            "aulas": total,
            "pendentes": pendentes,
            "faltas": faltas,
            "limite": limite,
            "restantes": max(0, limite - faltas),
            "excesso": max(0, faltas - limite),
            "frequencia": 100 * (total - faltas) / total
            if total and not pendentes
            else None,
        }


class ControleAcademico:
    """Coordena disciplinas e pode carregar/salvar dados em SQLite.

    Com ``persistente=False`` o controle serve aos testes puros de domínio.
    O programa de terminal e o navegador usam ``persistente=True``; ambos
    percorrem as mesmas regras de ``Disciplina``. A fachada persistente é
    necessária porque devolver a disciplina pura permitiria corrigir sua
    memória sem salvar o SQLite.
    """

    def __init__(self, *, persistente=False, caminho_banco=None):
        self._persistente = persistente
        self._caminho_banco = Path(caminho_banco or database.DB_PATH)
        self._disciplinas = {}
        self._atividades = []
        if persistente:
            database.inicializar_banco(self._caminho_banco)
            self._carregar()

    def _carregar(self):
        """Reconstrói objetos do domínio; o banco guarda dados, não regras.

        A mesma classe Disciplina recalcula os totais depois de reabrir, sem
        persistir um segundo resumo que poderia divergir dos registros.
        """
        for codigo, nome, chamadas, aulas in database.listar_disciplinas(
            self._caminho_banco
        ):
            linhas = database.obter_registros(codigo, self._caminho_banco)
            datas = [date.fromisoformat(linha[0]) for linha in linhas]
            registros = {
                dia: Registro(dia, aulas, situacao, faltas)
                for dia, situacao, faltas in (
                    (date.fromisoformat(dia), situacao, faltas)
                    for dia, situacao, faltas in linhas
                )
            }
            self._disciplinas[codigo] = Disciplina(
                codigo, nome, chamadas, aulas, datas, registros
            )
        for identificador, codigo, dia, tipo, titulo in database.listar_atividades(
            self._caminho_banco
        ):
            self._atividades.append(
                Atividade(codigo, date.fromisoformat(dia), tipo, titulo, identificador)
            )

    @property
    def disciplinas(self):
        """Lista disciplinas sem permitir que alterações ignorem o SQLite."""
        if self._persistente:
            return tuple(
                _DisciplinaPersistente(disciplina, self)
                for disciplina in self._disciplinas.values()
            )
        return tuple(self._disciplinas.values())

    @property
    def atividades(self):
        """Agenda cronológica somente de leitura; não modifica a frequência."""
        return tuple(
            sorted(self._atividades, key=lambda a: (a.dia, a.identificador or 0))
        )

    def adicionar_atividade(self, codigo, dia, tipo, titulo):
        """Inclui prova ou trabalho sem modificar a frequência.

        A disciplina precisa existir. O objeto entra na agenda em memória
        apenas depois de ter sido gravado no banco, quando há persistência.
        """
        disciplina = self.obter_disciplina(codigo)
        nova = Atividade(disciplina.codigo, dia, tipo, titulo)
        if self._persistente:
            identificador = database.salvar_atividade(
                nova.codigo_disciplina,
                nova.dia,
                nova.tipo,
                nova.titulo,
                self._caminho_banco,
            )
            nova = Atividade(
                nova.codigo_disciplina, nova.dia, nova.tipo, nova.titulo, identificador
            )
        self._atividades.append(nova)
        return nova

    def criar_disciplina(self, codigo, nome, chamadas, aulas, datas):
        """Cadastra uma disciplina com todas as datas inicialmente pendentes.

        A construção valida a grade antes da escrita. Em modo persistente,
        a disciplina e as linhas da grade entram na mesma transação SQL;
        somente após o commit ela aparece na lista do programa.
        """
        nova = Disciplina(codigo, nome, chamadas, aulas, datas)
        if nova.codigo in self._disciplinas:
            raise ValueError("Já existe uma disciplina com esse código.")
        if self._persistente:
            database.salvar_disciplina(
                nova.codigo,
                nova.nome,
                nova.chamadas,
                nova.registros[0].aulas,
                [registro.dia for registro in nova.registros],
                self._caminho_banco,
            )
        # Só entra no cadastro depois do commit SQL bem-sucedido.
        self._disciplinas[nova.codigo] = nova
        return _DisciplinaPersistente(nova, self) if self._persistente else nova

    def preencher_exemplo(self):
        """Prepara uma amostra completa sem depender de arquivo ou conta.

        Ela só entra numa base vazia. Primeiro as regras comuns validam todos
        os objetos em memória; depois uma transação grava tudo. Publicar os
        objetos só após o commit evita uma demo pela metade se o disco falhar.
        """
        if self._disciplinas or self._atividades:
            raise ValueError("Os dados de exemplo exigem uma demo vazia.")
        preparado = ControleAcademico()
        dias = [date(2026, 11, dia) for dia in (2, 4, 9, 11)]
        disciplina = preparado.criar_disciplina(
            "DEMO01", "Disciplina fictícia", 2, 2, dias
        )
        disciplina.registrar_presenca(dias[0], "presente")
        disciplina.registrar_presenca(dias[1], "ausente")
        atividade = preparado.adicionar_atividade(
            "DEMO01", date(2026, 11, 10), "prova", "Avaliação fictícia"
        )
        if self._persistente:
            identificador = database.salvar_exemplo(
                disciplina, atividade, self._caminho_banco
            )
            atividade = Atividade(
                atividade.codigo_disciplina,
                atividade.dia,
                atividade.tipo,
                atividade.titulo,
                identificador,
            )
        self._disciplinas[disciplina.codigo] = disciplina
        self._atividades.append(atividade)
        return disciplina

    def obter_disciplina(self, codigo):
        """Busca por código sem diferenciar caixa nem espaços nas bordas.

        A versão persistente devolve uma fachada que salva correções antes
        de atualizar o objeto original; os cálculos continuam em Disciplina.
        """
        if not isinstance(codigo, str) or not codigo.strip():
            raise ValueError("Informe o código da disciplina.")
        chave = codigo.strip().upper()
        if chave not in self._disciplinas:
            raise ValueError("Disciplina não encontrada. Cadastre-a primeiro.")
        disciplina = self._disciplinas[chave]
        return (
            _DisciplinaPersistente(disciplina, self)
            if self._persistente
            else disciplina
        )

    def renomear_disciplina(self, codigo, novo_nome):
        """Corrige somente o nome, preservando grade, registros e atividades.

        Valida o novo nome e confirma a alteração no banco antes de mudar o
        objeto em memória. Se falhar, o nome antigo permanece nos dois.
        """
        disciplina = self.obter_disciplina(codigo)
        if not isinstance(novo_nome, str) or not novo_nome.strip():
            raise ValueError("Informe o nome da disciplina.")
        nome = novo_nome.strip()
        if self._persistente:
            database.atualizar_nome(disciplina.codigo, nome, self._caminho_banco)
        self._disciplinas[disciplina.codigo].nome = nome
        return self.obter_disciplina(disciplina.codigo)

    def remarcar_encontro(self, codigo, dia_anterior, novo_dia):
        """Corrige uma data por código, usando as mesmas regras em todas as telas."""
        return self.obter_disciplina(codigo).remarcar_encontro(dia_anterior, novo_dia)

    def apagar_tudo(self):
        """Remove disciplinas, registros e atividades após confirmar no menu.

        No modo persistente, o banco é limpo antes da memória. Uma falha SQL
        deixa ambos com os dados anteriores; o arquivo e as tabelas continuam.
        """
        if self._persistente:
            database.apagar_tudo(self._caminho_banco)
        self._disciplinas.clear()
        self._atividades.clear()

    def _salvar_registro(self, disciplina, registro):
        """Persiste o registro já validado antes de ele entrar na grade em memória."""
        if self._persistente:
            database.salvar_registro(
                disciplina.codigo,
                registro.dia,
                registro.situacao,
                registro.faltas,
                self._caminho_banco,
            )

    def _salvar_data_encontro(self, disciplina, dia_anterior, novo_dia):
        """Persiste a nova chave da grade antes de publicá-la em memória."""
        if self._persistente:
            database.remarcar_encontro(
                disciplina.codigo, dia_anterior, novo_dia, self._caminho_banco
            )


class _DisciplinaPersistente:
    """Fachada que intercepta mutações e salva antes de publicá-las.

    Não herda de Disciplina: representa a mesma matéria com persistência,
    enquanto ChamadaUnica/ChamadaDupla são as especializações da regra de
    faltas. __getattr__ delega as consultas; as mutações têm métodos próprios.
    """

    __slots__ = ("_disciplina", "_controle")

    def __init__(self, disciplina, controle):
        self._disciplina = disciplina
        self._controle = controle

    def __getattr__(self, nome):
        """Repassa leituras ao objeto de domínio sem expor sua coleção interna."""
        return getattr(self._disciplina, nome)

    @property
    def nome(self):
        return self._disciplina.nome

    @nome.setter
    def nome(self, valor):
        self._controle.renomear_disciplina(self._disciplina.codigo, valor)

    def registrar_presenca(self, *args, **kwargs):
        """Usa a regra da disciplina e injeta a escrita antes da troca."""
        return self._disciplina.registrar_presenca(
            *args,
            salvar=lambda registro: self._controle._salvar_registro(
                self._disciplina, registro
            ),
            **kwargs,
        )

    def remarcar_encontro(self, dia_anterior, novo_dia):
        """Mantém a regra da disciplina e salva a data antes da troca."""
        return self._disciplina.remarcar_encontro(
            dia_anterior,
            novo_dia,
            salvar=lambda anterior, novo: self._controle._salvar_data_encontro(
                self._disciplina, anterior, novo
            ),
        )
