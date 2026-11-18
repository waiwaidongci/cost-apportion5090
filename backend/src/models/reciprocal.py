from sqlalchemy import Column, Integer, String, JSON, Float, Text
from src.config.database import Base


class ReciprocalRule(Base):
    """互供关系版本：登记服务部门→服务/受益部门的有理数比例，版本名不可覆盖。"""
    __tablename__ = 'reciprocal_rules'
    id = Column(Integer, primary_key=True)
    version = Column(String(120), unique=True)
    data = Column(JSON, nullable=False)
    created = Column(Float)


class ReciprocalRun(Base):
    """互供核算任务：排队时冻结同一时点的底稿与互供关系，完成后才可复核。"""
    __tablename__ = 'reciprocal_runs'
    id = Column(Integer, primary_key=True)
    name = Column(String(120))
    status = Column(String(20))
    period = Column(String(120))
    rule_id = Column(Integer)
    rule_version = Column(String(120))
    snapshot = Column(JSON)
    checksum = Column(String(64))
    result = Column(JSON)
    error = Column(Text)
    created = Column(Float)
    finished = Column(Float)
    approved = Column(Integer, default=0)
    review = Column(Text, default='')
