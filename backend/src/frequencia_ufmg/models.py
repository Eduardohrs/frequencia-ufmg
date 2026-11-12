"""Modelo de domínio avaliável da frequência acadêmica."""

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any


class QuantidadeAulas(IntEnum):
    """Quantidades permitidas de aulas de 50 minutos em uma sessão."""

    UMA = 1
    DUAS = 2
    QUATRO = 4


class NumeroChamadas(IntEnum):
    """Quantidade de chamadas realizadas durante uma sessão."""

    UMA = 1
    DUAS = 2


class EstadoPing(StrEnum):
    """Evidência de localização observada em um momento da sessão."""

    NO_CAMPUS = "no_campus"
    FORA = "fora"
    INDISPONIVEL = "indisponivel"


class SituacaoFrequencia(StrEnum):
    """Classificação pessoal produzida a partir dos dois pings."""

    PRESENTE = "presente"
    CHEGOU_ATRASADO = "chegou_atrasado"
    SAIU_MAIS_CEDO = "saiu_mais_cedo"
    AUSENTE = "ausente"
    PENDENTE = "pendente"


class PoliticaFrequencia(ABC):
    """Contrato polimórfico para classificar os pings de uma sessão."""

    @abstractmethod
    def classificar(
        self,
        primeiro_ping: EstadoPing,
        segundo_ping: EstadoPing,
    ) -> SituacaoFrequencia:
        """Classifique duas evidências já validadas."""

    @abstractmethod
    def calcular_faltas(
        self,
        aulas: QuantidadeAulas,
        situacao: SituacaoFrequencia,
    ) -> int | None:
        """Converta uma situação validada em faltas de aulas inteiras."""


class PoliticaChamadaUnica(PoliticaFrequencia):
    """Uma confirmação no campus resolve uma sessão de chamada única."""

    def classificar(
        self,
        primeiro_ping: EstadoPing,
        segundo_ping: EstadoPing,
    ) -> SituacaoFrequencia:
        """Preserve detalhes quando ambos os pings estiverem disponíveis."""

        if EstadoPing.INDISPONIVEL in (primeiro_ping, segundo_ping):
            if EstadoPing.NO_CAMPUS in (primeiro_ping, segundo_ping):
                return SituacaoFrequencia.PRESENTE
            return SituacaoFrequencia.PENDENTE
        return _classificar_pings_validos(primeiro_ping, segundo_ping)

    def calcular_faltas(
        self,
        aulas: QuantidadeAulas,
        situacao: SituacaoFrequencia,
    ) -> int | None:
        """Conte o bloco inteiro somente quando a sessão estiver ausente."""

        if situacao is SituacaoFrequencia.PENDENTE:
            return None
        if situacao is SituacaoFrequencia.AUSENTE:
            return int(aulas)
        return 0


class PoliticaDuasChamadas(PoliticaFrequencia):
    """Cada ping é obrigatório quando a sessão possui duas chamadas."""

    def classificar(
        self,
        primeiro_ping: EstadoPing,
        segundo_ping: EstadoPing,
    ) -> SituacaoFrequencia:
        """Mantenha a sessão pendente enquanto uma das metades não tiver evidência."""

        if EstadoPing.INDISPONIVEL in (primeiro_ping, segundo_ping):
            return SituacaoFrequencia.PENDENTE
        return _classificar_pings_validos(primeiro_ping, segundo_ping)

    def calcular_faltas(
        self,
        aulas: QuantidadeAulas,
        situacao: SituacaoFrequencia,
    ) -> int | None:
        """Conte zero, metade ou todas as aulas conforme as duas chamadas."""

        if situacao is SituacaoFrequencia.PENDENTE:
            return None
        if situacao is SituacaoFrequencia.PRESENTE:
            return 0
        if situacao is SituacaoFrequencia.AUSENTE:
            return int(aulas)
        return int(aulas) // 2


