"""Import every model so `Base.metadata` is complete (Alembic autogenerate + create_all)."""
from app.db.models.audit import AuditLog
from app.db.models.document import (Chunk, Document, DocumentElement, DocumentVersion, Embedding, Page,
                                    ProcessingJob)
from app.db.models.knowledge import Entity, EntityMention, EntityRelationship
from app.db.models.reasoning import Answer, Citation, Contradiction, Insight, Query, RetrievalRun
from app.db.models.review import ReviewTask
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowRun

__all__ = [
    "AuditLog", "Chunk", "Document", "DocumentElement", "DocumentVersion", "Embedding", "Page", "ProcessingJob",
    "Entity", "EntityMention", "EntityRelationship", "Answer", "Citation", "Contradiction", "Insight", "Query",
    "RetrievalRun", "ReviewTask", "User", "Workflow", "WorkflowRun",
]
