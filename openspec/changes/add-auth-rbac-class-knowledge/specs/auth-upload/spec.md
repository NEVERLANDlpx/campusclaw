## Purpose

让教师维护本班教学材料，学生读取本班内容，登录身份及班级边界均由后端确定。

## ADDED Requirements

### Requirement: Account authentication

系统 MUST 校验教师和学生的账号密码，建立可校验的会话，并阻止未认证的数据访问。

#### Scenario: Valid demo accounts
- **WHEN** teacher_a、student_a1 或 student_b1 提交正确口令
- **THEN** 登录成功，会话包含 user_id、role、class_id
- **AND** /api/me 返回对应身份，不包含密码哈希

#### Scenario: Wrong password
- **WHEN** 用户提交错误口令
- **THEN** 返回401和统一错误信息，不建立已认证会话

#### Scenario: Anonymous requests
- **WHEN** 未登录请求 /materials 或 /api/materials
- **THEN** 页面302至/login，API为401，均不含材料信息

#### Scenario: Logout and tampering
- **WHEN** Cookie签名损坏、已过期或已退出后重放
- **THEN** 受保护API返回401

### Requirement: Role authorization

系统 MUST 在后端执行权限检查，教师维护资料，学生只能读取。

#### Scenario: Student writes
- **WHEN** 学生上传或删除材料
- **THEN** 返回403，材料表、知识表和文件目录无变化

#### Scenario: Teacher writes
- **WHEN** 教师提交合法文件且CSRF有效
- **THEN** 上传返回201与新材料ID，本班列表出现该条记录

#### Scenario: Read only interface
- **WHEN** 学生登录
- **THEN** 可打开本班材料详情，页面没有上传或删除入口

### Requirement: Class isolation

系统 MUST 使用服务端可信班级过滤所有材料与知识正文读写，不采用客户端class_id授权。

#### Scenario: Cross-class resource
- **WHEN** A班账号访问或删除B班材料ID
- **THEN** 返回404，不含B班标题、正文或路径

#### Scenario: Manipulated list
- **WHEN** A班账号请求列表并传入class_id=2
- **THEN** 仍仅返回A班内容

#### Scenario: Manipulated upload
- **WHEN** 教师A上传同时传入class_id=2
- **THEN** 新材料和知识条目仍关联A班

### Requirement: Upload persistence

系统 MUST 解析UTF-8 txt/md并持久化文件、材料及知识正文，失败不得留下脏数据。

#### Scenario: Successful ingest
- **WHEN** 教师上传有效txt/md
- **THEN** 文件可找到，材料与知识条目关联同一材料ID及班级
- **AND** 同班学生刷新能读到正文，异班不可见
- **AND** materials.file_path MUST 保存为相对于上传根目录的路径，不得保存 Windows 或 Linux 绝对路径

#### Scenario: Invalid file
- **WHEN** 文件为空、类型不支持、UTF-8解码失败或含二进制控制字符
- **THEN** 返回400，文件与两张业务表无新增

#### Scenario: Oversize file
- **WHEN** 文件超过2MiB或请求体超过3MiB
- **THEN** 返回413且无新增数据

#### Scenario: Database failure
- **WHEN** 文件落盘后数据库写入失败
- **THEN** 事务回滚并删除新文件，返回明确错误

### Requirement: Seed data

系统 MUST 建立六类核心实体和材料、知识条目，并提供双班演示数据。

#### Scenario: Initial and repeated setup
- **WHEN** 初始化执行一次或重复执行
- **THEN** 班级A/B和教师A、学生A1/B1均存在，且不会重复种子或清除上传
- **AND** 两班材料标题可区分，讲义、作业、助手、技能表存在

### Requirement: Password and session security

系统 MUST 使用bcrypt保存密码，SECRET_KEY仅从环境读取，并校验写操作的CSRF。

#### Scenario: Hash verification
- **WHEN** 检查users.password_hash
- **THEN** 字段为bcrypt格式而非明文，正确密码可验证，错误密码不能验证

#### Scenario: Missing secret
- **WHEN** SECRET_KEY不存在或短于32字符
- **THEN** 应用启动失败，不回退到默认值

#### Scenario: Missing CSRF
- **WHEN** 教师提交无CSRF令牌的写操作
- **THEN** 返回403，不改变业务数据

### Requirement: Deployment and health

系统 MUST 提供Compose配置、持久化目录与无需登录的健康检查。

#### Scenario: Compose startup
- **WHEN** 配置.env并执行docker compose up --build
- **THEN** 可访问8080端口登录页，健康检查通过

#### Scenario: Health status
- **WHEN** 未登录请求/health
- **THEN** 数据库可读时200且status为ok，数据库故障时503

#### Scenario: Container rebuild
- **WHEN** 上传后docker compose down再up且保留挂载数据
- **THEN** 账号与上传材料仍存在
