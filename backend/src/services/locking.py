"""并发控制：排队冻结与底稿/关系写入共用同一把事务级咨询锁。

PostgreSQL 使用 pg_advisory_xact_lock，事务提交或回滚时自动释放；
非 Postgres（如测试用 SQLite）回退为空操作，由单事务保证快照一致。
"""
from sqlalchemy import text

# 固定常量键，取 'RECI' 的标识，全应用唯一
SNAPSHOT_LOCK_KEY = 1380014153


def acquire_snapshot_lock(db):
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': SNAPSHOT_LOCK_KEY})