@dataclass(frozen=True, slots=True)
class ConfiguracaoSessao:
    """Configuração imutável que define como uma sessão contabiliza presença."""

    aulas: QuantidadeAulas
    chamadas: NumeroChamadas

    def __post_init__(self) -> None:
        """Impeça combinações que não representam aulas inteiras."""

        if not isinstance(self.aulas, QuantidadeAulas) or not isinstance(
            self.chamadas, NumeroChamadas
        ):
            raise TypeError("aulas e chamadas devem usar os enums do domínio")
        if self.aulas is QuantidadeAulas.UMA and self.chamadas is NumeroChamadas.DUAS:
            raise ValueError("uma aula não pode ter duas chamadas")


class SessaoAula:
    """Uma sessão identificável pertencente a uma disciplina."""

    __slots__ = ("_configuracao", "_identificador")

    def __init__(self, identificador: str, configuracao: ConfiguracaoSessao) -> None:
        self._identificador = _texto_obrigatorio(identificador, "identificador")
        if not isinstance(configuracao, ConfiguracaoSessao):
            raise TypeError("configuração deve ser uma ConfiguracaoSessao")
        self._configuracao = configuracao

    @property
    def identificador(self) -> str:
        """Identidade estável da sessão dentro de uma disciplina."""

        return self._identificador

    @property
    def configuracao(self) -> ConfiguracaoSessao:
        """Configuração validada da sessão."""

        return self._configuracao

    def classificar(
        self,
        primeiro_ping: EstadoPing,
        segundo_ping: EstadoPing,
    ) -> SituacaoFrequencia:
        """Classifique a sessão conforme sua quantidade de chamadas."""

        if not isinstance(primeiro_ping, EstadoPing) or not isinstance(
            segundo_ping, EstadoPing
        ):
            raise TypeError("os pings devem usar EstadoPing")
        politica = _politica_frequencia(self._configuracao.chamadas)
        return politica.classificar(primeiro_ping, segundo_ping)

    def calcular_faltas(self, situacao: SituacaoFrequencia) -> int | None:
        """Converta a situação em faltas conforme a configuração da sessão."""

        if not isinstance(situacao, SituacaoFrequencia):
            raise TypeError("situação deve usar SituacaoFrequencia")
        politica = _politica_frequencia(self._configuracao.chamadas)
        return politica.calcular_faltas(self._configuracao.aulas, situacao)


class RegistroFrequencia:
    """Resultado atual de uma sessão, automático ou corrigido manualmente."""

    __slots__ = ("_faltas", "_sessao", "_situacao")

    def __init__(self, sessao: SessaoAula, situacao: SituacaoFrequencia) -> None:
        if not isinstance(sessao, SessaoAula):
            raise TypeError("sessão deve ser uma SessaoAula")
        if not isinstance(situacao, SituacaoFrequencia):
            raise TypeError("situação deve usar SituacaoFrequencia")
        self._sessao = sessao
        self._situacao = situacao
        self._faltas = sessao.calcular_faltas(situacao)

    @property
    def sessao(self) -> SessaoAula:
        """Sessão à qual o resultado pertence."""

        return self._sessao

    @property
    def situacao(self) -> SituacaoFrequencia:
        """Situação atualmente considerada nos relatórios."""

        return self._situacao

    @property
    def faltas(self) -> int | None:
        """Faltas atuais, ou ausência de valor enquanto estiver pendente."""

        return self._faltas

    def corrigir(self, situacao: SituacaoFrequencia, faltas: int | None) -> None:
        """Substitua o resultado atual sem manter motivo ou histórico."""

        if not isinstance(situacao, SituacaoFrequencia):
            raise TypeError("situação deve usar SituacaoFrequencia")
        if situacao is SituacaoFrequencia.PENDENTE:
            if faltas is not None:
                raise ValueError("uma situação pendente não pode ter faltas")
        else:
            if not isinstance(faltas, int) or isinstance(faltas, bool):
                raise TypeError("faltas devem ser um número inteiro")
            if not 0 <= faltas <= int(self._sessao.configuracao.aulas):
                raise ValueError("faltas devem respeitar a quantidade de aulas da sessão")
        self._situacao = situacao
        self._faltas = faltas


