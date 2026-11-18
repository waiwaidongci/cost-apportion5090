# 初始结构

SQLAlchemy启动创建以下业务表：costperiods, costentrys, allocationrules, allocationruns, delivery_schedules, deliveries、users、audits，以及互供核算新增的 reciprocal_rules（互供关系版本）、reciprocal_runs（互供核算任务）。Source专属JSON字段由对应validation严格校验；Policy为不可覆盖的版本记录；Run保存source/policy冻结快照；Period仅用于已有期间选择器，不计入核心复杂度。已有数据库升级需先备份，后续字段演进应以独立迁移执行。

## 002 互供核算（reciprocal）

新增表：

- `reciprocal_rules`：互供关系版本，字段 id/version(唯一)/data(JSON，含 services、beneficiaries、rows，ratio 以分数或有限小数字符串保存)/created。版本名不可覆盖。
- `reciprocal_runs`：互供核算任务，字段 id/name/status/period/rule_id/rule_version/snapshot(JSON 冻结同一时点底稿与关系)/checksum/result/error/created/finished/approved/review。

升级方式：应用启动时 `Base.metadata.create_all` 自动创建新表，不影响既有表；PostgreSQL 上排队事务通过 `pg_advisory_xact_lock` 与底稿写入互斥，SQLite 自动回退为空操作。
