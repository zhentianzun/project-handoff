# Project Handoff · 项目交接

[![Tests](https://github.com/zhentianzun/project-handoff/actions/workflows/test.yml/badge.svg)](https://github.com/zhentianzun/project-handoff/actions/workflows/test.yml)

**换 agent、换模型、换会话后，从已保存的项目状态继续工作。**

[English](README.md) · [技能说明](SKILL.md) · [详细工作规范](references/workflow.md)

把最后成功动作、下一步、用户决策、文件归属和验证证据存进项目。下一位 agent 开工前主动读取，并检查记录与工作区是否一致。

```text
agent A → 保存检查点、证据和文件归属
                     ↓
agent B → 读状态 → 查差异 → 确认未闭环操作 → 继续
```

## 能解决什么

- 建立 AGENTS 入口、单一状态源及自动生成的看板与待办。
- 记录阶段检查点，保留未完成状态和未提交代码差异。
- 拒绝旧状态覆盖新状态，发现锁和半写入草稿，保留人工规则。
- 登记外部操作；结果仍为 running/unknown 时检查失败，先确认再续做。
- 导出白名单文档与源码指纹，便于移交。
- 支持 Git／非 Git 项目；运行时只需 Python 3.10+ 标准库。

## 安装与使用

将整个仓库下载到个人 Codex 技能目录，文件夹命名为 `project-handoff`；也可把本仓库链接交给技能安装器。已有定制版本先核对，避免直接覆盖。

在新项目里输入：

```text
$project-handoff 为当前项目建立自动接手规范。
```

建立项目入口后，支持加载 AGENTS.md 的宿主会按入口要求主动接手，无需每次提醒。其他宿主需要配置自己的入口或使用接手包；已打开的会话恢复时主动重读。

## 不依赖 agent 的体验示例

在本仓库目录运行，使用**全新空白目录**：

```sh
mkdir demo-project
python scripts/init_project.py --root demo-project --name 演示项目
python scripts/init_project.py --root demo-project --name 演示项目 --apply
cd demo-project
python tools/handoff.py checkpoint --owner agent-A --summary "交接骨架已建立；下一步填写项目事实。"
python tools/handoff.py check
python tools/handoff.py export --output .handoff-export
```

不加 `--apply` 只预览。已有交接文件或同名工具时拒绝覆盖，转为维护已有机制。真实项目用 `--source src` 等参数指定代码范围；默认指纹只覆盖交接工具。骨架生成后仍需填写真实目标、环境、命令、决策、待办和验证证据。

## 中途切换 agent

修改前登记任务、执行体和文件范围；每个关键阶段立即保存检查点。外部操作在 `operations` 数组登记 operation_id、owner、target、status、reconcile。

接手者确认上一执行体已停止或协调，核对检查点、未提交改动和外部实际结果。不要为了让检查通过直接 `record-local`：它只记录指纹，不会证明测试或发布成功。

状态修改用工具的 load/validate/save API 保存，再 render/check。保存具备锁、原子替换和读取版本核对；源码仍须协调归属。突然中断前没有保存的信息无法恢复，也不能保证所有模型永不出错。

## 验证

```sh
python -X utf8 scripts/test_portability.py
```

当前 26 项隔离测试覆盖项目根与路径别名、人工规则、检查点、旧状态写入、中断、源码变化、未知外部结果和导出范围。Git 相关测试需要安装 Git。Windows／Linux、Python 3.10／3.13 的 GitHub Actions 结果见顶部测试徽章。

这是工具层验证，不等于所有模型端到端测试。导出前还需人工核对文档和状态是否含敏感内容，排除常见秘密文件不能保证任意输入都安全。

## 反馈

欢迎提供最小复现、期望行为及验证范围。不要上传凭据、学生数据、生产数据库或原始私人对话。采用 [MIT 许可](LICENSE)，允许修改、分发和商用，并要求保留许可声明。

```sh
git clone https://github.com/zhentianzun/project-handoff.git ~/.codex/skills/project-handoff
```
