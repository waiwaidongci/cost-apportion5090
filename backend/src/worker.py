import time,json,traceback
from pathlib import Path
import redis
from src.config.database import Base,engine,Session
from src.config.settings import REDIS_URL
from src.models import identity,source,run,reciprocal
from src.models.run import Run
from src.models.reciprocal import ReciprocalRun
from src.services.calculation import calculate
from src.services.reciprocal_service import run_calculation, RECIPROCAL_QUEUE
from src.services.delivery import tick
Base.metadata.create_all(engine)
r=redis.Redis.from_url(REDIS_URL)
while True:
 Path('/tmp/worker-heartbeat').write_text(str(time.time()))
 try:
  item=r.lpop('report-jobs')
  if item:
   with Session() as db:
    job=db.get(Run,int(item))
    if job and job.status=='queued':
     job.status='running';db.commit()
     try: job.result=calculate(job.snapshot['sources'],job.snapshot['policy']);job.status='completed'
     except Exception as exc: job.status='failed';job.error=str(exc);traceback.print_exc()
     db.commit()
  reciprocal_item=r.lpop(RECIPROCAL_QUEUE)
  if reciprocal_item:
   with Session() as db:
    job=db.get(ReciprocalRun,int(reciprocal_item))
    if job and job.status=='queued':
     run_calculation(db,job.id)
  with Session() as db: tick(db)
 except Exception: traceback.print_exc()
 time.sleep(1)
