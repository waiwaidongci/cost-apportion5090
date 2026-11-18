from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from src.config.database import database
from src.controllers.auth import current, editor, admin
from src.models.reciprocal import ReciprocalRule, ReciprocalRun
from src.schemas.requests import DataInput, ReciprocalRunInput, ReviewInput
from src.services.reciprocal_service import (
    save_rule,
    precheck_rule,
    submit_reciprocal,
    approve_reciprocal,
)
from src.services.export import reciprocal_csv_text
from src.utils.serialize import row

router = APIRouter()


@router.get('/reciprocal/rules')
def rules(db=Depends(database), u=Depends(current)):
    return [row(x) for x in db.query(ReciprocalRule).order_by(ReciprocalRule.id.desc()).all()]


@router.post('/reciprocal/rules/precheck')
def rule_precheck(b: DataInput, db=Depends(database), u=Depends(editor)):
    return precheck_rule(db, u, b.data)


@router.post('/reciprocal/rules')
def rule_create(b: DataInput, db=Depends(database), u=Depends(admin)):
    return row(save_rule(db, u, b.data))


@router.get('/reciprocal/runs')
def runs(db=Depends(database), u=Depends(current)):
    return [row(x) for x in db.query(ReciprocalRun).order_by(ReciprocalRun.id.desc()).all()]


@router.get('/reciprocal/runs/{id}')
def detail(id: int, db=Depends(database), u=Depends(current)):
    obj = db.get(ReciprocalRun, id)
    if not obj:
        raise HTTPException(404, '互供核算任务不存在')
    return row(obj)


@router.post('/reciprocal/runs')
def run_create(b: ReciprocalRunInput, db=Depends(database), u=Depends(editor)):
    return row(submit_reciprocal(db, u, b))


@router.post('/reciprocal/runs/{id}/approve')
def run_approve(id: int, b: ReviewInput, db=Depends(database), u=Depends(admin)):
    return row(approve_reciprocal(db, u, id, b.note))


@router.get('/reciprocal/runs/{id}/csv')
def run_csv(id: int, db=Depends(database), u=Depends(current)):
    obj = db.get(ReciprocalRun, id)
    if not obj or obj.status != 'completed':
        raise HTTPException(409, '互供核算尚未完成')
    if u.role == 'viewer' and not obj.approved:
        raise HTTPException(403, '业务阅读者仅可下载已复核的互供核算')
    return Response(
        reciprocal_csv_text(obj.result),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="reciprocal-{id}.csv"'},
    )
