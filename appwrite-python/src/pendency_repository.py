"""Repositório de persistência para pendências de horário."""

import json
from datetime import datetime
from typing import Any

from appwrite.client import Client
from appwrite.enums import Permission, Role
from appwrite.id import ID
from appwrite.services.databases import Databases

from course_repository import validate_course_id


class PendencyRepository:
    """Repositório para persistência de pendências de horário no Appwrite."""

    def __init__(
        self,
        client: Client,
        database_id: str = "frequencia_ufmg",
        collection_id: str = "schedule_pendencies",
    ) -> None:
        """Inicializa o repositório de pendências."""
        self._client = client
        self._db = Databases(client)
        self._database_id = database_id
        self._collection_id = collection_id

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
        """Salva uma pendência de horário."""
        validate_course_id(course_id)

        document_id = ID.unique()
        now = datetime.utcnow().isoformat()

        data: dict[str, Any] = {
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

        try:
            self._db.create_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=document_id,
                data=data,
                permissions=[
                    Permission.read(Role.user(course_id)),
                    Permission.write(Role.user(course_id)),
                    Permission.delete(Role.user(course_id)),
                ],
            )
            return document_id
        except Exception as e:
            print(f"Error saving pendency: {e}")
            raise

    def get_pendency(self, pendency_id: str) -> dict[str, Any] | None:
        """Recupera uma pendência pelo ID."""
        try:
            response = self._db.get_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=pendency_id,
            )
            return response
        except Exception:
            return None

    def update_decision(
        self,
        pendency_id: str,
        decision: str,
        status: str = "resolved",
    ) -> bool:
        """Atualiza a decisão de uma pendência."""
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
        except Exception:
            return False

    def list_pendencies(
        self,
        course_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista pendências, opcionalmente filtradas por curso e status."""
        queries = []
        if course_id:
            queries.append(f"course_id = {json.dumps(course_id)}")
        if status:
            queries.append(f"status = {json.dumps(status)}")

        try:
            response = self._db.list_documents(
                database_id=self._database_id,
                collection_id=self._collection_id,
                queries=queries,
            )
            return response.get("documents", [])
        except Exception:
            return []

    def delete_pendency(self, pendency_id: str) -> bool:
        """Remove uma pendência."""
        try:
            self._db.delete_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=pendency_id,
            )
            return True
        except Exception:
            return False
