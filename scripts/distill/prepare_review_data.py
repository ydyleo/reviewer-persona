"""读取 enriched JSONL（优先）/ Excel，生成结构化 JSON 供蒸馏。

来源：legacy reviewer-distiller/prepare_review_data.py，重构为正式链路。
- 优先读 outputs/enriched/*.jsonl（English key）；Excel 输入时按 CN→EN 映射归一化。
- 输出锚定 outputs/structured/{reviewer_w3}_{start}_{end}_structured.json。
- 保留 PATTERN_RULES 模式聚类（S/P/B/A/C/D），这是蒸馏起点，不是最终权威分类。
- 防御性噪声过滤（is_noise_comment），确保后续结构化数据干净。

用法（由顶层 SKILL.md 用绝对路径调用）：
    python <SKILL_ROOT>/scripts/distill/prepare_review_data.py \
        --input <SKILL_ROOT>/outputs/enriched/z00000001_2024-07-01_2026-01-01_enriched.jsonl
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, NamedTuple

SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # code-review/scripts
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.paths import STRUCTURED_DIR, ensure_dirs  # noqa: E402
from common.artifacts import now_iso  # noqa: E402
from common.jsonl_io import read_jsonl, CN_TO_EN  # noqa: E402
from common.filters import is_noise_comment  # noqa: E402


class PatternRule(NamedTuple):
    label: str
    category: str
    code_keywords: List[str]
    comment_keywords: List[str]
    target_code_patterns: List[str]
    description: str


# 类别编码：S=规范、P=性能、B=业务逻辑、A=架构、C=并发、D=可读性
PATTERN_RULES: List[PatternRule] = [
    PatternRule("const/auto&缺失", "S",
     [r'\bauto\b'],
     ["const", "auto&", "const auto&", "引用", "拷贝", "copy", "const ref"],
     [r'\bauto\s+\w+\s*=', r'\bauto\s+\w+\s*\('],
     "使用 auto 但未加 const 或 &，可能导致不必要的拷贝"),
    PatternRule("裸指针/手动内存管理", "P",
     [r'\bnew\s', r'\bdelete\b', r'\bmalloc\b', r'\bfree\b', r'\w+\s*\*\s*\w+\s*='],
     ["裸指针", "智能指针", "unique_ptr", "shared_ptr", "new", "delete", "内存泄漏",
      "memory leak", "手动管理", "raw pointer"],
     [r'\bnew\s', r'\bdelete\b', r'\w+\s*\*\s*\w+\s*=\s*new\b'],
     "使用裸指针或手动 new/delete，应优先使用智能指针"),
    PatternRule("RAII/资源管理", "A",
     [r'\bclose\s*\(', r'\brelease\s*\(', r'\bfree\s*\(', r'~\w+\s*\(\s*\)'],
     ["RAII", "析构", "资源释放", "close", "release", "fd", "句柄", "resource", "destructor"],
     [r'\bclose\s*\(', r'\brelease\s*\(', r'~\w+\s*\(\s*\)\s*=\s*default'],
     "资源获取释放未遵循 RAII 模式"),
    PatternRule("异常处理不当", "B",
     [r'\bcatch\s*\(', r'\bthrow\b', r'\bnoexcept\b', r'\btry\s*\{'],
     ["异常", "exception", "catch", "throw", "noexcept", "异常安全", "exception safety", "捕获", "抛出"],
     [r'\bcatch\s*\(\.\.\.\)', r'\bthrow\s', r'\bcatch\s*\(\s*\w+\s+&\s*\)'],
     "异常捕获或抛出方式不当"),
    PatternRule("错误码/返回值未检查", "B",
     [r'\bret\b', r'\berr\b', r'\bstatus\b', r'\bresult\b', r'\berror\b'],
     ["错误码", "返回值", "错误处理", "err", "error", "ret", "返回", "检查", "判断", "未检查", "忽略"],
     [r'\b\w+\(', r'\bif\s*\(\s*ret'],
     "函数返回值或错误码未被检查"),
    PatternRule("命名不规范", "S",
     [r'\b[A-Z][a-z]+\s+\w*[A-Z]{2,}', r'\b[a-z]+\s+\w+_\w+\s*[=(]'],
     ["命名", "name", "Naming", "变量名", "函数名", "命名规范", "驼峰", "下划线", "匈牙利"],
     [r'\bint\s+t[A-Z]', r'\bvoid\s+\w+_\w+\s*\('],
     "变量或函数命名不符合团队规范"),
    PatternRule("作用域/生命周期", "S",
     [r'\bstatic\b', r'\bextern\b', r'\[&\s*\]', r'\[=\s*\]'],
     ["作用域", "scope", "生命周期", "lifetime", "static", "lambda", "捕获", "capture", "引用悬挂"],
     [r'\[\s*&\s*\]', r'\[\s*=\s*\]', r'\bstatic\s+\w'],
     "变量作用域过大或 lambda 捕获方式不当"),
    PatternRule("智能指针使用", "P",
     [r'\bunique_ptr\b', r'\bshared_ptr\b', r'\bweak_ptr\b', r'\bmake_unique\b', r'\bmake_shared\b'],
     ["unique_ptr", "shared_ptr", "weak_ptr", "智能指针", "make_unique", "make_shared", "所有权"],
     [r'\bunique_ptr\b', r'\bshared_ptr\b', r'\bweak_ptr\b'],
     "智能指针的选择或使用方式存在问题"),
    PatternRule("范围for/迭代器", "P",
     [r'\bfor\s*\(\s*auto', r'\bbegin\s*\(\s*\)', r'\bend\s*\(\s*\)', r'\biterator\b', r'\bconst_iterator\b'],
     ["范围for", "迭代器", "range", "for", "iterator", "begin", "end", "遍历", "循环"],
     [r'\bfor\s*\(\s*auto\b', r'\bfor\s*\(\s*\w+::iterator'],
     "循环遍历方式不够现代，应使用范围 for 或更优写法"),
    PatternRule("魔法数字/硬编码", "D",
     [r'\b\d{4,}\b', r'"[^"]*\b\d+\b[^"]*"'],
     ["魔法数字", "hardcode", "magic", "常量", "枚举", "define", "硬编码", "数字"],
     [r'=\s*\d{3,}', r'\bif\s*\(\s*\w+\s*==\s*\d+'],
     "使用了魔法数字或硬编码值，应定义为命名常量"),
    PatternRule("线程/并发安全", "C",
     [r'\bmutex\b', r'\block\b', r'\batomic\b', r'\bthread\b', r'\bstd::async\b',
      r'\bfuture\b', r'\bpromise\b', r'\bcondition_variable\b'],
     ["线程", "并发", "锁", "mutex", "lock", "thread", "atomic", "race", "data race", "竞争", "同步", "async"],
     [r'\bmutex\b', r'\block_guard', r'\bstd::thread\b'],
     "并发场景下锁使用或线程安全存在问题"),
    PatternRule("冗余拷贝", "P",
     [r'\bstd::move\b', r'\bstd::forward\b', r'\bcopy\b', r'\bclone\b', r'\bswap\b'],
     ["拷贝", "copy", "move", "移动语义", "RVO", "NRVO", "返回值优化", "pass by value", "传值", "开销"],
     [r'\bstd::move\b', r'\bconst\s+\w+\s+\w+\s*=\s*\w+'],
     "存在不必要的拷贝，应使用移动语义或引用传递"),
    PatternRule("接口设计", "A",
     [r'\bvirtual\b', r'\boverride\b', r'\bfinal\b', r'\babstract\b',
      r'\bpublic\b', r'\bprotected\b', r'\bprivate\b'],
     ["接口", "interface", "虚函数", "virtual", "override", "设计", "架构", "耦合", "依赖", "参数"],
     [r'\bvirtual\s+\w+\s+\w+\s*\(', r'\bclass\s+\w+\s*[:{]'],
     "类接口设计或继承关系存在问题"),
    PatternRule("日志/调试", "D",
     [r'\bLOG_', r'\blog_\b', r'\bprintf\b', r'\bcout\b', r'\bcerr\b', r'\bassert\b', r'\bstd::cout\b'],
     ["日志", "log", "打印", "输出", "debug", "调试", "assert", "printf", "cout"],
     [r'\bLOG_\w+\s*\(', r'\bprintf\s*\(', r'\bstd::cout\b'],
     "日志级别不当或使用 print 调试而非专用日志框架"),
    PatternRule("条件/分支复杂度", "D",
     [r'\bif\s*\(', r'\belse\s+if\b', r'\bswitch\b', r'\bcase\b', r'\?\s*.*\s*:'],
     ["if", "else", "switch", "分支", "条件", "嵌套", "复杂度", "圈复杂度", "三元"],
     [r'\bif\s*\(', r'\belse\s+if\b', r'\bswitch\s*\('],
     "条件分支嵌套过深或设计不够简洁"),
    PatternRule("代码重复", "D",
     [r'\bcopy\b\s+and\b\s+\bpaste\b'],
     ["重复", "duplicate", "复用", "reuse", "模板", "generic", "copy paste"],
     [],
     "存在明显的代码重复，应提取为公共函数或模板"),
]


def parse_code_context(context_str):
    """解析代码上下文文本，提取目标行和周围上下文。"""
    if context_str is None or not str(context_str).strip():
        return None, []
    lines = []
    target_code = None
    for line in str(context_str).split('\n'):
        line = line.rstrip()
        if not line:
            continue
        marker_match = re.match(r'^(\s*)(>>|\s{1,2})(\s*)(\d+):\s*(.*)', line)
        if marker_match:
            marker = marker_match.group(2).strip()
            marker = '>>' if marker == '>>' else '  '
            ln = int(marker_match.group(4))
            content = marker_match.group(5)
            lines.append({'ln': ln, 'marker': marker, 'content': content})
            if marker == '>>' and target_code is None:
                target_code = content
    return target_code, lines


def classify_review(target_code, comment, file_path):
    """对单条评论进行模式分类，返回匹配的模式标签列表。"""
    if target_code is None:
        target_code = ''
    comment_lower = (comment or '').lower()
    matched = []
    for rule in PATTERN_RULES:
        comment_hit = any(
            keyword.lower() in comment_lower
            for keyword in rule.comment_keywords)
        code_hit = any(
            re.search(pattern, target_code)
            for pattern in rule.target_code_patterns)
        if comment_hit or code_hit:
            matched.append((rule.label, rule.category))
    if not matched:
        return [('其他', 'D')]
    return matched


def build_structured_json(reviewer_name, reviewer_w3, records, source_file):
    """为单个评审人生成结构化 JSON。records 为 English-key dict 列表。"""
    # 按严重程度排序
    severity_order = {'致命': 0, '严重': 0, '阻断': 0, '高危': 0,
                      '一般': 1, '中危': 1, '低危': 2,
                      '建议': 3, '提示': 3, '优化建议': 3}

    def _sev_rank(r):
        return severity_order.get(str(r.get('severity', '')).strip(), 99)

    records = sorted(records, key=_sev_rank)

    reviews = []
    pattern_map = defaultdict(list)
    for idx, r in enumerate(records):
        review_id = idx + 1
        comment = str(r.get('comment', '') or '')
        file_path = str(r.get('file_path', '') or '')
        line = r.get('line', '')
        try:
            line = int(float(line)) if line != '' and line is not None else None
        except (ValueError, TypeError):
            line = None
        severity = str(r.get('severity', '') or '未知')
        created_at = str(r.get('created_at', '') or '')
        submitter_name = str(r.get('submitter_name', '') or '')
        submitter_w3 = str(r.get('submitter_w3', '') or '')

        target_code, context_lines = parse_code_context(r.get('code_context', ''))
        for label, category in classify_review(target_code, comment, file_path):
            pattern_map[(label, category)].append(review_id)

        reviews.append({
            'id': review_id,
            'comment': comment,
            'severity': severity,
            'file': file_path,
            'line': line,
            'target_code': target_code,
            'context_lines': context_lines,
            'submitter': {'name': submitter_name, 'w3': submitter_w3},
            'created_at': created_at,
        })

    pattern_clusters = []
    for (label, category), review_ids in sorted(pattern_map.items(), key=lambda x: -len(x[1])):
        pattern_clusters.append({
            'pattern': label, 'category': category,
            'count': len(review_ids), 'review_ids': sorted(review_ids),
        })

    file_counter = Counter(r['file'] for r in reviews if r['file'])
    file_distribution = dict(file_counter.most_common(30))
    sev_counter = Counter(r['severity'] for r in reviews)
    severity_distribution = dict(sev_counter)

    return {
        'meta': {
            'source_file': Path(source_file).name,
            'reviewer_name': str(reviewer_name),
            'reviewer_w3': str(reviewer_w3),
            'total_reviews': len(reviews),
            'mode': 'enhanced',
            'severity_distribution': severity_distribution,
            'unique_files': len(file_distribution),
            'total_patterns': len(pattern_clusters),
        },
        'reviews': reviews,
        'pattern_clusters': pattern_clusters,
        'file_distribution': file_distribution,
    }


def _load_records(input_path: str):
    """优先读 JSONL；Excel 输入时归一化为 English-key dict 列表。"""
    p = Path(input_path)
    if p.suffix == '.jsonl':
        return read_jsonl(str(p)), None
    # Excel fallback：归一化中文列名为英文
    import pandas as pd  # 延迟导入，避免无 pandas 环境报错
    df = pd.read_excel(str(p))
    records = []
    for _, row in df.iterrows():
        rec = {}
        for k, v in row.items():
            rec[CN_TO_EN.get(k, k)] = (None if pd.isna(v) else v)
        records.append(rec)
    # 从 records 里取 reviewer 信息
    rn = next((r.get('reviewer_name') for r in records if r.get('reviewer_name')), '')
    rw3 = next((r.get('reviewer_w3') for r in records if r.get('reviewer_w3')), '')
    return records, (rn, rw3)


def prepare(input_path: str, reviewer_w3: str = '', start: str = '', end: str = '') -> str:
    ensure_dirs()
    print('=' * 60)
    print('  评审数据预处理：enriched → 结构化 JSON')
    print('=' * 60)

    records, excel_meta = _load_records(input_path)
    print(f'  载入 {len(records)} 条记录')

    # 防御性噪声过滤
    before = len(records)
    records = [r for r in records if not is_noise_comment(r.get('comment', ''))]
    if len(records) != before:
        print(f'  防御性噪声过滤：移除 {before - len(records)} 条，剩余 {len(records)} 条')

    # reviewer 信息
    reviewer_name = ''
    if excel_meta:
        reviewer_name, reviewer_w3 = excel_meta
    else:
        reviewer_name = next((r.get('reviewer_name') for r in records if r.get('reviewer_name')), '')
        if not reviewer_w3:
            reviewer_w3 = next((r.get('reviewer_w3') for r in records if r.get('reviewer_w3')), '')

    if not reviewer_w3:
        raise RuntimeError('无法确定 reviewer_w3')

    # start/end 从文件名解析
    if not (start and end):
        m = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_enriched\.(?:jsonl|xlsx)$',
                      str(input_path))
        if m:
            start, end = m.group(1), m.group(2)
    start, end = start or 'unknown', end or 'unknown'

    data = build_structured_json(reviewer_name, reviewer_w3, records, input_path)
    data['meta'].update({
        'distill_start': start,
        'distill_end': end,
        'prepared_at': now_iso(),
    })

    sev_str = ', '.join(f'{k}:{v}' for k, v in sorted(data['meta']['severity_distribution'].items()))
    print(f'  严重程度分布: {sev_str}')
    print(f'  涉及文件数: {data["meta"]["unique_files"]}，代码模式数: {data["meta"]["total_patterns"]}')
    for p in data['pattern_clusters'][:5]:
        print(f'    [{p["category"]}] {p["pattern"]}: {p["count"]}条')

    out = STRUCTURED_DIR / f'{reviewer_w3}_{start}_{end}_structured.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'  → 输出: {out}')
    return str(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='enriched → 结构化 JSON')
    parser.add_argument('--input', required=True, help='enriched JSONL 或 Excel 路径')
    parser.add_argument('--reviewer-w3', default='', help='检视人 w3（JSONL 可省略）')
    parser.add_argument('--start', default='', help='开始日期（不传则从文件名解析）')
    parser.add_argument('--end', default='', help='结束日期（不传则从文件名解析）')
    args = parser.parse_args()
    prepare(input_path=args.input, reviewer_w3=args.reviewer_w3,
            start=args.start, end=args.end)
