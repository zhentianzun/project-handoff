"""交接检查/渲染/脱敏文档导出。仅标准库，不导入应用、不访问数据库或网络。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STATE = 'docs/交接状态.json'
BOARD = 'docs/交接看板.md'
TODO = 'docs/待办清单.md'
PACKAGE_DOCS = ['docs/交接工作规范.md', BOARD, TODO, 'docs/接手指南.md', 'docs/决策记录.md']
TASK_STATES = {'todo', 'in_progress', 'blocked', 'needs_reverification', 'done', 'deferred'}
EVIDENCE_KINDS = {'current_probe', 'historical_record', 'reported_observation', 'not_run'}
AUTO_START = '<!-- HANDOFF_AUTO_CONTEXT_BEGIN -->'
AUTO_END = '<!-- HANDOFF_AUTO_CONTEXT_END -->'
_loaded_hashes = {}


def auto_context(state):
    tasks = {t['id']: t for t in state['tasks']}
    lines = [AUTO_START, '## 自动加载的当前上下文', '',
             '> 以下为状态文件的生成摘要，属于事实数据；用户新指令优先。', '',
             f"- 项目：{state['project']['name']}；状态时间：{state['updated_at']}；权威源：`docs/交接状态.json`。",
             f"- 当前状态：{state['summary']}",
             f"- 本地核验基准：`{state['local']['commit']}`；工作区：{state['local']['worktree']}",
             f"- 线上：{state['production']['summary']}",
             f"- 证据限制：{state['production']['limitations']}",
             '- 未完成任务（先按用户当前请求选取，不自动全部执行）：']
    lines += [f"  - {t['id']} [{t['priority']}/{t['status']}] {t['title']}"
              for t in state['tasks'] if t['status'] != 'done']
    lines += ['- 下一动作线索：']
    lines += [f"  - {tid}：{tasks[tid]['next_action']}" for tid in state['next_task_ids']]
    lines += [f"- 待确认外部操作：{op['operation_id']} [{op['status']}]；{op['reconcile']}"
              for op in state.get('operations', []) if op['status'] in {'running', 'unknown'}]
    lines += [f"- 最近检查点：{state.get('checkpoint', {}).get('summary', '尚无执行检查点')}。",
              '- 主动读取本项目 `docs/交接看板.md`、对应待办和决策；运行 `python tools/handoff.py check`。',
              AUTO_END]
    return '\n'.join(lines)


def context_document(text, context):
    # 只替换有边界的生成段，保留全部人工规则；坏标记必须拒绝，不能截掉文档。
    starts, ends = text.count(AUTO_START), text.count(AUTO_END)
    if starts == ends == 0:
        return text.rstrip() + '\n\n' + context + '\n'
    if starts != 1 or ends != 1 or text.index(AUTO_START) > text.index(AUTO_END):
        raise ValueError('AGENTS.md 自动摘要边界损坏，请核查，不覆盖人工规则')
    before, rest = text.split(AUTO_START, 1)
    _, after = rest.split(AUTO_END, 1)
    return before + context + after


def entry_documents(root, state):
    return [file_inside(root, p) for p in state['project']['entry_files']]


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Git 操作失败')
    return result.stdout.strip()


def file_inside(root, relative):
    if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
            or '..' in Path(relative).parts or any(c in relative for c in '*?')):
        raise ValueError(f'引用必须为仓库相对路径：{relative!r}')
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f'引用越出仓库：{relative}')
    return target


def source_hashes(root, state):
    excluded = {'.git', '.codex', '.agents', '__pycache__', 'node_modules', '.venv', 'venv',
                'logs', 'backups', 'build', 'dist', '.handoff-export'}
    secret_names = {'.env', 'auth.json', 'credentials.json', '.secrets.json', '.fernet_key'}
    text_ext = {'.py', '.js', '.ts', '.css', '.html', '.json', '.txt', '.ini', '.gd', '.cs', '.cpp', '.h', '.toml', '.yaml', '.yml', '.md', '.tscn'}
    result = {}
    for relative in state['project']['source_paths']:
        if relative in ('.', './'):
            raise ValueError('请配置具体源文件/目录，不能扫描整个项目根')
        target = file_inside(root, relative)
        if not target.exists():
            raise ValueError(f'配置的源码路径缺失：{relative}')
        names = [target] if target.is_file() else target.rglob('*')
        for path in names:
            name = path.relative_to(root).as_posix()
            parts = path.relative_to(root).parts
            if (not path.is_file() or path.is_symlink() or any(p in excluded for p in parts)
                    or any((root.joinpath(*parts[:i])).is_symlink() for i in range(1, len(parts)))
                    or path.name in secret_names or path.name.startswith('.env.')
                    or path.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.pem', '.key', '.log'}
                    or path.name.endswith(('_key.txt', '.db-wal', '.db-shm'))):
                continue
            raw = file_inside(root, name).read_bytes()
            if path.suffix.lower() in text_ext:
                raw = raw.replace(b'\r\n', b'\n')
            result[name] = hashlib.sha256(raw).hexdigest()
    return dict(sorted(result.items()))


def revision(root):
    try:
        top = Path(git(root, 'rev-parse', '--show-toplevel')).resolve()
        if top != root.resolve():
            return 'unversioned'
        try:
            return git(root, 'rev-parse', 'HEAD')
        except RuntimeError:
            return 'unborn'
    except (RuntimeError, FileNotFoundError):
        return 'unversioned'


def save(root, state):
    # 同目录原子替换，避免写了一半的JSON；不执行外部操作。
    target = root / STATE
    temp = target.with_suffix('.json.tmp')
    lock = target.parent / '.handoff.lock'
    # 只释放本执行体刚创建的锁。旧锁/中断草稿保留，接手先核验，不覆盖。
    with lock.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps({'pid': os.getpid(), 'at': datetime.now(timezone.utc).isoformat()}))
    try:
        key = str(target.resolve())
        expected = _loaded_hashes.get(key)
        if expected is not None and target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError('状态已被其他执行体更新，先重读合并，不覆盖')
        with temp.open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(target)
        _loaded_hashes[key] = hashlib.sha256(target.read_bytes()).hexdigest()
    finally:
        lock.unlink()


def load(root):
    target = root / STATE
    raw = target.read_bytes()
    _loaded_hashes[str(target.resolve())] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8'))


def validate(state, root):
    errors = []
    def need(obj, fields, label):
        if not isinstance(obj, dict):
            errors.append(f'{label} 必须是对象')
            return False
        for field in fields:
            if field not in obj or obj[field] is None or obj[field] == '':
                errors.append(f'{label} 缺少 {field}')
        return True

    if not need(state, ['schema_version', 'updated_at', 'updated_by', 'summary', 'local',
                        'production', 'inflight', 'tasks', 'next_task_ids', 'validation',
                        'pitfalls', 'references'], 'state'):
        return errors
    if state.get('schema_version') != 1:
        errors.append('不支持的 schema_version')
    if not isinstance(state.get('local'), dict) or not isinstance(state.get('production'), dict):
        return errors + ['local/production必须是对象']
    project = state.get('project')
    if need(project, ['name', 'source_paths', 'entry_files'], 'project'):
        for field in ('source_paths', 'entry_files'):
            if not isinstance(project.get(field), list) or not project[field]:
                errors.append(f'project.{field}必须为非空数组')
        for path in project.get('entry_files', []):
            if path not in ('AGENTS.md', 'AGENTS.override.md'):
                errors.append('只支持本项目根AGENTS入口，不写父项目')
        for path in project.get('source_paths', []):
            try:
                file_inside(root, path)
            except ValueError as exc:
                errors.append(str(exc))
    try:
        stamp = datetime.fromisoformat(state.get('updated_at', ''))
        if stamp.tzinfo is None:
            errors.append('updated_at 必须含时区')
    except (ValueError, TypeError):
        errors.append('updated_at 必须为 ISO 时间')
    for field in ('inflight', 'tasks', 'next_task_ids', 'validation', 'pitfalls', 'references'):
        if not isinstance(state.get(field), list):
            errors.append(f'{field} 必须为数组')
    need(state.get('local'), ['commit', 'checked_at', 'hash_mode', 'source_hashes', 'worktree'], 'local')
    if state.get('local', {}).get('hash_mode') != 'sha256_text_lf_binary_raw':
        errors.append('hash_mode必须为sha256_text_lf_binary_raw')
    need(state.get('production'), ['evidence_kind', 'summary', 'evidence_ref', 'limitations'], 'production')
    hashes = state.get('local', {}).get('source_hashes')
    if not isinstance(hashes, dict) or not hashes:
        errors.append('local.source_hashes 不得为空')
    else:
        for path, digest in hashes.items():
            try:
                file_inside(root, path)
            except ValueError as exc:
                errors.append(str(exc))
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                errors.append(f'无效源码指纹：{path}')
    ids = set()
    for task in state.get('tasks', []) if isinstance(state.get('tasks'), list) else []:
        if not need(task, ['id', 'title', 'priority', 'status', 'owner', 'context', 'evidence',
                          'next_action', 'acceptance', 'files'], 'task'):
            continue
        tid = task.get('id')
        if not isinstance(tid, str) or tid in ids:
            errors.append(f'重复或无效任务 ID：{tid}')
        else:
            ids.add(tid)
        if task.get('status') not in TASK_STATES:
            errors.append(f'{tid} 无效状态')
        if task.get('priority') not in ('P0', 'P1', 'P2', 'P3'):
            errors.append(f'{tid} 无效优先级')
        if not isinstance(task.get('acceptance'), list) or not task.get('acceptance'):
            errors.append(f'{tid} 缺少可执行验收条件')
        evidence = task.get('evidence')
        if need(evidence, ['kind', 'summary', 'refs'], f'{tid}.evidence'):
            if evidence.get('kind') not in EVIDENCE_KINDS:
                errors.append(f'{tid} 无效证据类型')
            if task.get('status') == 'done' and evidence.get('kind') in ('not_run', 'reported_observation'):
                errors.append(f'{tid} done 必须有已核验或长期证据')
    for tid in state.get('next_task_ids', []) if isinstance(state.get('next_task_ids'), list) else []:
        if tid not in ids:
            errors.append(f'下一步引用不存在的任务：{tid}')
    for item in state.get('inflight', []) if isinstance(state.get('inflight'), list) else []:
        if need(item, ['owner', 'status', 'files', 'next_checkpoint'], 'inflight'):
            if item.get('status') not in {'active', 'done_uncommitted', 'ownership_unknown'}:
                errors.append('无效在途归属状态')
    operations = state.get('operations', [])
    if not isinstance(operations, list):
        errors.append('operations必须为数组')
    else:
        seen = set()
        for op in operations:
            if not need(op, ['operation_id', 'owner', 'target', 'status', 'reconcile'], 'operation'):
                continue
            oid = op.get('operation_id')
            if not isinstance(oid, str) or not oid or oid in seen:
                errors.append('外部操作ID必须非空且唯一')
            else:
                seen.add(oid)
            if op.get('status') not in {'planned', 'running', 'succeeded', 'failed', 'unknown'}:
                errors.append('无效外部操作状态')
    # refs 只能指向长期可访问的仓库证据，不对临时绝对路径作假成功检查。
    refs = list(state.get('references', [])) if isinstance(state.get('references'), list) else []
    prod = state.get('production', {})
    if isinstance(prod, dict) and prod.get('evidence_ref'):
        refs.append(prod['evidence_ref'])
    for task in state.get('tasks', []) if isinstance(state.get('tasks'), list) else []:
        if isinstance(task, dict) and isinstance(task.get('evidence'), dict):
            refs.extend(task['evidence'].get('refs', []))
    for relative in refs:
        try:
            if not file_inside(root, relative).is_file():
                errors.append(f'证据引用缺失：{relative}')
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def generated(state):
    tasks = {t['id']: t for t in state['tasks']}
    board = [f"# {state['project']['name']} · 交接看板", '', '> 自动生成自 `交接状态.json`；禁止单独手改。', '',
             '## ① 一句话现状', '', state['summary'], '', '## ② 基准', '',
             f"- 本地核验基准：`{state['local']['commit']}`；核验时间：{state['local']['checked_at']}。",
             f"- 源码指纹：状态文件内 {len(state['local']['source_hashes'])} 项；用 `check` 核对，文档提交可推进 HEAD。",
             f"- 工作区：{state['local']['worktree']}",
             f"- 发布/交付证据类型：`{state['production']['evidence_kind']}`。{state['production']['summary']}",
             f"- 线上证据：[{state['production']['evidence_ref']}](../{state['production']['evidence_ref']})",
             f"- 线上核验限制：{state['production']['limitations']}", '', '## ③ 在飞', '']
    board += [f"- {i['owner']}｜{i['status']}｜{', '.join(i['files'])}｜下一检查点：{i['next_checkpoint']}"
              for i in state['inflight']] or ['无已登记的执行任务；旧进程需重新核验。']
    board += [f"- 外部操作 {op['operation_id']}｜{op['status']}｜{op['target']}｜确认办法：{op['reconcile']}"
              for op in state.get('operations', [])]
    board += ['', '## ④ 未完成', '', '细节、卡点、下一动作和验收条件见 [待办清单](待办清单.md)。', '']
    board += [f"- **{t['id']}** [{t['priority']} / {t['status']}] {t['title']}；归属：{t['owner']}。"
              for t in state['tasks'] if t['status'] != 'done']
    board += ['', '## ⑤ 新踩的坑', ''] + ['- ' + p for p in state['pitfalls']]
    board += ['', '## ⑥ 下一步建议', '']
    board += [f"{n}. **{tid}**：{tasks[tid]['next_action']}" for n, tid in enumerate(state['next_task_ids'], 1)]
    board += ['', '最近验证：', ''] + ['- ' + v for v in state['validation']]
    board += ['', '最近执行检查点：', '', json.dumps(state.get('checkpoint', {}), ensure_ascii=False), '']
    board += ['', '## ⑦ 最后更新', '', f"{state['updated_at']}；{state['updated_by']}。", '']
    todo = ['# 待办清单', '', '> 自动生成自 `交接状态.json`；状态与优先级只在源文件修改。', '']
    for t in state['tasks']:
        todo += [f"## {t['id']} · {t['title']}", '',
                 f"- 优先级/状态：{t['priority']} / {t['status']}；归属：{t['owner']}。",
                 f"- 背景与卡点：{t['context']}",
                 f"- 证据 [{t['evidence']['kind']}]：{t['evidence']['summary']}",
                 f"- 下一动作：{t['next_action']}",
                 '- 定向文件：' + '、'.join(f'`{p}`' for p in t['files']),
                 '- 长期证据：' + '、'.join(f'[{p}](../{p})' for p in t['evidence']['refs']),
                 '', '验收条件：', ''] + ['- ' + a for a in t['acceptance']] + ['']
    return {BOARD: '\n'.join(board), TODO: '\n'.join(todo)}


def check(root, state):
    errors = validate(state, root)
    warnings = []
    if errors:
        return errors, warnings
    for op in state.get('operations', []):
        if op['status'] in {'running', 'unknown'}:
            errors.append(f"外部操作待确认：{op['operation_id']}；{op['reconcile']}；不能盲目重试")
    for pending in ['docs/.handoff.lock', 'docs/交接状态.json.tmp']:
        if (root / pending).exists():
            errors.append(f'存在在途锁或中断草稿：{pending}；核查执行体与内容，不直接删除')
    if state['production']['evidence_kind'] not in EVIDENCE_KINDS:
        errors.append('production 无效证据类型')
    for path, expected in generated(state).items():
        target = root / path
        if not target.exists() or target.read_text(encoding='utf-8') != expected:
            errors.append(f'{path} 与状态不同步；运行 render')
    for entry in entry_documents(root, state):
        if not entry.is_file():
            errors.append(f'自动加载入口缺失：{entry.name}')
            continue
        raw = entry.read_text(encoding='utf-8')
        try:
            if raw != context_document(raw, auto_context(state)):
                errors.append(f'自动摘要与状态不同步：{entry}；运行 render')
        except ValueError as exc:
            errors.append(str(exc))
    current = source_hashes(root, state)
    saved = state['local']['source_hashes']
    changed = sorted(p for p in set(current) | set(saved) if current.get(p) != saved.get(p))
    if changed:
        errors.append('本地源码基准已变化，先核查再 record-local：' + ', '.join(changed[:15]))
    if state['local']['commit'] not in ('unversioned', 'unborn'):
        try:
            if revision(root) in ('unversioned', 'unborn'):
                raise RuntimeError('Git根已变化')
            git(root, 'merge-base', '--is-ancestor', state['local']['commit'], 'HEAD')
        except RuntimeError:
            errors.append('核验提交不是当前项目HEAD的祖先；核查根/分支/基准')
    age = datetime.now(timezone.utc) - datetime.fromisoformat(state['updated_at'])
    if age.days > 7:
        warnings.append(f'状态已超过 {age.days} 天；先核查新提交、生产状态和资源')
    if state['production']['evidence_kind'] != 'current_probe':
        warnings.append('线上仅有历史/待核验信息，不能据此宣布当前发布正常')
    warnings.append('仅检查配置路径与交接一致性，不证明业务测试或交付成功')
    return errors, warnings


def render_plan(root, state):
    # 预先检查全部入口，防止坏标记/超长摘要导致半写入或检查点丢失。
    outputs = {root / path: content for path, content in generated(state).items()}
    for entry in entry_documents(root, state):
        content = context_document(entry.read_text(encoding='utf-8'), auto_context(state))
        if len(content.encode('utf-8')) > 32768:
            raise ValueError('入口超32KiB，请缩短摘要/细节后再生成')
        outputs[entry] = content
    return outputs


def write_render(outputs):
    for path, content in outputs.items():
        path.write_text(content, encoding='utf-8')


def export(root, state, output):
    output = output.resolve()
    if (not output.is_relative_to(root.resolve()) or output == root.resolve()
            or output.is_relative_to(root / 'docs') or output.is_relative_to(root / '.git')
            or any(output.is_relative_to(file_inside(root, p)) for p in state['project']['source_paths'])):
        raise ValueError('导出须在项目内独立目录，不能覆盖源码、docs或Git目录')
    output.mkdir(parents=True, exist_ok=True)
    docs = list(state['project']['entry_files']) + list(PACKAGE_DOCS)
    # 长期文档证据仅允许 docs 下 Markdown；不因 refs 指到日志就自动打包。
    docs += [p for p in state['references'] if p.startswith('docs/发布记录/') and p.endswith('.md')]
    docs = list(dict.fromkeys(docs))
    parts = [f"# {state['project']['name']} · 接手包", '',
             f"生成时间：{datetime.now(timezone.utc).isoformat()}；状态时间：{state['updated_at']}。",
             '只包含交接文档与状态指纹；不含源码/数据库/登录态/原始日志。此包是快照，仓库新状态优先。',
             '没有仓库访问权时，先取得相应源码与证据，不得凭摘要执行部署。', '']
    manifest = {}
    for relative in docs:
        raw = file_inside(root, relative).read_bytes()
        manifest[relative] = hashlib.sha256(raw).hexdigest()
        parts += [f'---\n\n来源：`{relative}`\n', raw.decode('utf-8'), '']
    parts += ['---\n\n来源：`docs/交接状态.json`\n', '```json',
              json.dumps(state, ensure_ascii=False, indent=2), '```', '']
    manifest[STATE] = hashlib.sha256((root / STATE).read_bytes()).hexdigest()
    bundle = output / '接手包.md'
    bundle.write_text('\n'.join(parts), encoding='utf-8')
    manifest['bundle_sha256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'render', 'record-local', 'export', 'checkpoint'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--owner')
    parser.add_argument('--summary')
    args = parser.parse_args()
    try:
        state = load(ROOT)
        errors = validate(state, ROOT)
        if errors:
            raise ValueError('\n'.join(errors))
        if args.command == 'record-local':
            state['local']['commit'] = revision(ROOT)
            state['local']['checked_at'] = datetime.now(timezone.utc).isoformat()
            state['local']['hash_mode'] = 'sha256_text_lf_binary_raw'
            state['local']['source_hashes'] = source_hashes(ROOT, state)
            save(ROOT, state)
            print('LOCAL_RECORDED：仅记录指纹，不代表测试或发布通过；请 render/check')
            return 0
        if args.command == 'render':
            write_render(render_plan(ROOT, state))
            print('HANDOFF_RENDERED')
            return 0
        if args.command == 'checkpoint':
            if not args.owner or not args.summary:
                raise ValueError('checkpoint需--owner和--summary，不自动推断任务完成')
            now = datetime.now(timezone.utc).isoformat()
            state['updated_at'], state['updated_by'] = now, args.owner
            state['checkpoint'] = {'at': now, 'owner': args.owner, 'summary': args.summary}
            outputs = render_plan(ROOT, state)
            save(ROOT, state)
            # 故意不记录新源码基准，源文件漂移仍会在下一次check拒绝。
            write_render(outputs)
            print('CHECKPOINT_SAVED：未更改源码基准/归属/完成状态，接手先检查')
            return 0
        errors, warnings = check(ROOT, state)
        for warning in warnings:
            print('WARN：' + warning)
        if errors:
            raise ValueError('\n'.join(errors))
        if args.command == 'export':
            if not args.output:
                raise ValueError('export 必须指定 --output')
            print(export(ROOT, state, args.output))
        else:
            print('HANDOFF_CHECK=PASS（结构、引用、生成物、本地源码指纹）')
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print('HANDOFF_CHECK=FAIL：' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
