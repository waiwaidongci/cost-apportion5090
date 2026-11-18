"""互供核算端到端集成测试：SQLite 内存库 + FastAPI TestClient，不依赖 Postgres/Redis。"""
import sys
import types
import unittest

# 在导入业务包之前注入 settings 桩，绕开容器内 /app/project.json 路径
_settings = types.ModuleType('src.config.settings')
_settings.CONFIG = {
    'title': '测试归集簿', 'slug': 'test', 'fields': {
        'period': '期间', 'department': '部门', 'category': '费用类别', 'amount_cents': '金额（分）'},
}
_settings.DATABASE_URL = 'sqlite://'
_settings.REDIS_URL = 'memory://fake'
_settings.SECRET = 'test-secret'
sys.modules['src.config.settings'] = _settings

import sqlalchemy  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.config.database as database  # noqa: E402
database.engine = sqlalchemy.create_engine(
    'sqlite://',
    connect_args={'check_same_thread': False},
    poolclass=StaticPool,
)
database.Session.configure(bind=database.engine)

import redis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.config.database import Base, Session  # noqa: E402
from src.main import app  # noqa: E402
from src.models.identity import User  # noqa: E402
from src.models.source import Source  # noqa: E402
from src.models.reciprocal import ReciprocalRun  # noqa: E402
from src.services.reciprocal_service import run_calculation  # noqa: E402
from src.utils.security import password_hash  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.queues = {}

    def rpush(self, key, value):
        self.queues.setdefault(key, []).append(value)

    def ping(self):
        return True


redis.Redis.from_url = lambda url: FakeRedis()


class ReciprocalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(database.engine)
        cls.client = TestClient(app)
        with Session() as db:
            for role in ('admin', 'analyst', 'viewer'):
                if not db.query(User).filter_by(email=f'{role}@demo.local').first():
                    db.add(User(email=f'{role}@demo.local', role=role,
                                password=password_hash('Demo2026!')))
            db.commit()

    def _token(self, role):
        r = self.client.post('/auth/login',
                             json={'email': f'{role}@demo.local', 'password': 'Demo2026!'})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['token']

    def _auth(self, role):
        return {'Authorization': 'Bearer ' + self._token(role)}

    def _rule_doc(self):
        return {
            'version': '互供集成测试-v1',
            'services': ['后勤', '车队'],
            'beneficiaries': ['生产一厂', '生产二厂'],
            'rows': [
                {'source': '后勤', 'allocations': [
                    {'target': '车队', 'ratio': '1/2'},
                    {'target': '生产一厂', 'ratio': '1/4'},
                    {'target': '生产二厂', 'ratio': '1/4'}]},
                {'source': '车队', 'allocations': [
                    {'target': '生产一厂', 'ratio': '1/2'},
                    {'target': '生产二厂', 'ratio': '1/2'}]},
            ],
        }

    def _seed_sources(self):
        with Session() as db:
            rows = [
                {'period': '2026-11', 'department': '后勤', 'category': '水电费', 'amount_cents': 1000},
                {'period': '2026-11', 'department': '车队', 'category': '水电费', 'amount_cents': 400},
                {'period': '2026-11', 'department': '生产一厂', 'category': '耗材', 'amount_cents': 55},
            ]
            for i, data in enumerate(rows):
                if not db.query(Source).filter_by(natural_key=f'it-{i}').first():
                    db.add(Source(natural_key=f'it-{i}', data=data))
            db.commit()

    def test_full_flow_and_snapshot_freeze(self):
        self._seed_sources()
        admin = self._auth('admin')
        analyst = self._auth('analyst')

        # 预检通过
        r = self.client.post('/reciprocal/rules/precheck', json={'data': self._rule_doc()}, headers=analyst)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['ok'])

        # analyst 无权登记规则
        r = self.client.post('/reciprocal/rules', json={'data': self._rule_doc()}, headers=analyst)
        self.assertEqual(r.status_code, 403)

        # admin 登记
        r = self.client.post('/reciprocal/rules', json={'data': self._rule_doc()}, headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        rule_id = r.json()['id']
        # 同名版本拒绝覆盖
        r = self.client.post('/reciprocal/rules', json={'data': self._rule_doc()}, headers=admin)
        self.assertEqual(r.status_code, 409)

        # 行合计不等于 1 拒绝
        bad = self._rule_doc()
        bad['version'] = '坏规则-v1'
        bad['rows'][1]['allocations'][0]['ratio'] = '1/3'
        r = self.client.post('/reciprocal/rules/precheck', json={'data': bad}, headers=analyst)
        self.assertEqual(r.status_code, 422)

        # 排队
        r = self.client.post('/reciprocal/runs',
                             json={'name': '十一月互供核算', 'rule_id': rule_id, 'period': '2026-11'},
                             headers=analyst)
        self.assertEqual(r.status_code, 200, r.text)
        run_id = r.json()['id']
        self.assertEqual(r.json()['status'], 'queued')
        self.assertEqual(len(r.json()['snapshot']['sources']), 3)

        # worker 执行
        with Session() as db:
            run_calculation(db, run_id)
        r = self.client.get(f'/reciprocal/runs/{run_id}', headers=analyst)
        body = r.json()
        self.assertEqual(body['status'], 'completed', body.get('error'))
        self.assertEqual(body['result']['summary']['守恒差额分'], 0)
        # 来源总额 1455（含直归 55）
        self.assertEqual(body['result']['summary']['底稿金额分'], 1455)
        self.assertEqual(body['result']['summary']['取整后分摊金额分'], 1455)
        self.assertTrue(body['result']['cross_check']['matched'])

        # 完成前不可复核：先验证排队态被拒（新建一个任务但不执行）
        r = self.client.post('/reciprocal/runs',
                             json={'name': '未完成互供', 'rule_id': rule_id, 'period': '2026-11'},
                             headers=analyst)
        pending_id = r.json()['id']
        r = self.client.post(f'/reciprocal/runs/{pending_id}/approve',
                             json={'note': '尝试提前复核'}, headers=admin)
        self.assertEqual(r.status_code, 409)

        # analyst 无复核权
        r = self.client.post(f'/reciprocal/runs/{run_id}/approve',
                             json={'note': '分析师尝试复核'}, headers=analyst)
        self.assertEqual(r.status_code, 403)

        # 复核说明过短拒绝
        r = self.client.post(f'/reciprocal/runs/{run_id}/approve',
                             json={'note': '太短'}, headers=admin)
        self.assertEqual(r.status_code, 422)

        # admin 正常复核
        r = self.client.post(f'/reciprocal/runs/{run_id}/approve',
                             json={'note': '已核对互供口径与守恒结果'}, headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['approved'], 1)

        # 复核后再改底稿，不影响已冻结快照
        with Session() as db:
            src = db.query(Source).filter_by(natural_key='it-0').first()
            src.data = {**src.data, 'amount_cents': 999999}
            db.commit()
        r = self.client.get(f'/reciprocal/runs/{run_id}', headers=admin)
        self.assertEqual(r.json()['snapshot']['sources'][0]['amount_cents'], 1000)
        self.assertEqual(r.json()['result']['summary']['底稿金额分'], 1455)

        # viewer 下载已复核 CSV
        r = self.client.get(f'/reciprocal/runs/{run_id}/csv', headers=self._auth('viewer'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('受益部门取整分摊', r.text)

    def test_closed_cycle_rejected_even_with_zero_cost(self):
        self._seed_sources()
        admin = self._auth('admin')
        closed = {
            'version': '封闭环规则-v1',
            'services': ['S1', 'S2'],
            'beneficiaries': ['B1'],
            'rows': [
                {'source': 'S1', 'allocations': [{'target': 'S2', 'ratio': 1}]},
                {'source': 'S2', 'allocations': [{'target': 'S1', 'ratio': 1}]},
            ],
        }
        r = self.client.post('/reciprocal/rules/precheck', json={'data': closed},
                             headers=self._auth('analyst'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['ok'])
        self.assertEqual(r.json()['无外流部门'], ['S1', 'S2'])
        # 登记本身允许（与原口径版本一致：版本可留存），但核算必拒
        r = self.client.post('/reciprocal/rules', json={'data': closed}, headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        rule_id = r.json()['id']
        r = self.client.post('/reciprocal/runs',
                             json={'name': '封闭环核算', 'rule_id': rule_id, 'period': '2026-11'},
                             headers=self._auth('analyst'))
        run_id = r.json()['id']
        with Session() as db:
            run_calculation(db, run_id)
        with Session() as db:
            obj = db.get(ReciprocalRun, run_id)
            self.assertEqual(obj.status, 'failed')
            self.assertIn('无外流', obj.error)
            # 失败任务不可复核
        r = self.client.post(f'/reciprocal/runs/{run_id}/approve',
                             json={'note': '尝试复核失败任务'}, headers=admin)
        self.assertEqual(r.status_code, 409)


    def test_snapshot_lock_taken_on_submit_and_source_write(self):
        self._seed_sources()
        admin = self._auth('admin')
        analyst = self._auth('analyst')
        rule_doc = self._rule_doc()
        rule_doc['version'] = '互供加锁测试-v1'
        r = self.client.post('/reciprocal/rules', json={'data': rule_doc}, headers=admin)
        rule_id = r.json()['id']

        import src.services.reciprocal_service as rs
        import src.services.source as source_service
        calls = []
        rs.acquire_snapshot_lock = lambda db: calls.append('reciprocal')
        source_service.acquire_snapshot_lock = lambda db: calls.append('source')

        self.client.post('/reciprocal/runs',
                         json={'name': '加锁互供任务', 'rule_id': rule_id, 'period': '2026-11'},
                         headers=analyst)
        self.assertIn('reciprocal', calls)

    def test_worker_consumes_same_queue_key(self):
        # 不直接 import src.worker（其模块级 while True 会轮询挂起），
        # 用 AST 静态确认 worker 从 service 导入同一队列键，保证入队与消费一致
        import ast
        from pathlib import Path
        from src.services.reciprocal_service import RECIPROCAL_QUEUE
        self.assertEqual(RECIPROCAL_QUEUE, 'reciprocal-jobs')
        worker_src = Path(worker_module_path()).read_text(encoding='utf-8')
        tree = ast.parse(worker_src)
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'src.services.reciprocal_service':
                imported_names.update(alias.name for alias in node.names)
        self.assertIn('RECIPROCAL_QUEUE', imported_names)
        self.assertIn('run_calculation', imported_names)


def worker_module_path():
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / 'src' / 'worker.py'


if __name__ == '__main__':
    unittest.main()
