"""Modelo de domínio avaliável da frequência acadêmica."""

from dataclasses import dataclass
from enum import IntEnum


class QuantidadeAulas(IntEnum):
    """Quantidades permitidas de aulas de 50 minutos em uma sessão."""

    UMA = 1
    DUAS = 2
    QUATRO = 4


class NumeroChamadas(IntEnum):
    """Quantidade de chamadas realizadas durante uma sessão."""

    UMA = 1
    DUAS = 2


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


class Disciplina:
    """Agregado que controla as sessões de uma disciplina."""

    __slots__ = ("_carga_horaria", "_codigo", "_nome", "_sessoes")

    def __init__(self, codigo: str, nome: str, carga_horaria: int) -> None:
        self._codigo = _texto_obrigatorio(codigo, "código")
        self._nome = _texto_obrigatorio(nome, "nome")
        if not isinstance(carga_horaria, int) or isinstance(carga_horaria, bool):
            raise TypeError("carga horária deve ser um número inteiro")
        if carga_horaria <= 0:
            raise ValueError("carga horária deve ser positiva")
        self._carga_horaria = carga_horaria
        self._sessoes: list[SessaoAula] = []

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
        """Carga horária positiva informada para a disciplina."""

        return self._carga_horaria

    @property
    def sessoes(self) -> tuple[SessaoAula, ...]:
        """Cópia imutável das sessões atualmente cadastradas."""

        return tuple(self._sessoes)

    def adicionar_sessao(self, sessao: SessaoAula) -> None:
        """Adicione uma sessão cuja identidade ainda não pertence à disciplina."""

        if not isinstance(sessao, SessaoAula):
            raise TypeError("sessão deve ser uma SessaoAula")
        if any(item.identificador == sessao.identificador for item in self._sessoes):
            raise ValueError("sessão já cadastrada na disciplina")
        self._sessoes.append(sessao)


def _texto_obrigatorio(valor: object, campo: str) -> str:
    """Normalize um campo textual obrigatório na fronteira do domínio."""

    if not isinstance(valor, str):
        raise TypeError(f"{campo} deve ser texto")
    normalizado = valor.strip()
    if not normalizado:
        raise ValueError(f"{campo} é obrigatório")
    return normalizado
