"""Integração de persistência para CentralPendencias e GerenciadorRascunhos."""

from typing import Any, Protocol

from frequencia_ufmg.models import (
    CentralPendencias,
    DecisaoHorario,
    GerenciadorRascunhos,
    PendenciaHorario,
    RascunhoCadastro,
)


class PendencyStorage(Protocol):
    """Protocol para armazenamento de pendências."""

    def save_pendency(
        self,
        course_id: str,
        course_code: str,
        course_name: str,
        current_schedule: str,
        new_schedule: str,
        reason: str,
        decision: str | None = None,
        status: str = "pending",
    ) -> str:
        """Salva uma pendência."""
        ...

    def get_pendency(self, pendency_id: str) -> dict[str, Any] | None:
        """Recupera uma pendência."""
        ...

    def update_decision(
        self,
        pendency_id: str,
        decision: str,
        status: str = "resolved",
    ) -> bool:
        """Atualiza uma decisão."""
        ...

    def list_pendencies(
        self,
        course_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista pendências."""
        ...

    def delete_pendency(self, pendency_id: str) -> bool:
        """Remove uma pendência."""
        ...


class DraftStorage(Protocol):
    """Protocol para armazenamento de rascunhos."""

    def save_draft(
        self,
        course_id: str,
        course_code: str,
        session_id: str,
        form_data: dict[str, Any],
        last_error: str | None = None,
        attempt_count: int = 1,
    ) -> str:
        """Salva um rascunho."""
        ...

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        """Recupera um rascunho."""
        ...

    def update_draft(
        self,
        draft_id: str,
        form_data: dict[str, Any] | None = None,
        last_error: str | None = None,
        attempt_count: int | None = None,
    ) -> bool:
        """Atualiza um rascunho."""
        ...

    def list_drafts(
        self,
        course_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista rascunhos."""
        ...

    def delete_draft(self, draft_id: str) -> bool:
        """Remove um rascunho."""
        ...


class PersistentCentralPendencias(CentralPendencias):
    """Central de pendências com persistência."""

    def __init__(self, storage: PendencyStorage | None = None) -> None:
        """Inicializa com armazenamento opcional."""
        super().__init__()
        self._storage = storage
        self._load_pendencies()

    def _load_pendencies(self) -> None:
        """Carrega pendências do armazenamento."""
        if self._storage:
            pendencies = self._storage.list_pendencies(status="pending")
            for p in pendencies:
                pendencia = PendenciaHorario(
                    disciplina_codigo=p.get("course_code", ""),
                    disciplina_nome=p.get("course_name", ""),
                    horario_atual=p.get("current_schedule", ""),
                    horario_novo=p.get("new_schedule", ""),
                    motivo=p.get("reason", ""),
                )
                pendency_id = p.get("$id", "")
                self._pendencias[pendency_id] = pendencia
                
                # Carregar decisão se existir
                if p.get("decision"):
                    decision_str = p.get("decision", "")
                    if decision_str == "MANTER_ATUAL":
                        self._decisoes[pendency_id] = DecisaoHorario.MANTER_ATUAL
                    elif decision_str == "APLICAR_MUDANCA":
                        self._decisoes[pendency_id] = DecisaoHorario.APLICAR_MUDANCA
                    else:
                        self._decisoes[pendency_id] = DecisaoHorario.PENDENTE

    def adicionar_pendencia(self, pendencia: PendenciaHorario) -> str:
        """Adiciona uma pendência e persiste."""
        pendencia_id = super().adicionar_pendencia(pendencia)
        
        if self._storage:
            # Salvar no armazenamento
            self._storage.save_pendency(
                course_id="",  # Será preenchido no uso real
                course_code=pendencia.disciplina_codigo,
                course_name=pendencia.disciplina_nome,
                current_schedule=pendencia.horario_atual,
                new_schedule=pendencia.horario_novo,
                reason=pendencia.motivo,
            )
        
        return pendencia_id

    def registrar_decisao(
        self,
        pendencia_id: str,
        decisao: DecisaoHorario,
    ) -> None:
        """Registra a decisão e persiste."""
        super().registrar_decisao(pendencia_id, decisao)
        
        if self._storage:
            decision_str = decisao.value
            status = "resolved" if decisao != DecisaoHorario.PENDENTE else "pending"
            self._storage.update_decision(
                pendency_id=pendencia_id,
                decision=decision_str,
                status=status,
            )

    def remover_pendencia(self, pendencia_id: str) -> bool:
        """Remove uma pendência e apaga do armazenamento."""
        removed = super().remover_pendencia(pendencia_id)
        
        if removed and self._storage:
            self._storage.delete_pendency(pendencia_id)
        
        return removed


class PersistentGerenciadorRascunhos(GerenciadorRascunhos):
    """Gerenciador de rascunhos com persistência."""

    def __init__(self, storage: DraftStorage | None = None) -> None:
        """Inicializa com armazenamento opcional."""
        super().__init__()
        self._storage = storage
        self._load_drafts()

    def _load_drafts(self) -> None:
        """Carrega rascunhos do armazenamento."""
        if self._storage:
            drafts = self._storage.list_drafts()
            for d in drafts:
                rascunho = RascunhoCadastro(
                    disciplina_codigo=d.get("course_code", ""),
                    sessao_identificador=d.get("session_id", ""),
                    dados=d.get("form_data", {}),
                )
                draft_id = d.get("$id", "")
                self._rascunhos[draft_id] = rascunho

    def salvar_rascunho(
        self,
        disciplina_codigo: str,
        sessao_identificador: str,
        dados: dict[str, Any],
    ) -> str:
        """Salva um rascunho e persiste."""
        rascunho_id = super().salvar_rascunho(disciplina_codigo, sessao_identificador, dados)
        
        if self._storage:
            self._storage.save_draft(
                course_id="",  # Será preenchido no uso real
                course_code=disciplina_codigo,
                session_id=sessao_identificador,
                form_data=dados,
                last_error=None,
                attempt_count=1,
            )
        
        return rascunho_id

    def recuperar_rascunho(self, rascunho_id: str) -> RascunhoCadastro | None:
        """Recupera um rascunho do armazenamento ou memória."""
        # Verificar na memória primeiro
        result = super().recuperar_rascunho(rascunho_id)
        
        if result is None and self._storage:
            # Tentar carregar do armazenamento
            draft = self._storage.get_draft(rascunho_id)
            if draft:
                rascunho = RascunhoCadastro(
                    disciplina_codigo=draft.get("course_code", ""),
                    sessao_identificador=draft.get("session_id", ""),
                    dados=draft.get("form_data", {}),
                )
                self._rascunhos[rascunho_id] = rascunho
                return rascunho
        
        return result

    def remover_rascunho(self, rascunho_id: str) -> bool:
        """Remove um rascunho da memória e do armazenamento."""
        removed = super().remover_rascunho(rascunho_id)
        
        if removed and self._storage:
            self._storage.delete_draft(rascunho_id)
        return removed
        
        
