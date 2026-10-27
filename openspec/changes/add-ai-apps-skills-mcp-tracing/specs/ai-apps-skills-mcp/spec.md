## Purpose

提供可按班级授权、可实际执行并可追踪验证的多 AI 应用、Prompt、Skill 与 MCP 工具编排。

## ADDED Requirements

### Requirement: Independent assistant applications

系统 MUST 为每个班级幂等提供四个内置应用，且每个应用 MUST 保存自己的 system prompt 和运行参数。

#### Scenario: Prompt isolation
- **WHEN** 教师修改一个本班应用的 Prompt
- **THEN** 下一次该应用请求 MUST 使用新 Prompt
- **AND** 其他应用 Prompt MUST 保持不变

#### Scenario: Server-side application scope
- **WHEN** 用户提交其他班级 app_id 或禁用应用
- **THEN** 系统 MUST 返回 404
- **AND** 不得根据客户端 class_id 改变授权范围

### Requirement: Safe prompt templates

系统 MUST 支持 Prompt 模板库及复制到应用，并 MUST 只替换白名单变量。

#### Scenario: Apply template
- **WHEN** 本班教师向当前应用应用模板
- **THEN** 模板内容 MUST 复制到应用 system_prompt_template
- **AND** 后续修改模板 MUST NOT 改变该应用

#### Scenario: Unknown variable
- **WHEN** 模板包含非白名单变量或表达式
- **THEN** 系统 MUST 拒绝保存或应用且不得执行表达式

#### Scenario: Template preview and explicit save
- **WHEN** 教师在当前应用选择一个 Prompt 模板
- **THEN** 前端 MUST 将模板内容复制到当前 Prompt 编辑区并明确提示尚未保存
- **AND** 教师可继续编辑副本，只有点击保存成功后才持久化到当前应用
- **AND** 选择“不应用模板” MUST 恢复当前应用最近一次已保存的 Prompt，不修改其他运行参数

#### Scenario: Recoverable asynchronous save
- **WHEN** 教师保存 Prompt 与参数成功或失败
- **THEN** 保存按钮 MUST 在请求期间禁用并在完成后恢复
- **AND** 前端 MUST 显示服务端返回的实际成功或错误结果，不得在异步等待后依赖失效的 DOM event currentTarget

### Requirement: Controlled Skill definitions and routing

系统 MUST 支持内置及 Markdown 上传 Skill、应用绑定和确定性单 Skill 路由，并不得执行上传内容。

触发关键词 MUST 按空白、逗号或分号拆分，并以不区分大小写的连续子串进行确定性匹配；系统 MUST NOT 把未配置的近义词或相近表达自动视为命中。候选审计 MUST 记录本轮实际检查的关键词及命中项，使未命中原因可复核。

#### Scenario: Matching enabled Skill
- **WHEN** 问题命中当前应用绑定且启用 Skill 的关键词
- **THEN** 最多 MUST 选择一个 Skill
- **AND** 完整 Skill 指令 MUST 进入实际 system message
- **AND** MUST 记录候选、选择理由与注入内容哈希

#### Scenario: Disabled or unbound Skill
- **WHEN** Skill 被禁用、未绑定或未命中
- **THEN** 其内容 MUST NOT 注入模型请求

#### Scenario: Similar wording without a configured keyword
- **WHEN** 问题只包含某个触发词的近义表达，但不包含已配置触发词的连续子串
- **THEN** 该 Skill MUST NOT 被选中或注入
- **AND** 路由审计 MUST 显示本轮检查的已配置触发词和空命中项

#### Scenario: Upload Markdown
- **WHEN** 本班教师上传合规 Markdown Skill
- **THEN** 系统 MUST 保存原始文本和解析元数据但不得执行其中代码
- **AND** 学生、跨班用户或超限/非 Markdown 内容 MUST 被拒绝

#### Scenario: Inspect and configure a Skill card
- **WHEN** 教师点击任一内置或上传 Skill 卡片
- **THEN** 页面 MUST 展示该 Skill 的说明、触发关键词、完整受控指令、启用状态及当前应用绑定状态
- **AND** 教师保存启用状态、内容或绑定后 MUST 持久化，刷新及再次打开时保持一致
- **AND** 被禁用或从应用解绑的 Skill MUST 立即停止参与路由和注入

