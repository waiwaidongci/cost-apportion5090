import json,random
from src.config.database import Base,engine,Session
from src.config.settings import CONFIG
from src.models.identity import User
from src.models.source import Source,Policy,Period
from src.models import run
from src.models.reciprocal import ReciprocalRule
from src.utils.security import password_hash
from src.services.validation import validate_source

def demo_reciprocal_rule():
 return {
  'version':'互供关系-v1',
  'services':['公共','后勤服务','车队服务'],
  'beneficiaries':['光学研究','材料研究','工艺研究'],
  'rows':[
   {'source':'公共','allocations':[
     {'target':'光学研究','ratio':'1/3'},
     {'target':'材料研究','ratio':'1/3'},
     {'target':'工艺研究','ratio':'1/3'}]},
   {'source':'后勤服务','allocations':[
     {'target':'车队服务','ratio':'1/2'},
     {'target':'光学研究','ratio':'1/4'},
     {'target':'材料研究','ratio':'1/8'},
     {'target':'工艺研究','ratio':'1/8'}]},
   {'source':'车队服务','allocations':[
     {'target':'光学研究','ratio':'2/5'},
     {'target':'材料研究','ratio':'2/5'},
     {'target':'工艺研究','ratio':'1/5'}]},
  ],
 }

def reciprocal_demo_rows():
 # 与互供关系服务部门对齐的自身费用，保证“全部”期间核算时所有底稿部门均已登记
 rows=[]
 for period in ('2026-10','2026-11'):
  for department in ('后勤服务','车队服务'):
   for category in ('仪器维护','试验耗材','研究工时'):
    rows.append({'period':period,'department':department,'category':category,
                 'amount_cents':120000 if department=='后勤服务' else 86000})
 return rows

def demo_rows():
 rng=random.Random(42);rows=[]
 for i in range(240):
  rows.append({'period':'2026-'+('10' if i<120 else '11'),'department':rng.choice(['公共','公共','光学研究','材料研究','工艺研究']),'category':rng.choice(['仪器维护','试验耗材','研究工时']),'amount_cents':rng.randint(1000,500000)})
 return rows

def seed():
 Base.metadata.create_all(engine)
 with Session() as db:
  for role in ('admin','analyst','viewer'):
   if not db.query(User).filter_by(email=role+'@demo.local').first():db.add(User(email=role+'@demo.local',role=role,password=password_hash('Demo2026!')))
  rows=demo_rows()
  for name in sorted(set(r['period'] for r in rows)):
   if not db.query(Period).filter_by(name=name).first():db.add(Period(name=name,description='合成演示业务期间，seed=42'))
  for i,data in enumerate(rows):
   validate_source(data);key='demo-'+str(i+1)
   if not db.query(Source).filter_by(natural_key=key).first():db.add(Source(natural_key=key,data=data))
  reciprocal_rows=reciprocal_demo_rows()
  for i,data in enumerate(reciprocal_rows):
   validate_source(data);key='demo-reciprocal-'+str(i+1)
   if not db.query(Source).filter_by(natural_key=key).first():db.add(Source(natural_key=key,data=data))
  if not db.query(Policy).filter_by(version=CONFIG['policy']['version']).first():db.add(Policy(version=CONFIG['policy']['version'],data=CONFIG['policy']))
  reciprocal_rule=demo_reciprocal_rule()
  if not db.query(ReciprocalRule).filter_by(version=reciprocal_rule['version']).first():
   db.add(ReciprocalRule(version=reciprocal_rule['version'],data=reciprocal_rule,created=__import__('time').time()))
  db.commit();print(json.dumps({'users':db.query(User).count(),'sources':db.query(Source).count(),'policies':db.query(Policy).count(),'reciprocal_rules':db.query(ReciprocalRule).count(),'periods':db.query(Period).count()},ensure_ascii=False))
if __name__=='__main__':seed()
