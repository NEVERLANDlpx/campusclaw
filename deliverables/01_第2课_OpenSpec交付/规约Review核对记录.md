# 规约 Review 核对记录

依据：线上 PPT 第 4.6-4.9 节、本地 `CampusClaw_第二课Ex1-Ex4.pdf` p20-p24。

## proposal / design

- README 三行说明存在：`README.md`。
- proposal 含登录、角色权限、班级隔离、上传入库、预置数据、安全运行与 Non-goals：`openspec/changes/add-auth-rbac-class-knowledge/proposal.md`。
- design 写明 Flask signed cookie、bcrypt、SECRET_KEY 环境注入、服务端班级过滤、上传事务、Compose/health 与风险：`openspec/changes/add-auth-rbac-class-knowledge/design.md`。

## spec / Scenario

至少三条硬性要求：

- 登录与会话：`specs/auth-upload/spec.md` 的 `Requirement: Account authentication`。
- 班级隔离：`Requirement: Class isolation`，跨班资源返回 404，不泄漏标题、正文或路径。
- 上传与知识库：`Requirement: Upload persistence`，合法 txt/md 必须文件、材料、知识条目一致；失败无脏数据。

A 班学生不能读取 B 班资料。依据 `Class isolation / Scenario: Cross-class resource`：A 班账号访问 B 班材料 ID 时返回 404 且不含 B 班标题、正文或路径。

教师上传后，`Upload persistence / Scenario: Successful ingest` 要求文件可找到，材料与知识条目关联同一材料 ID 与班级，同班学生刷新能读到正文，异班不可见。

## tasks

PPT 第 2 课 Review 要求 tasks 全部 `[ ]`。交付副本 `deliverables/01_第2课_OpenSpec交付/openspec/changes/add-auth-rbac-class-knowledge/tasks.md` 已全未勾选；主仓 `openspec/.../tasks.md` 保留当前实现状态，不用于冒充第 2 课快照。

