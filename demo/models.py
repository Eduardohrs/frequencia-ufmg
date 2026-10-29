"""Domínio didático: frequência pessoal; nenhuma integração ou I/O neste arquivo."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from enum import Enum


class Evidencia(Enum):
    """Resultado SIMULADO da localização; indisponível não significa ausência."""

    NO_CAMPUS = "no campus"
    FORA = "fora do campus"
    INDISPONIVEL = "indisponível"


class Momento(Enum):
    """Checkpoints conceituais: início+20min e término-20min; sem relógio real."""

    INICIO = "20 minutos após o início"
    FIM = "20 minutos antes do término"


class Situacao(Enum):
    """Classificações para controle pessoal, sem valor de comprovação oficial."""

    PRESENTE = "presente"
    ATRASADO = "atrasado"
    SAIU_MAIS_CEDO = "saiu mais cedo"
    AUSENTE = "ausente"
    PENDENTE = "pendente"


@dataclass(frozen=True)
class RegistroFrequencia:
    """Resultado imutável: correção substitui o objeto, sem acumular nem auditar."""

    situacao: Situacao
    faltas: int | None
    manual: bool = False


class PoliticaFrequencia(ABC):
    """Contrato: mesmas evidências, faltas conforme a modalidade de chamada."""

    @abstractmethod
    def classificar(
        self, aulas: int, primeiro: Evidencia, segundo: Evidencia
    ) -> RegistroFrequencia:
        """Retorne a estimativa; a sessão valida os argumentos antes da chamada."""

    def _situacao(self, primeiro: Evidencia, segundo: Evidencia) -> Situacao:
        """Mantenha o significado dos estados comum às especializações."""
        if Evidencia.INDISPONIVEL in (primeiro, segundo):
            return Situacao.PENDENTE
        return {
            (Evidencia.NO_CAMPUS, Evidencia.NO_CAMPUS): Situacao.PRESENTE,
            (Evidencia.NO_CAMPUS, Evidencia.FORA): Situacao.SAIU_MAIS_CEDO,
            (Evidencia.FORA, Evidencia.NO_CAMPUS): Situacao.ATRASADO,
            (Evidencia.FORA, Evidencia.FORA): Situacao.AUSENTE,
        }[primeiro, segundo]


class ChamadaUnica(PoliticaFrequencia):
    """Qualquer confirmação positiva basta para zero faltas no bloco inteiro."""

    def classificar(self, aulas, primeiro, segundo):
        situacao = self._situacao(primeiro, segundo)
        if situacao == Situacao.PENDENTE and Evidencia.NO_CAMPUS in (primeiro, segundo):
            situacao = Situacao.PRESENTE
        faltas = (
            None
            if situacao == Situacao.PENDENTE
            else (aulas if situacao == Situacao.AUSENTE else 0)
        )
        return RegistroFrequencia(situacao, faltas)


class ChamadaDupla(PoliticaFrequencia):
    """Cada checkpoint corresponde à metade das unidades de uma sessão2/4."""

    def classificar(self, aulas, primeiro, segundo):
        situacao = self._situacao(primeiro, segundo)
        faltas = (
            None
            if situacao == Situacao.PENDENTE
            else (
                (int(primeiro == Evidencia.FORA) + int(segundo == Evidencia.FORA))
                * (aulas // 2)
            )
        )
        return RegistroFrequencia(situacao, faltas)


class SessaoAula:
    """Dona dos pings únicos por momento e do único resultado atual."""

    def __init__(
        self,
        identificador: str,
        dia: date,
        aulas: int,
        politica: PoliticaFrequencia,
        natureza: str = "normal",
    ):
        if not isinstance(identificador, str) or not identificador.strip():
            raise ValueError("Identificador obrigatório.")
        if type(dia) is not date:
            raise ValueError("Data da sessão inválida.")
        if type(aulas) is not int or aulas not in (1, 2, 4):
            raise ValueError("Use 1, 2 ou 4 aulas de 50 minutos.")
        if not isinstance(politica, PoliticaFrequencia):
            raise ValueError("Política de chamada inválida.")
        if aulas == 1 and isinstance(politica, ChamadaDupla):
            raise ValueError("Uma aula admite somente chamada única.")
        if natureza not in ("normal", "cancelada", "sem_chamada"):
            raise ValueError("Natureza da sessão inválida.")
        self._identificador = identificador.strip()
        self._dia, self._aulas, self._politica, self._natureza = (
            dia,
            aulas,
            politica,
            natureza,
        )
        self._pings: dict[Momento, Evidencia] = {}
        self._registro = RegistroFrequencia(
            Situacao.PRESENTE if natureza == "sem_chamada" else Situacao.PENDENTE,
            0 if natureza == "sem_chamada" else None,
        )

    @property
    def identificador(self):
        """Identificador estável usado pelo menu."""
        return self._identificador

    @property
    def dia(self):
        """Dia fictício da sessão."""
        return self._dia

    @property
    def aulas(self):
        """Quantidade de unidades de50min."""
        return self._aulas

    @property
    def natureza(self):
        """Normal, cancelada ou sem chamada; fixa neste incremento."""
        return self._natureza

    @property
    def modalidade(self):
        """Descrição da política, sem expor estado mutável."""
        return (
            "uma chamada"
            if isinstance(self._politica, ChamadaUnica)
            else "duas chamadas"
        )

    @property
    def pings(self):
        """Retrato imutável; a coleção interna não pode ser alterada pelo menu."""
        return tuple(self._pings.items())

    @property
    def registro(self):
        """Resultado atual imutável."""
        return self._registro

    def _exigir_normal(self):
        if self._natureza != "normal":
            raise ValueError(
                "Sessão cancelada/sem chamada não recebe pings nem correções."
            )

    def registrar_ping(
        self, momento: Momento, evidencia: Evidencia
    ) -> RegistroFrequencia:
        """F01: valide, classifique uma cópia e só então altere o estado completo."""
        self._exigir_normal()
        if not isinstance(momento, Momento) or not isinstance(evidencia, Evidencia):
            raise ValueError("Momento ou evidência inválidos.")
        if self._registro.manual:
            raise ValueError(
                "Correção manual protegida; use corrigir para substituir o resultado."
            )
        if momento in self._pings:
            raise ValueError("Ping deste momento já registrado.")
        novos = {**self._pings, momento: evidencia}
        registro = self._politica.classificar(
            self._aulas,
            novos.get(Momento.INICIO, Evidencia.INDISPONIVEL),
            novos.get(Momento.FIM, Evidencia.INDISPONIVEL),
        )
        self._pings, self._registro = novos, registro
        return registro

    def corrigir(self, situacao: Situacao, faltas: int | None) -> RegistroFrequencia:
        """F02: substitua o resultado; preserve evidências; rejeição não altera nada."""
        self._exigir_normal()
        if not isinstance(situacao, Situacao):
            raise ValueError("Situação inválida.")
        if situacao == Situacao.PENDENTE:
            if faltas is not None:
                raise ValueError("Pendente não aceita número de faltas.")
        elif type(faltas) is not int or not 0 <= faltas <= self._aulas:
            raise ValueError(f"Faltas devem ser inteiras entre 0 e {self._aulas}.")
        self._registro = RegistroFrequencia(situacao, faltas, manual=True)
        return self._registro


@dataclass(frozen=True)
class ResumoDisciplina:
    """Unidades de50min; percentual final indefinido enquanto houver pendências."""

    aulas_elegiveis: int
    aulas_presentes: int
    aulas_pendentes: int
    faltas_consumidas: int
    limite_faltas: int
    faltas_restantes: int
    excedeu_limite: bool
    frequencia_percentual: float | None


class Disciplina:
    """Agrega sessões conhecidas; consulta calcula totais sem manter cache divergente."""

    def __init__(self, codigo: str, nome: str, sessoes):
        if (
            not isinstance(codigo, str)
            or not codigo.strip()
            or not isinstance(nome, str)
            or not nome.strip()
        ):
            raise ValueError("Código e nome obrigatórios.")
        itens = tuple(sessoes)
        if any(not isinstance(s, SessaoAula) for s in itens):
            raise ValueError("A disciplina aceita apenas sessões de aula.")
        if len({s.identificador for s in itens}) != len(itens):
            raise ValueError("Identificador de sessão duplicado.")
        self._codigo, self._nome, self._sessoes = codigo.strip(), nome.strip(), itens

    @property
    def codigo(self):
        """Código fictício da disciplina."""
        return self._codigo

    @property
    def nome(self):
        """Nome da disciplina fictícia."""
        return self._nome

    @property
    def sessoes(self):
        """Tupla dos agregados; não permite adicionar ou remover sessões externamente."""
        return self._sessoes

    def obter_sessao(self, identificador: str) -> SessaoAula:
        for sessao in self._sessoes:
            if sessao.identificador == identificador:
                return sessao
        raise ValueError("Sessão não encontrada nesta disciplina.")

    def resumo(self) -> ResumoDisciplina:
        """Cancelada sai da base; sem chamada entra com0faltas; pendente não presume presença."""
        elegiveis = [s for s in self._sessoes if s.natureza != "cancelada"]
        total = sum(s.aulas for s in elegiveis)
        pendentes = sum(s.aulas for s in elegiveis if s.registro.faltas is None)
        faltas = sum(s.registro.faltas or 0 for s in elegiveis)
        limite = total // 4
        return ResumoDisciplina(
            total,
            total - pendentes - faltas,
            pendentes,
            faltas,
            limite,
            max(0, limite - faltas),
            faltas > limite,
            100 * (total - faltas) / total if total and not pendentes else None,
        )
