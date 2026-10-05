from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_role
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowRun
from app.db.session import get_db
from app.schemas.requests import WorkflowIn, WorkflowPatch
from app.schemas.serializers import run_out, workflow_out
from app.services import workflow_service as ws
from app.workflows import actions as A
from app.workflows import conditions as C

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/meta")
def meta(_: User = Depends(get_current_user)):
    return {"triggers": sorted(C.TRIGGERS), "fields": C.FIELDS, "operators": sorted(C.OPS), "actions": A.ACTION_TYPES,
            "trigger_fields": {k: list(v) for k, v in C.TRIGGER_FIELDS.items()}}


@router.get("")
def list_workflows(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    runs = dict(db.query(WorkflowRun.workflow_id, func.count(WorkflowRun.id)).group_by(WorkflowRun.workflow_id).all())
    matched = dict(db.query(WorkflowRun.workflow_id, func.count(WorkflowRun.id)).filter(WorkflowRun.matched.is_(True)).group_by(WorkflowRun.workflow_id).all())
    return [workflow_out(w, runs.get(w.id, 0), matched.get(w.id, 0)) for w in db.query(Workflow).order_by(Workflow.id).all()]


@router.post("", status_code=201)
def create(body: WorkflowIn, db: Session = Depends(get_db), user: User = Depends(require_role("reviewer"))):
    return workflow_out(ws.create(db, user, **body.model_dump()))


@router.patch("/{wf_id}")
def update(wf_id: int, body: WorkflowPatch, db: Session = Depends(get_db), user: User = Depends(require_role("reviewer"))):
    return workflow_out(ws.update(db, user, wf_id, **body.model_dump()))


@router.delete("/{wf_id}", status_code=204)
def delete(wf_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("reviewer"))):
    ws.delete(db, user, wf_id)
    return Response(status_code=204)


@router.post("/{wf_id}/run")
def run_now(wf_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("reviewer"))):
    return ws.run_now(db, user, wf_id)


@router.get("/runs")
def runs(workflow_id: int | None = None, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    names = {w.id: w.name for w in db.query(Workflow.id, Workflow.name).all()}
    return [run_out(r, names.get(r.workflow_id)) for r in ws.list_runs(db, workflow_id, limit)]
