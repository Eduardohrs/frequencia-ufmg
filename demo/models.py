"""Regras do protótipo. Uma aula corresponde a 50 minutos."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

SITUACOES = (
    "presente",
    "ausente",
    "atrasado",
    "saiu mais cedo",
    "cancelada",
    "sem chamada",
)


class PoliticaChamada(ABC):
    """Calcula faltas após a disciplina validar a situação e a quantidade de aulas."""

    @abstractmethod
    def calcular_faltas(self, situacao: str, aulas: int) -> int:
        """Retorna faltas em unidades de 50 minutos."""


class ChamadaUnica(PoliticaChamada):
    """Atraso ou saída antecipada não gera falta no bloco."""

    def calcular_faltas(self, situacao, aulas):
        return aulas if situacao == "ausente" else 0


class ChamadaDupla(PoliticaChamada):
    """Atraso ou saída antecipada perde metade das aulas do bloco."""

    def calcular_faltas(self, situacao, aulas):
        if situacao == "ausente":
            return aulas
        return aulas // 2 if situacao in ("atrasado", "saiu mais cedo") else 0


@dataclass(frozen=True)
class Registro:
    """Retrato imutável de uma aula prevista e de sua frequência atual."""

    dia: date
    aulas: int
    situacao: str = "pendente"
    faltas: int | None = None


class Disciplina:
    """Guarda a grade e valida cada registro antes de substituir seu estado."""

    def __init__(self, codigo, nome, chamadas, aulas, datas):
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
        dias = tuple(datas)
        if not dias or any(type(d) is not date for d in dias):
            raise ValueError("Informe ao menos uma data válida.")
        if len(set(dias)) != len(dias):
            raise ValueError("A grade não pode repetir uma data.")
        self._codigo = codigo.strip().upper()
        self._nome = nome.strip()
        self._chamadas = chamadas
        self._politica = ChamadaUnica() if chamadas == 1 else ChamadaDupla()
        self._registros = {d: Registro(d, aulas) for d in sorted(dias)}

    @property
    def codigo(self):
        return self._codigo

    @property
    def nome(self):
        return self._nome

    @property
    def chamadas(self):
        return self._chamadas

    @property
    def registros(self):
        """A tupla e seus registros não permitem alterar a coleção interna."""
        return tuple(self._registros.values())

    def registrar_presenca(self, dia: date, situacao: str, *, corrigir=False):
        """Registra uma data da grade; repetir exige correção explícita."""
        if type(dia) is not date or dia not in self._registros:
            raise ValueError("A data não faz parte da grade desta disciplina.")
        if situacao not in SITUACOES:
            raise ValueError("Situação de frequência inválida.")
        anterior = self._registros[dia]
        if anterior.situacao != "pendente" and not corrigir:
            raise ValueError("Esta data já foi registrada. Use Corrigir registro.")
        faltas = self._politica.calcular_faltas(situacao, anterior.aulas)
        novo = Registro(dia, anterior.aulas, situacao, faltas)
        self._registros[dia] = novo
        return novo

    def resumo(self):
        """Calcula a partir da grade atual, sem presumir presença nas pendências."""
        ativos = [r for r in self.registros if r.situacao != "cancelada"]
        total = sum(r.aulas for r in ativos)
        pendentes = sum(r.aulas for r in ativos if r.faltas is None)
        faltas = sum(r.faltas or 0 for r in ativos)
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
    """Cadastro iniciado vazio; impede dois códigos iguais."""

    def __init__(self):
        self._disciplinas = {}

    @property
    def disciplinas(self):
        return tuple(self._disciplinas.values())

    def criar_disciplina(self, codigo, nome, chamadas, aulas, datas):
        """Cria a disciplina e sua grade; rejeições não mudam o cadastro."""
        nova = Disciplina(codigo, nome, chamadas, aulas, datas)
        if nova.codigo in self._disciplinas:
            raise ValueError("Já existe uma disciplina com esse código.")
        self._disciplinas[nova.codigo] = nova
        return nova

    def obter_disciplina(self, codigo):
        chave = codigo.strip().upper()
        if chave not in self._disciplinas:
            raise ValueError("Disciplina não encontrada. Cadastre-a primeiro.")
        return self._disciplinas[chave]