### Requirement: Standard MCP discovery and authorization

系统 MUST 通过标准 MCP initialize、分页 tools/list 发现工具，并只使用运行期仍可用的本班授权工具。

教师管理界面 MUST 复用服务端连接、发现及断开接口，展示真实连接状态、失败原因、发现工具说明与参数 Schema，并在请求期间阻止重复操作。服务端只可连接部署配置明确允许的 MCP 主机，登记和每次连接时均 MUST 重新校验端点，不得把教师输入直接扩展为任意服务端网络访问能力。

#### Scenario: Atomic discovery
- **WHEN** MCP 握手和全部分页发现成功
- **THEN** 系统 MUST 在一个事务中替换旧清单并标记 connected
- **AND** 重复连接 MUST NOT 累积重复工具

#### Scenario: Discovery failure or disconnect
- **WHEN** 握手/发现失败或服务器断开
- **THEN** 失败连接 MUST NOT 覆盖旧清单或标记 connected
- **AND** 断开 MUST 清空有效清单，使绑定工具立即不可执行

#### Scenario: Tool binding validation
- **WHEN** 教师保存 `tool_name@server_name` 绑定
- **THEN** 系统 MUST 验证格式、本班服务器、connected 状态、发现清单及 JSON Schema

#### Scenario: Connect and inspect from teacher UI
- **WHEN** 教师点击某一本班服务器的“连接并发现工具”
- **THEN** 页面 MUST 调用真实连接接口并在进行期间禁用重复点击
- **AND** 成功后 MUST 显示 connected 及持久化的工具名称、说明和参数 Schema
- **AND** 失败后 MUST 显示服务端记录的可诊断错误，不得显示伪造成功或清除最近一次成功清单

#### Scenario: Bind a discovered tool from Skill detail
- **WHEN** 教师在 Skill 详情中选择当前 connected 服务器的已发现工具并保存
- **THEN** 页面 MUST 复用 Skill 工具绑定接口持久化 `tool_name@server_name`
- **AND** 未连接、未发现、跨班或 Schema 无效的工具 MUST 被服务端拒绝

#### Scenario: Disallowed MCP endpoint
- **WHEN** 教师登记或连接部署配置未允许的 MCP 主机
- **THEN** 服务端 MUST 拒绝请求且不得发起网络连接

### Requirement: Bounded MCP tool loop

系统 MUST 校验模型 tool_calls 后调用 MCP，并把结果作为 tool 消息追加，且 MUST 分别限制调用轮次和累计次数。

#### Scenario: Successful tool call
- **WHEN** 模型请求当前 Skill 获准且参数满足 Schema 的工具
- **THEN** 宿主 MUST 调用真实发现的工具并记录参数、状态、摘要和耗时
- **AND** 下一轮模型请求 MUST 包含对应 tool 消息

#### Scenario: Rejected or failed tool call
- **WHEN** 函数未知、未授权、服务器断开、参数无效、超时或工具报错
- **THEN** 系统 MUST 不把失败伪装成成功
- **AND** MUST 将可理解的错误工具结果回传模型并记录拒绝或错误

### Requirement: Traceable LLM calls

系统 MUST 在实际发送前记录真实请求，在响应后记录真实响应，并不得记录凭据。

#### Scenario: Tool-capable request trace
- **WHEN** 实际请求包含 tools 或 tool_choice
- **THEN** 日志 MUST 保存实际发送的这些字段及 messages、model 和可选参数
- **AND** 响应 MUST 保留 choices、assistant message 与 tool_calls

#### Scenario: Trace authorization
- **WHEN** 教师或学生查询会话追踪
- **THEN** 教师仅可查看本班记录，学生仅可查看本人的记录

### Requirement: Observable SSE execution

系统 MUST 输出 meta、delta、citations、done、error，并仅在真实工具调用时输出 tool_call。

#### Scenario: Tool event ordering
- **WHEN** 本次真实发生工具调用
- **THEN** tool_call 事件 MUST 先于最终回答的第一个 delta

