"""建立通用交接骨架；默认预览，--apply落地，不覆盖已有交接记录。"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil

SKILL = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('handoff_template', SKILL / 'assets/handoff.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def initialize(root, name, sources=None, apply=False):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('项目根必须是已存在目录')
    entry = 'AGENTS.override.md' if (root / 'AGENTS.override.md').is_file() else 'AGENTS.md'
    paths = [runtime.STATE, runtime.BOARD, runtime.TODO, 'docs/决策记录.md',
             'docs/接手指南.md', 'docs/交接工作规范.md', 'tools/handoff.py']
    for relative in paths:
        target = runtime.file_inside(root, relative)
        if target.exists():
            raise ValueError(f'已有交接/同名文件，保留原件，改走维护或迁移：{relative}')
    for relative in ('docs/交接状态.json.tmp', 'docs/.handoff.lock'):
        if runtime.file_inside(root, relative).exists():
            raise ValueError('有中断草稿/在途锁，先恢复核查')
    source_paths = list(dict.fromkeys((sources or []) + ['tools/handoff.py']))
    for relative in source_paths:
        target = runtime.file_inside(root, relative)
        if relative in ('.', './'):
            raise ValueError('不能将项目根作为源码扫描路径')
        if relative != 'tools/handoff.py' and not target.exists():
            raise ValueError(f'源码路径不存在：{relative}')
    entry_path = runtime.file_inside(root, entry)
    original = entry_path.read_text(encoding='utf-8') if entry_path.exists() else '# 项目工作规则\n'
    if runtime.AUTO_START in original or runtime.AUTO_END in original:
        raise ValueError('入口已有自动交接摘要，先核对旧机制，不重复初始化')
    rule = '''
## 自动接手工作约定

新会话、换模型/agent或恢复后主动读取本项目docs/交接看板.md、当前任务与决策，运行python tools/handoff.py check，不等待用户提醒。入口下方是生成摘要，完整状态以docs/交接状态.json为准；用户新指令决定当前工作。

修改前登记任务/归属/文件范围，每个关键阶段立即落盘。换agent前记录最后成功动作与下一步；新agent核查工作区与未闭环外部操作，不重复执行结果不明的操作，不覆盖未知改动。旧执行体仍写共享文件时先协调或停止。

功能与环境约束见项目指南。产出后更新权威状态/必要决策及证据，代码核查后record-local、render、check，按项目规则精确提交。check不证明业务正确，record-local不跑测试。只读无新状态不机械写。

自动读取依赖宿主加载AGENTS.md并能访问项目；旧会话恢复主动重读。渲染仅维护标记内生成摘要，保留人工规则。不自动启用子agent、定时任务或生产操作。
'''
    now = datetime.now(timezone.utc).isoformat()
    state = {
        'schema_version': 1, 'project': {'name': name, 'source_paths': source_paths, 'entry_files': [entry]},
        'updated_at': now, 'updated_by': 'project-handoff initializer',
        'summary': '交接骨架已建立；项目事实、环境、决策和实际验证范围尚待核对填写。',
        'local': {'commit': runtime.revision(root), 'checked_at': now,
                  'hash_mode': 'sha256_text_lf_binary_raw', 'source_hashes': {},
                  'worktree': '未判定其他改动归属；骨架生成不是项目审查。'},
        'production': {'evidence_kind': 'not_run', 'summary': '发布/交付情况待核验，没有线上则写不适用。',
                       'evidence_ref': 'docs/接手指南.md', 'limitations': '未验证产品或交付环境。'},
        'inflight': [], 'operations': [], 'tasks': [{'id': 'SETUP', 'title': '补全项目真实交接信息', 'priority': 'P1',
            'status': 'todo', 'owner': '当前接手者', 'context': '目前只有通用骨架，不能代替项目事实。',
            'evidence': {'kind': 'not_run', 'summary': '待定向核验', 'refs': ['docs/接手指南.md']},
            'next_action': '核对目标、环境、代码基准、用户决定和未完任务，补齐证据与归属。',
            'acceptance': ['未知明确标记，当前任务有下一动作与验收。', '真实命令/验证结果/限制有来源，入口与状态同步。'],
            'files': ['docs/交接状态.json', 'docs/接手指南.md', 'docs/决策记录.md']}],
        'next_task_ids': ['SETUP'], 'validation': ['只建立骨架，未执行产品测试。'], 'pitfalls': [],
        'references': ['docs/交接工作规范.md', 'docs/接手指南.md', 'docs/决策记录.md'],
        'checkpoint': {'at': now, 'owner': 'project-handoff initializer', 'summary': '骨架初始化；下一步填写项目事实。'},
    }
    plan = {'root': str(root), 'name': name, 'entry': entry, 'create': paths, 'source_paths': source_paths}
    if not apply:
        return plan
    if len((original + rule).encode('utf-8')) > 24576:
        raise ValueError('已有入口较大，先定向适配，避免自动注入被截断')
    for relative in paths:
        runtime.file_inside(root, relative).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SKILL / 'assets/handoff.py', root / 'tools/handoff.py')
    shutil.copyfile(SKILL / 'references/workflow.md', root / 'docs/交接工作规范.md')
    (root / 'docs/决策记录.md').write_text('# 项目决策记录\n\n按稳定ID记录用户原话/来源、决定和适用范围；新决定注明替代关系。当前尚未填写真实项目决策。\n', encoding='utf-8')
    (root / 'docs/接手指南.md').write_text(
        f'# {name} · 接手指南\n\n本文件需接手者补全，不能把生成视为项目审查。\n\n'
        '## 项目与仓库边界\n\n待核验：目标、根目录、嵌套仓库、数据与资产位置。\n\n'
        '## 环境与命令\n\n待核验：启动、测试、构建/交付命令及实际依赖。\n\n'
        '## 模块导航与项目保护规则\n\n待核验：当前任务涉及的模块、业务数据/秘密/资产/兼容约束。\n\n'
        '## 发布/交付与恢复\n\n待核验；若不适用写明不适用，不能伪造线上结果。\n\n'
        '## 文档时效与未知点\n\n历史记录不自动代表现状；补全已知差异和未完成项。\n', encoding='utf-8')
    state['local']['source_hashes'] = runtime.source_hashes(root, state)
    payload = runtime.context_document(original + rule, runtime.auto_context(state))
    if len(payload.encode('utf-8')) > 32768:
        raise ValueError('生成入口超过32KiB，应缩短摘要后适配')
    entry_path.write_text(payload, encoding='utf-8')
    runtime.save(root, state)
    for path, text in runtime.generated(state).items():
        (root / path).write_text(text, encoding='utf-8')
    errors, _ = runtime.check(root, state)
    if errors:
        raise ValueError('\n'.join(errors))
    return {**plan, 'result': '骨架已建立并通过一致性检查；项目事实仍需填写'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--source', action='append')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(initialize(args.root, args.name, args.source, args.apply), ensure_ascii=False, indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, 'INIT_REFUSED: ' + str(exc) + '\n')