@dataclass(frozen=True, slots=True)
class ResumoDisciplina:
    """Retrato imutável da frequência atual de uma disciplina."""

    codigo: str
    total_sessoes: int
    sessoes_pendentes: int
    faltas_consumidas: int
    limite_faltas: int
    faltas_restantes: int


class Disciplina:
    """Agregado que controla as sessões de uma disciplina."""

    __slots__ = ("_carga_horaria", "_codigo", "_nome", "_registros", "_sessoes")

    def __init__(self, codigo: str, nome: str, carga_horaria: int) -> None:
        self._codigo = _texto_obrigatorio(codigo, "código")
        self._nome = _texto_obrigatorio(nome, "nome")
        if not isinstance(carga_horaria, int) or isinstance(carga_horaria, bool):
            raise TypeError("carga horária deve ser um número inteiro")
        if carga_horaria <= 0:
            raise ValueError("carga horária deve ser positiva")
        self._carga_horaria = carga_horaria
        self._sessoes: list[SessaoAula] = []
        self._registros: dict[str, RegistroFrequencia] = {}

    @property
    def codigo(self) -> str:
        """Código acadêmico normalizado da disciplina."""

        return self._codigo

    @property
    def nome(self) -> str:
        """Nome normalizado da disciplina."""

        return self._nome

    @property
    def carga_horaria(self) -> int:
        """Quantidade positiva de horas-aula de 50 minutos da disciplina."""

        return self._carga_horaria

    @property
    def limite_faltas(self) -> int:
        """Máximo inteiro que mantém pelo menos 75% de presença."""

        return self._carga_horaria // 4

    @property
    def sessoes(self) -> tuple[SessaoAula, ...]:
        """Cópia imutável das sessões atualmente cadastradas."""

        return tuple(self._sessoes)

    @property
    def registros(self) -> tuple[RegistroFrequencia, ...]:
        """Resultados atuais na mesma ordem das sessões cadastradas."""

        return tuple(
            self._registros[sessao.identificador]
            for sessao in self._sessoes
            if sessao.identificador in self._registros
        )

    def adicionar_sessao(self, sessao: SessaoAula) -> None:
        """Adicione uma sessão cuja identidade ainda não pertence à disciplina."""

        if not isinstance(sessao, SessaoAula):
            raise TypeError("sessão deve ser uma SessaoAula")
        if any(item.identificador == sessao.identificador for item in self._sessoes):
            raise ValueError("sessão já cadastrada na disciplina")
        self._sessoes.append(sessao)

    def faltas_restantes(self, faltas_consumidas: int) -> int:
        """Informe quantas faltas ainda cabem no limite da disciplina."""

        if not isinstance(faltas_consumidas, int) or isinstance(faltas_consumidas, bool):
            raise TypeError("faltas consumidas devem ser um número inteiro")
        if faltas_consumidas < 0:
            raise ValueError("faltas consumidas não podem ser negativas")
        return max(self.limite_faltas - faltas_consumidas, 0)

    def registrar_frequencia(
        self,
        identificador_sessao: str,
        situacao: SituacaoFrequencia,
    ) -> RegistroFrequencia:
        """Crie ou substitua o resultado atual de uma sessão cadastrada."""

        sessao = self._buscar_sessao(identificador_sessao)
        registro = RegistroFrequencia(sessao, situacao)
        self._registros[sessao.identificador] = registro
        return registro

    def resumo(self) -> ResumoDisciplina:
        """Consolide apenas os valores atuais de todas as sessões."""

        registros = self.registros
        faltas_consumidas = sum(
            registro.faltas for registro in registros if registro.faltas is not None
        )
        sessoes_resolvidas = sum(registro.faltas is not None for registro in registros)
        sessoes_pendentes = len(self._sessoes) - sessoes_resolvidas
        return ResumoDisciplina(
            codigo=self._codigo,
            total_sessoes=len(self._sessoes),
            sessoes_pendentes=sessoes_pendentes,
            faltas_consumidas=faltas_consumidas,
            limite_faltas=self.limite_faltas,
            faltas_restantes=self.faltas_restantes(faltas_consumidas),
        )

    def _buscar_sessao(self, identificador: str) -> SessaoAula:
        """Encontre uma sessão pertencente ao agregado."""

        if not isinstance(identificador, str):
            raise TypeError("identificador da sessão deve ser texto")
        normalizado = identificador.strip()
        for sessao in self._sessoes:
            if sessao.identificador == normalizado:
                return sessao
        raise ValueError("sessão não cadastrada na disciplina")


