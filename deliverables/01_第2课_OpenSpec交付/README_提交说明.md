# 第 2 课 OpenSpec 提交说明

本目录是第 2 课规约交付副本，只包含 `add-auth-rbac-class-knowledge` 四件套。主仓库已有后续实现与实测证据，但第 2 课 PPT 明确是 Propose + Review，不 Apply、不写业务页面、不运行真实 Compose，因此本目录内 `tasks.md` 保持全部 `[ ]`。

提交范围：

- `openspec/changes/add-auth-rbac-class-knowledge/proposal.md`
- `openspec/changes/add-auth-rbac-class-knowledge/design.md`
- `openspec/changes/add-auth-rbac-class-knowledge/specs/auth-upload/spec.md`
- `openspec/changes/add-auth-rbac-class-knowledge/tasks.md`

已执行结构校验：

```powershell
npx @fission-ai/openspec@1.13.1 validate add-auth-rbac-class-knowledge --strict
```

结果：`Change 'add-auth-rbac-class-knowledge' is valid`。

