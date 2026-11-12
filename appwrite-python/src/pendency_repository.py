"""Repositório de persistência para pendências de horário.

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
    DATABASE_ID,
    PENDENCY_COLLECTION_ID,
    StorageNotFound,
    classify_error,
    list_all_documents,
    normalize_document,
)
from course_repository import validate_course_id


class PendencyRepository:
    """Repositório para persistência de pendências de horário no Appwrite."""

    def __init__(
        self,
        client: Client,
        database_id: str = DATABASE_ID,
        collection_id: str = PENDENCY_COLLECTION_ID,
    ) -> None:
        """Inicializa o repositório de pendências."""
        self._client = client
        self._db = Databases(client)
        self._database_id = database_id
        self._collection_id = collection_id

    def save_pendency(
        self,
        user_id: str,
        course_id: str,
        course_code: str,
        course_name: str,
        current_schedule: str,
        new_schedule: str,
        reason: str,
        decision: str | None = None,
        status: str = "pending",
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Salva uma pendência de horário com o proprietário registrado."""
        validate_course_id(course_id)
        if not user_id:
            raise ValueError("user_id is required")

        document_id = ID.unique()
        now = datetime.utcnow().isoformat()

        data: dict[str, Any] = {
            "user_id": user_id,
            "course_id": course_id,
            "course_code": course_code,
            "course_name": course_name,
            "current_schedule": current_schedule,
            "new_schedule": new_schedule,
            "reason": reason,
            "decision": decision,
            "created_at": now,
            "updated_at": now,
            "status": status,
        }
        if payload is not None:
            data["payload"] = json.dumps(payload, ensure_ascii=False)

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

    def get_pendency(self, pendency_id: str, user_id: str) -> dict[str, Any] | None:
        """Recupera uma pendência do usuário; devolve None se não for do usuário."""
        try:
            response = self._db.get_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=pendency_id,
            )
        except AppwriteException as error:
            translated = classify_error(error, operation="get_document", document_level=True)
            if isinstance(translated, StorageNotFound):
                return None
            raise translated from None
        document = normalize_document(response)
        if document.get("user_id") != user_id:
            return None
        return document

    def update_decision(
        self,
        pendency_id: str,
        user_id: str,
        decision: str,
        status: str = "resolved",
    ) -> bool:
        """Atualiza a decisão de uma pendência do usuário."""
        if self.get_pendency(pendency_id, user_id) is None:
            return False
        try:
            self._db.update_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=pendency_id,
                data={
                    "decision": decision,
                    "updated_at": datetime.utcnow().isoformat(),
                    "status": status,
                },
            )
            return True
        except AppwriteException as error:
            translated = classify_error(error, operation="update_document", document_level=True)
            if isinstance(translated, StorageNotFound):
                return False
            raise translated from None

    def list_pendencies(
        self,
        user_id: str,
        course_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista pendências do usuário, opcionalmente filtradas por curso e status."""
        if not user_id:
            raise ValueError("user_id is required")
        queries = [Query.equal("user_id", user_id)]
        if course_id:
            queries.append(Query.equal("course_id", course_id))
        if status:
            queries.append(Query.equal("status", status))
        return list_all_documents(self._db, self._database_id, self._collection_id, queries)

    def delete_pendency(self, pendency_id: str, user_id: str) -> bool:
        """Remove uma pendência do usuário."""
        if self.get_pendency(pendency_id, user_id) is None:
            return False
        try:
            self._db.delete_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=pendency_id,
            )
            return True
        except AppwriteException as error:
            translated = classify_error(error, operation="delete_document", document_level=True)
            if isinstance(translated, StorageNotFound):
                return False
            raise translated from None