def _texto_obrigatorio(valor: object, campo: str) -> str:
    """Normalize um campo textual obrigatório na fronteira do domínio."""

    if not isinstance(valor, str):
        raise TypeError(f"{campo} deve ser texto")
    normalizado = valor.strip()
    if not normalizado:
        raise ValueError(f"{campo} é obrigatório")
    return normalizado


def _politica_frequencia(chamadas: NumeroChamadas) -> PoliticaFrequencia:
    """Selecione a política correspondente à configuração validada."""

    if chamadas is NumeroChamadas.UMA:
        return PoliticaChamadaUnica()
    return PoliticaDuasChamadas()


def _classificar_pings_validos(
    primeiro_ping: EstadoPing,
    segundo_ping: EstadoPing,
) -> SituacaoFrequencia:
    """Classifique o padrão temporal quando ambos os pings estão disponíveis."""

    if primeiro_ping is EstadoPing.NO_CAMPUS:
        if segundo_ping is EstadoPing.NO_CAMPUS:
            return SituacaoFrequencia.PRESENTE
        return SituacaoFrequencia.SAIU_MAIS_CEDO
    if segundo_ping is EstadoPing.NO_CAMPUS:
        return SituacaoFrequencia.CHEGOU_ATRASADO
    return SituacaoFrequencia.AUSENTE


class DecisaoHorario(StrEnum):
    """DecisãoTomada pelo usuário em relação a uma pendência de horário."""

    MANTER_ATUAL = "manter_atual"
    APLICAR_MUDANCA = "aplicar_mudanca"
    PENDENTE = "pendente"


@dataclass(frozen=True, slots=True)
class PendenciaHorario:
    """Pendência de horário que precisa de decisão do usuário."""

    disciplina_codigo: str
    disciplina_nome: str
    horario_atual: str
    horario_novo: str
    motivo: str
    data_criacao: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict[str, Any]:
        """Converte para dicionário para serialização."""
        return {
            "disciplina_codigo": self.disciplina_codigo,
            "disciplina_nome": self.disciplina_nome,
            "horario_atual": self.horario_atual,
            "horario_novo": self.horario_novo,
            "motivo": self.motivo,
            "data_criacao": self.data_criacao.isoformat(),
        }


class RascunhoCadastro:
    """Rascunho de cadastro que pode ser recuperado em caso de falha."""

    __slots__ = ("_disciplina", "_sessao", "_dados", "_timestamp")

    def __init__(
        self,
        disciplina_codigo: str,
        sessao_identificador: str,
        dados: dict[str, Any],
    ) -> None:
        self._disciplina = disciplina_codigo
        self._sessao = sessao_identificador
        self._dados = copy.deepcopy(dados)
        self._timestamp = datetime.now()

    @property
    def disciplina_codigo(self) -> str:
        return self._disciplina

    @property
    def sessao_identificador(self) -> str:
        return self._sessao

    @property
    def dados(self) -> dict[str, Any]:
        return self._dados.copy()

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    def to_dict(self) -> dict[str, Any]:
        """Converte para dicionário para serialização."""
        return {
            "disciplina_codigo": self._disciplina,
            "sessao_identificador": self._sessao,
            "dados": self._dados,
            "timestamp": self._timestamp.isoformat(),
        }


