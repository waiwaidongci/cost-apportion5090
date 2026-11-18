# 砺禾项目成本归集簿

内部研究项目工时与费用→精确分摊和透视→站内月结交付；金额用整数分，定时worker站内交付

## 业务场景与工作流
模拟客户：砺禾研究协作组，12位业务与分析人员。每月研究明细先从`cost-apportion-202611.csv`录入底稿，经口径冻结、Python核算、负责人复核后向业务阅读者交付站内CSV。原有流程依靠人工表格抄算，痛点为口径版本难追溯、重复计算易错、复核与交付脱节。

模块：业务总览、业务底稿、新建口径版本、互供核算、异步核算与复核、定时交付、站内收件箱、审计。底稿可新增/修改/删除；口径仅新增版本；报告提交时冻结来源与版本并保存SHA256。定时交付引用已复核报告快照，worker到期写入数据库，业务阅读者下载。

## 算法口径
按工时权重分摊公共成本、整数分最大余数守恒与差异透视。1分三权重守恒与稳定tie；零权重拒绝；透视总数等于源数。

整数分守恒 · 公共成本逐笔可追溯。输入：业务底稿与口径JSON；输出：summary、透视rows、method、warnings。算法实现在`backend/src/services/calculation.py`，输入校验在`validation.py`。固定seed=42，240条合成数据；未对接真实业务系统。修改源数据和新建因子/口径不会改变已提交报告。

## 互供核算（代数分配法，保留原分摊方式）

服务部门之间存在循环转入时，一次分摊会漏算。新增独立互供模块（`backend/src/services/reciprocal/`），与原工时权重分摊并存、互不影响：

- **关系登记**：登记服务部门→服务/受益部门的有理数比例（接受 `1/3`、`0.25`、`1e-6` 等，全程 `Fraction` 不丢精度），每个服务部门一行、行合计必须恰为1；服务部门≤100、受益部门≤20。
- **精确求解**：按“服务部门总成本 = 自身费用 + 转入费用”建立方程 `(I-Aᵀ)x=b`，主解为 Fraction 前向消元（最小度数主元、稀疏字典存储）+回代；仅受益部门按期间×类别取整，最大余数法的余分按部门名升序稳定分配，整数分总额守恒。
- **封闭循环拒绝**：无外流的服务部门集合（汇点强连通分量）即使费用全为零也拒绝，错误信息点名无外流部门与封闭环分组。
- **近封闭环交叉校验**：外流比例可低至百万分之一；近封闭环强制用相互独立的第二套精确求解路径对照（小规模再叠加 Gauss-Jordan 与 Bareiss 整数消元），不一致即拒绝出表。
- **30秒时限**：主解55%、交叉校验35%、收尾10%的时限预算，超时明确拒绝并提示复核；100服务/20受益/百万分之一外流的稠密场景在时限内完成。
- **并发与复核**：排队事务用 `pg_advisory_xact_lock` 与底稿/关系写入互斥，冻结同一时点的底稿与互供关系（SHA256 快照），任务完成（completed）前不可复核；失败/排队/运行中均拒绝复核。
- 页面“互供核算”可配置比例、查看分数份额与取整结果；后端测试见 `backend/tests/`（`python3 -m unittest discover -s tests`，纯标准库/SQLite，无需外部服务）。


## 一天的验收剧本
1. 09:00 admin查看240条seed底稿与具名业务期间。
2. 09:10 analyst添加`cost-apportion-202611.csv`的一条具名业务记录。
3. 09:20 admin在口径版本页登记新版本；旧版本保留。
4. 09:30 analyst命名“十一月核算”并选择期间/版本排队。
5. 09:31 Redis worker真实执行Python计算，展示汇总/透视与口径边界。
6. 09:40 admin核对数值后填写至少4字复核说明。
7. 09:45 admin建立60秒周期计划，worker到期生成站内持久化交付。
8. 09:46 viewer在站内收件箱下载交付CSV；审计页查看操作者与时间。

## 快速启动
```sh
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```
前端 http://localhost:18250 ，后端 http://localhost:19250/docs ，数据库宿主端口17750。中文父目录可用。恰好5服务frontend/backend/worker/db/redis；均有真实healthcheck。停止并清空演示数据：`docker compose down -v --remove-orphans`。

|角色|邮箱|密码|权限|
|---|---|---|---|
|admin|admin@demo.local|Demo2026!|全部底稿、口径版本、核算、复核、调度|
|analyst|analyst@demo.local|Demo2026!|底稿增改删、核算、导出；无复核/调度/口径写权限|
|viewer|viewer@demo.local|Demo2026!|只读；仅可下载已复核报告与站内交付|

## 工程结构与开发
Python3.11/FastAPI/SQLAlchemy/Redis，PostgreSQL16；前端原生HTML/CSS/JS ES modules，Nginx代理`/api/`剥前缀至后端。`frontend/src`按api/stores/pages/components/hooks/utils/router/constants/types拆分；`backend/src`按models/schemas/services/controllers/routes/middlewares/config/utils/constants拆分；`backend/scripts/seed_demo.py`自然键幂等且不覆盖用户修改。SQLAlchemy启动创建初始结构，迁移说明在backend/migrations。

后端开发：在backend安装requirements，设置DATABASE_URL/REDIS_URL/JWT_SECRET，`uvicorn src.main:app --reload`；前端可用Nginx或带同等代理的静态开发服务器。前后端全部业务计算在Python。

环境变量：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、JWT_SECRET（部署替换）、DATABASE_URL、REDIS_URL、SEED_DEMO。`.env`不入Git。数据库/Redis/共享产物为命名卷。共享角色枚举admin/analyst/viewer与状态queued/running/completed/failed分别定义于backend/src/constants/enums.py和frontend/src/constants/enums.js。两个中间件：统一可恢复校验错误、每IP每分钟360请求限流。

## 已知边界
定时分发为站内收件箱；一名worker轮询执行，无外部邮件。调度发送已复核固定报告快照，不自动重算新数据。时间显示Asia/Shanghai。报告导出适合小型数据；底稿全量加载240行演示数据。Google Fonts不可用时回退serif。后端API以专属字段对象收发，页面通过业务输入控件编辑，不要求用户写JSON。新增来源期间自动可选；专属字段和算法严格校验。JWT演示有效期2小时。

MIT License。

## 实际实体映射
来源记录（Source，专属业务字段校验）、口径版本（Policy）、核算报告（Run）、交付计划（Schedule）、交付（Delivery）均经数据库→模型→请求schema→service→route/controller→frontend API→store→page。Period为已有来源期间字典，在任务期间选择器使用；不单独作为复杂度计数。底稿JSON为小型多字段单记录存储，不虚构未落库的子实体。
