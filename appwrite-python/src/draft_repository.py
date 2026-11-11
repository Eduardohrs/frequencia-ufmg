"""Repositório de persistência para rascunhos de cadastro."""

import json
from datetime import datetime
from typing import Any

from appwrite.client import Client
from appwrite.enums import Permission, Role
from appwrite.id import ID
from appwrite.services.databases import Databases

from course_repository import validate_course_id


class DraftRepository:
    """Repositório para persistência de rascunhos de cadastro no Appwrite."""

    def __init__(
        self,
        client: Client,
        database_id: str = "frequencia_ufmg",
        collection_id: str = "registration_drafts",
    ) -> None:
        """Inicializa o repositório de rascunhos."""
        self._client = client
        self._db = Databases(client)
        self._database_id = database_id
        self._collection_id = collection_id

    def save_draft(
        self,
        course_id: str,
        course_code: str,
        session_id: str,
        form_data: dict[str, Any],
        last_error: str | None = None,
        attempt_count: int = 1,
    ) -> str:
        """Salva um rascunho de cadastro."""
        validate_course_id(course_id)

        document_id = ID.unique()
        now = datetime.utcnow().isoformat()

        data: dict[str, Any] = {
            "course_id": course_id,
            "course_code": course_code,
            "session_id": session_id,
            "form_data": json.dumps(form_data, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
            "attempt_count": attempt_count,
            "last_error": last_error,
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
            print(f"Error saving draft: {e}")
            raise

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        """Recupera um rascunho pelo ID."""
        try:
            response = self._db.get_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=draft_id,
            )
            if response and "form_data" in response:
                response["form_data"] = json.loads(response["form_data"])
            return response
        except Exception:
            return None

    def update_draft(
        self,
        draft_id: str,
        form_data: dict[str, Any] | None = None,
        last_error: str | None = None,
        attempt_count: int | None = None,
    ) -> bool:
        """Atualiza um rascunho."""
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
        except Exception:
            return False

    def list_drafts(
        self,
        course_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista rascunhos, opcionalmente filtrados por curso e sessão."""
        queries = []
        if course_id:
            queries.append(f"course_id = {json.dumps(course_id)}")
        if session_id:
            queries.append(f"session_id = {json.dumps(session_id)}")

        try:
            response = self._db.list_documents(
                database_id=self._database_id,
                collection_id=self._collection_id,
                queries=queries,
            )
            drafts = response.get("documents", [])
            for draft in drafts:
                if "form_data" in draft:
                    draft["form_data"] = json.loads(draft["form_data"])
            return drafts
        except Exception:
            return []

    def delete_draft(self, draft_id: str) -> bool:
        """Remove um rascunho."""
        try:
            self._db.delete_document(
                database_id=self._database_id,
                collection_id=self._collection_id,
                document_id=draft_id,
            )
            return True
        except Exception:
            return False