class CentralPendencias:
    """Central acionável para gerenciamento de pendências de horário."""

    __slots__ = ("_pendencias", "_decisoes")

    def __init__(self) -> None:
        self._pendencias: dict[str, PendenciaHorario] = {}
        self._decisoes: dict[str, DecisaoHorario] = {}

    def adicionar_pendencia(self, pendencia: PendenciaHorario) -> str:
        """Adiciona uma pendência de horário e retorna um ID único."""
        pendencia_id = f"{pendencia.disciplina_codigo}-{len(self._pendencias)}"
        self._pendencias[pendencia_id] = pendencia
        return pendencia_id

    def restaurar(
        self,
        pendencia_id: str,
        pendencia: PendenciaHorario,
        decisao: DecisaoHorario = DecisaoHorario.PENDENTE,
    ) -> None:
        """Restaura uma pendência persistida para a memória da instância."""
        self._pendencias[pendencia_id] = pendencia
        if decisao is not DecisaoHorario.PENDENTE:
            self._decisoes[pendencia_id] = decisao

    def registrar_decisao(
        self,
        pendencia_id: str,
        decisao: DecisaoHorario,
    ) -> None:
        """Registra a decisão do usuário para uma pendência."""
        if pendencia_id not in self._pendencias:
            raise ValueError(f"Pendência {pendencia_id} não encontrada")
        self._decisoes[pendencia_id] = decisao

    def get_pendencia(self, pendencia_id: str) -> PendenciaHorario | None:
        """Recupera uma pendência pelo ID."""
        return self._pendencias.get(pendencia_id)

    def get_decisao(self, pendencia_id: str) -> DecisaoHorario | None:
        """Recupera a decisão para uma pendência."""
        return self._decisoes.get(pendencia_id)

    def get_todas_pendencias(self) -> list[PendenciaHorario]:
        """Retorna todas as pendências ativas."""
        return list(self._pendencias.values())

    def remover_pendencia(self, pendencia_id: str) -> bool:
        """Remove uma pendência após resolução. Retorna True se removida."""
        if pendencia_id in self._pendencias:
            del self._pendencias[pendencia_id]
            return True
        return False

    def limpar_pendencias_resolvidas(self) -> int:
        """Remove pendências com decisão diferente de PENDENTE. Retorna quantidade removida."""
        removidas = 0
        ids_para_remover = [
            pid for pid, decisao in self._decisoes.items()
            if decisao != DecisaoHorario.PENDENTE
        ]
        for pid in ids_para_remover:
            if pid in self._pendencias:
                del self._pendencias[pid]
                removidas += 1
        return removidas


class GerenciadorRascunhos:
    """Gerenciador de rascunhos para recuperação em caso de falha."""

    __slots__ = ("_rascunhos",)

    def __init__(self) -> None:
        self._rascunhos: dict[str, RascunhoCadastro] = {}

    def salvar_rascunho(
        self,
        disciplina_codigo: str,
        sessao_identificador: str,
        dados: dict[str, Any],
    ) -> str:
        """Salva um rascunho e retorna um ID único."""
        rascunho_id = f"{disciplina_codigo}-{sessao_identificador}-{len(self._rascunhos)}"
        self._rascunhos[rascunho_id] = RascunhoCadastro(
            disciplina_codigo, sessao_identificador, dados
        )
        return rascunho_id

    def recuperar_rascunho(self, rascunho_id: str) -> RascunhoCadastro | None:
        """Recupera um rascunho pelo ID."""
        return self._rascunhos.get(rascunho_id)

    def remover_rascunho(self, rascunho_id: str) -> bool:
        """Remove um rascunho após uso. Retorna True se removido."""
        if rascunho_id in self._rascunhos:
            del self._rascunhos[rascunho_id]
            return True
        return False

    def listar_rascunhos(self, disciplina_codigo: str) -> list[RascunhoCadastro]:
        """Lista todos os rascunhos para uma disciplina."""
        return [
            r for r in self._rascunhos.values()
            if r.disciplina_codigo == disciplina_codigo
        ]
