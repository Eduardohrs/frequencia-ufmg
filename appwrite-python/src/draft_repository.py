"""Repositório de persistência para rascunhos de cadastro.

O banco é o configurado em ``SECURITY_DATABASE_ID``, passado explicitamente
pelo chamador (sem padrão): configuração ausente deve falhar alto.

Cada documento guarda o ``user_id`` do proprietário: API keys do Server SDK
ignoram as permissões de documento, então toda leitura/escrita valida o dono
antes de agir e as listagens filtram por ``user_id`` com ``Query.equal``.
"""

import json
from datetime import datetime
from typing import Any, cast

from appwrite.client import Client
from appwrite.exception import AppwriteException
from appwrite.id import ID
from appwrite.permission import Permission
from appwrite.query import Query
from appwrite.role import Role
from appwrite.services.databases import Databases

from appwrite_storage import (
    DRAFT_COLLECTION_ID,
    StorageNotFound,
    classify_error,
    list_all_documents,
    normalize_document,
)
from course_repository import validate_course_id


class DraftRepository:
    """Repositório para persistência de rascunhos de cadastro no Appwrite."""

    def __init__(
        self,
        client: Client,
        database_id: str,
        collection_id: str = DRAFT_COLLECTION_ID,
    ) -> None:
        """Inicializa o repositório de rascunhos."""
        self._client = client
        self._db = Databases(client)
        self._database_id = database_id
        self._collection_id = collection_id

    def save_draft(
        self,
        user_id: str,
        course_id: str,
        course_code: str,
        session_id: str,
        form_data: dict[str, Any],
        last_error: str | None = None,
        attempt_count: int = 1,
    ) -> str:
        """Salva um rascunho de cadastro com o proprietário registrado."""
        validate_course_id(course_id)
        if not user_id:
            raise ValueError("user_id is required")

        document_id = ID.unique()
        now = datetime.utcnow().isoformat()

        data: dict[str, Any] = {
            "user_id": user_id,
            "course_id": course_id,
            "course_code": course_code,
            "session_id": session_id,
            "form_data": json.dumps(form_data, ensure_ascii=False),
            "last_error": last_error,
            "attempt_count": attempt_count,
            "created_at": now,
            "updated_at": now,
        }

        try:
            self._db.create_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=document_id,
                data=data,
                permissions=[
                    Permission.read(Role.user(user_id)),
                    Permission.write(Role.user(user_id)),
                    Permission.delete(Role.user(user_id)),
                ],
            )
            return cast(str, document_id)
        except AppwriteException as error:
            raise classify_error(error, operation="create_document", document_level=False) from None

    def get_draft(self, draft_id: str, user_id: str) -> dict[str, Any] | None:
        """Recupera um rascunho do usuário; devolve None se não for do usuário."""
        try:
            response = self._db.get_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=draft_id,
            )
        except AppwriteException as error:
            translated = classify_error(error, operation="get_document", document_level=True)
            if isinstance(translated, StorageNotFound):
                return None
            raise translated from None
        document = normalize_document(response)
        if document.get("user_id") != user_id:
            return None
        if "form_data" in document:
            document["form_data"] = json.loads(document["form_data"])
        return document

    def update_draft(
        self,
        draft_id: str,
        user_id: str,
        form_data: dict[str, Any] | None = None,
        last_error: str | None = None,
        attempt_count: int | None = None,
    ) -> bool:
        """Atualiza um rascunho do usuário."""
        if self.get_draft(draft_id, user_id) is None:
            return False
        data: dict[str, Any] = {
            "updated_at": datetime.utcnow().isoformat(),
        }
        if form_data is not None:
            data["form_data"] = json.dumps(form_data, ensure_ascii=False)
        if last_error is not None:
            data["last_error"] = last_error
        if attempt_count is not None:
            data["attempt_count"] = attempt_count

        try:
            self._db.update_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=draft_id,
                data=data,
            )
            return True
        except AppwriteException as error:
            translated = classify_error(error, operation="update_document", document_level=True)
            if isinstance(translated, StorageNotFound):
                return False
            raise translated from None

    def list_drafts(
        self,
        user_id: str,
        course_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista rascunhos do usuário, opcionalmente filtrados por curso e sessão."""
        if not user_id:
            raise ValueError("user_id is required")
        queries = [Query.equal("user_id", user_id)]
        if course_id:
            queries.append(Query.equal("course_id", course_id))
        if session_id:
            queries.append(Query.equal("session_id", session_id))
        drafts = list_all_documents(self._db, self._database_id, self._collection_id, queries)
        for draft in drafts:
            if "form_data" in draft:
                draft["form_data"] = json.loads(draft["form_data"])
        return drafts

    def delete_draft(self, draft_id: str, user_id: str) -> bool:
        """Remove um rascunho do usuário."""
        if self.get_draft(draft_id, user_id) is None:
            return False
        try:
            self._db.delete_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=draft_id,
            )
            return True
        except AppwriteException as error:
            translated = classify_error(error, operation="delete_document", document_level=True)
            if isinstance(translated, StorageNotFound):
                return False
            raise translated from None
