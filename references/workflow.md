# 通用项目交接工作规范

## 单一来源

规则在有效AGENTS入口/工作规范；状态、基准、归属、待办在docs/交接状态.json；看板和待办同源生成；用户决策独立；环境/命令/模块/项目红线在接手指南；发布、交付、验证在docs/发布记录/。原始临时输出可能易失，不能独自承担追溯。

可以沿用已有名称，不另建互相独立的当前状态。迁移保留旧索引，历史结果不能冒充新实测。

## 检查点与中途接手

修改前登记任务ID、owner、文件范围。检查点记录最后成功动作、下一动作、checkpoint_at、证据引用；外部操作另记operation_id、target、status（planned/running/succeeded/failed/unknown）及恢复/确认办法。

通用骨架外部操作存入operations数组，每项含operation_id、owner、target、status、reconcile；running/unknown使check拒绝继续，先按reconcile确认实际结果。operations可为空，不自动执行操作。

工具内部load/save提供状态原子替换、独占写入锁及读取版本比对；编辑状态时使用该API保存（先load、修改、validate、save），不要用整文件覆盖绕过检查。每次save需重新render/check。人工规则和源码并非OS锁保护，仍须按归属协调；检查失败先核查，不抹掉证据。

阶段完成立即落盘，中断前尽量记录；突发中断后对照检查点、差异和外部实际状态恢复。源码漂移先核查，结果不明先确认，不盲目重试。共享文件同时只一执行体写；登记不是OS锁。接手前确认旧agent已停止或协调，不凭PID/旧sessionID/时间戳推断当前状态。

## 完成与证据

current_probe：本次实测，写时间、命令、判据、结果、限制。historical_record：有来源历史。reported_observation：未复验观察。not_run：未验证。

任务状态todo/in_progress/blocked/needs_reverification/done/deferred。每项含ID、标题、优先级、归属、背景/卡点、证据、下一动作、验收、文件。done需实测或长期证据，blocked说明外部阻碍。

本地与交付/线上基准分开。发布记录目标、来源提交/当时快照和指纹、备份、迁移、操作结果、验证、缺口与恢复边界。不能事后冒认临时目录是原上传包。工具PASS、文件一致、服务可访问、业务验收分开。

## 通用工具字段

project.name/source_paths/entry_files描述项目。source_paths为项目内相对文件/目录，不含..、绝对路径、通配符或秘密/业务库；覆盖范围需明确。entry_files仅根AGENTS.md/AGENTS.override.md，不自动写父项目。

local记录commit（独立Git根才取HEAD，非Gitunversioned，无提交unborn）、checked_at、hash_mode、source_hashes、worktree。文本换行规范化，其他资产按字节hash；只覆盖配置路径，跳过秘密/数据库/日志/输出/符号链接。

production用于交付/线上，没线上写不适用，不伪造服务结论。其余schema1字段：updated_at、updated_by、summary、inflight、tasks、next_task_ids、validation、pitfalls、references、checkpoint。check验证结构/引用/生成物/所选源码，不证明业务。

指南必须填写真实目标、仓库边界、环境/运行/测试命令、模块导航、交付/恢复、数据/资产保护和未知项。不能照搬某项目SSH、课程、玩法或偏好。

## 默认读取与收尾

宿主加载AGENTS→接手者主动读最新状态及任务证据/决策→检查→按用户请求继续。入口仅精简摘要，详情按引用读。收尾更新记录、代码核查后record-local→render→check，精确提交并解释剩余改动。只读无新状态不机械写。

官方机制：[AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[技能](https://learn.chatgpt.com/docs/build-skills)。不支持项目文件的外部宿主需要自己的入口/接手包；不宣称所有模型端到端验证过。
