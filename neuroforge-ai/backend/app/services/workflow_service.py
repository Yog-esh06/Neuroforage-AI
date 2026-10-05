"""Workflow CRUD + validation; execution lives in app/workflows/engine.py."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowRun
from app.services import audit_service
from app.workflows import actions as A
from app.workflows import conditions as C
from app.workflows import engine


def validate(trigger: str, conditions: dict | None, actions: list) -> None:
    if trigger not in C.TRIGGERS:
        raise ValidationFailed(f"Unknown trigger '{trigger}'", details={"allowed": sorted(C.TRIGGERS)})
    C.validate_conditions(conditions, trigger)
    A.validate_actions(actions)


def get(db: Session, wf_id: int) -> Workflow:
    wf = db.get(Workflow, wf_id)
    if not wf:
        raise NotFoundError(f"Workflow {wf_id} not found")
    return wf


def create(db: Session, user: User, *, name: str, description: str, trigger: str, conditions: dict, actions: list, enabled: bool = True) -> Workflow:
    validate(trigger, conditions, actions)
    if db.query(Workflow).filter(Workflow.name == name).first():
        raise ConflictError(f"A workflow named '{name}' already exists")
    wf = Workflow(name=name, description=description, trigger=trigger, conditions=conditions, actions=actions, enabled=enabled,
                  created_by=user.id if user.id else None)
    db.add(wf)
    db.flush()
    audit_service.log_event(db, action="workflow_created", user=user, entity_type="workflow", entity_id=wf.id, summary=f"Workflow '{name}' created",
                            details={"trigger": trigger, "conditions": conditions, "actions": actions})
    db.commit()
    return wf


def update(db: Session, user: User, wf_id: int, **fields) -> Workflow:
    wf = get(db, wf_id)
    new = {k: v for k, v in fields.items() if v is not None}
    validate(new.get("trigger", wf.trigger), new.get("conditions", wf.conditions), new.get("actions", wf.actions))
    if "name" in new and new["name"] != wf.name and db.query(Workflow).filter(Workflow.name == new["name"]).first():
        raise ConflictError(f"A workflow named '{new['name']}' already exists")
    for k, v in new.items():
        setattr(wf, k, v)
    audit_service.log_event(db, action="workflow_updated", user=user, entity_type="workflow", entity_id=wf.id, summary=f"Workflow '{wf.name}' updated",
                            details={"fields": sorted(new)})
    db.commit()
    return wf


def delete(db: Session, user: User, wf_id: int) -> None:
    wf = get(db, wf_id)
    audit_service.log_event(db, action="workflow_deleted", user=user, entity_type="workflow", entity_id=wf.id, summary=f"Workflow '{wf.name}' deleted")
    db.delete(wf)
    db.commit()


def run_now(db: Session, user: User, wf_id: int) -> dict:
    wf = get(db, wf_id)
    out = engine.backfill(db, wf, user)
    db.commit()
    return out


def list_runs(db: Session, workflow_id: int | None = None, limit: int = 50) -> list[WorkflowRun]:
    q = db.query(WorkflowRun)
    if workflow_id:
        q = q.filter(WorkflowRun.workflow_id == workflow_id)
    return q.order_by(WorkflowRun.id.desc()).limit(limit).all()
