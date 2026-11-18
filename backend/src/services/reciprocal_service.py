"""互供关系登记与互供核算任务：同一时点冻结底稿与互供关系，完成后才可复核。"""
import hashlib
import json
import time

from fastapi import HTTPException

from src.config.settings import REDIS_URL
from src.models.source import Source
from src.models.reciprocal import ReciprocalRule, ReciprocalRun
from src.services.audit import log
from src.services.reciprocal.engine import (
    validate_rule,
    reciprocal_allocate,
    diagnose,
    RuleValidationError,
)
from src.services.locking import acquire_snapshot_lock
import redis

RECIPROCAL_QUEUE = 'reciprocal-jobs'


def save_rule(db, user, body):
    """登记互供关系版本；严格校验有理数比例与行合计，版本名不可覆盖。

    封闭循环不在登记时拦截（版本可留存留痕），而在预检接口指出、在核算时拒绝。
    """
    try:
        normalized = validate_rule(body)
    except RuleValidationError as exc:
        raise HTTPException(422, str(exc))
    if db.query(ReciprocalRule).filter_by(version=normalized['version']).first():
        raise HTTPException(409, '互供关系版本名已存在，历史版本不可覆盖')
    detection = diagnose(normalized['services'], normalized['beneficiaries'],
                         normalized['proportions'])
    # 入库结构保留原始 ratio（字符串/数字），读取时重新解析，避免 JSON 丢精度
    obj = ReciprocalRule(version=normalized['version'], data=body, created=time.time())
    db.add(obj)
    log(db, user.email, 'reciprocal.rule.create',
        f"{normalized['version']} 封闭环={bool(detection['trapped'])}")
    db.commit()
    return obj


def precheck_rule(db, user, body):
    """登记前预检：校验行合计并返回封闭环诊断，封闭循环即使零费用也在此指出。"""
    try:
        rule = validate_rule(body)
    except RuleValidationError as exc:
        raise HTTPException(422, str(exc))
    detection = diagnose(rule['services'], rule['beneficiaries'], rule['proportions'])
    return {
        'ok': not detection['trapped'],
        '服务部门数': len(rule['services']),
        '受益部门数': len(rule['beneficiaries']),
        '无外流部门': detection['trapped'],
        '封闭环分组': detection['closed_groups'],
        '部门外流可达': detection['has_outflow'],
    }


def _load_entries(db, period):
    query = db.query(Source).order_by(Source.id)
    entries = [x.data for x in query.all()]
    if period != '全部':
        entries = [data for data in entries if data.get('period') == period]
    return entries


def submit_reciprocal(db, user, body):
    """排队互供核算：在同一事务、同一时点读取底稿与互供关系并整体冻结快照。

    通过事务级咨询锁与底稿写入互斥；快照一旦写入，后续任何修改都不影响该任务，
    且任务完成（completed）之前不允许复核。
    """
    acquire_snapshot_lock(db)
    rule_obj = db.get(ReciprocalRule, body.rule_id)
    if not rule_obj:
        raise HTTPException(404, '互供关系版本不存在')
    entries = _load_entries(db, body.period)
    if not entries:
        raise HTTPException(422, '所选期间没有底稿')
    try:
        validate_rule(rule_obj.data)  # 仅做严格校验，快照仍保存原始 data
    except RuleValidationError as exc:
        raise HTTPException(422, f'已登记互供关系不合法：{exc}')
    snapshot = {
        'rule_id': rule_obj.id,
        'rule_version': rule_obj.version,
        'rule': rule_obj.data,
        'sources': entries,
        'period': body.period,
        'frozen_at': time.time(),
    }
    checksum = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    obj = ReciprocalRun(
        name=body.name,
        status='queued',
        period=body.period,
        rule_id=rule_obj.id,
        rule_version=rule_obj.version,
        snapshot=snapshot,
        checksum=checksum,
        created=time.time(),
        approved=0,
    )
    db.add(obj)
    log(db, user.email, 'reciprocal.run.queue', body.name)
    db.commit()
    redis.Redis.from_url(REDIS_URL).rpush(RECIPROCAL_QUEUE, obj.id)
    return obj


def run_calculation(db, run_id):
    """worker 调用：基于冻结快照执行精确互供核算，结果只写回任务自身。"""
    obj = db.get(ReciprocalRun, run_id)
    if not obj or obj.status != 'queued':
        return
    obj.status = 'running'
    db.commit()
    try:
        rule = validate_rule(obj.snapshot['rule'])
        obj.result = reciprocal_allocate(obj.snapshot['sources'], rule)
        obj.status = 'completed'
        obj.finished = time.time()
    except Exception as exc:  # 含封闭环拒绝与超时拒绝，错误信息透出供复核
        obj.status = 'failed'
        obj.error = str(exc)
        obj.finished = time.time()
    db.commit()


def approve_reciprocal(db, user, run_id, note):
    """仅已完成（且未复核）的任务可复核；排队/运行/失败一律拒绝。"""
    obj = db.get(ReciprocalRun, run_id)
    if not obj:
        raise HTTPException(404, '互供核算任务不存在')
    if obj.status != 'completed':
        raise HTTPException(409, '仅可复核已完成的互供核算，排队或运行中的任务不可复核')
    if obj.approved:
        raise HTTPException(409, '该任务已经复核')
    obj.approved = 1
    obj.review = note
    log(db, user.email, 'reciprocal.run.approve', run_id)
    db.commit()
    return obj
