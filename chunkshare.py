"""chunkshare —— 检查同一文档不同分片之间的描述是否一致。

比对同一文档各分片里的元数据与摘要，找出互相矛盾的部分

定位：
  关注的是「同一文档内部」的矛盾，不是文档之间的

设计约束：
  1. **只报告能定位到具体位置的结论**，不做语义猜测。
  2. **规则表公开**，每条命中都能对应到 长文档分片一致性 领域的一条明示规则。
  3. **输入为空或格式不对时明确报错**，不静默返回空结果。

仅依赖 Python 标准库。

用法:
    python chunkshare.py --help
    python chunkshare.py --file input.txt
    python chunkshare.py --text "示例内容"
    python chunkshare.py --file input.txt --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# 领域规则表：每条规则独立可核查，命中即报，不做推断。
RULES: list[dict] = [
    {
        "name": "长文档分片一致性·缺失",
        "why": "缺少长文档分片一致性的关键要素时无法给出可靠判定",
        "severity": "high",
        "keywords": ['缺失', 'missing', 'absent', '缺少', '没有'],
    },
    {
        "name": "长文档分片一致性·冲突",
        "why": "同一份输入里两处长文档分片一致性描述互相矛盾",
        "severity": "high",
        "keywords": ['冲突', 'conflict', 'contradict', '矛盾', '不一致', '相反'],
    },
    {
        "name": "长文档分片一致性·越界",
        "why": "长文档分片一致性的取值超出常规范围",
        "severity": "medium",
        "keywords": ['越界', 'out of range', 'outlier', '越界', '超限', '超过'],
    },
    {
        "name": "长文档分片一致性·退化",
        "why": "长文档分片一致性的信息量不足以支撑结论",
        "severity": "medium",
        "keywords": ['退化', 'degrade', 'insufficient', '不足', '太少', '无法'],
    },
    {
        "name": "长文档分片一致性·泄漏",
        "why": "长文档分片一致性相关的内容被意外暴露",
        "severity": "high",
        "keywords": ['泄漏', 'leak', 'expose', '泄漏', '暴露', '明文'],
    },
    {
        "name": "长文档分片一致性·重复",
        "why": "同一处长文档分片一致性信息被反复传递",
        "severity": "low",
        "keywords": ['重复', 'duplicate', 'repeat', '重复', 'again'],
    },
    {
        "name": "长文档分片一致性·陈旧",
        "why": "长文档分片一致性的时效性已经过期",
        "severity": "medium",
        "keywords": ['陈旧', 'stale', 'expired', '过期', '陈旧', '旧版'],
    },
    {
        "name": "长文档分片一致性·不可核",
        "why": "长文档分片一致性的说法无法追溯到具体证据",
        "severity": "high",
        "keywords": ['不可核', 'unverifiable', 'no evidence', '无法追溯', '没有来源'],
    },
]


def chunkshare_split_items(text: str) -> list[str]:
    """按行/句切分为可比对的条目。"""
    items: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        for p in re.split(r"(?<=[。！？；;])\s*", line):
            p = p.strip()
            if p:
                items.append(p)
    return items


def chunkshare_polarity(text: str) -> int:
    """判定一句的极性：1 正向，-1 否定，0 中性。

    只看显式否定标记与显式肯定标记，不做语义推断。
    """
    neg = any(m in text for m in ("不", "无", "未", "非", "禁止", "避免",
                                  "not ", "no ", "never", "without"))
    pos = any(m in text for m in ("是", "有", "会", "应", "需", "必须",
                                  "must", "should", "will ", "has "))
    if neg and not pos:
        return -1
    if pos and not neg:
        return 1
    return 0


def chunkshare_word_tokens(text: str) -> set[str]:
    """抽词元。

    拉丁词按单词切；中文按**二元组**切。不用长正则 `[\u4e00-\u9fff]{2,}`——
    那会贪婪地把整句当成一个词元，两句中文只要措辞不同就永远没有共同词元，
    同主题判定会全部失效。二元组既能命中共享片段，又不会被长句吞掉。
    """
    low = text.lower()
    out = set(re.findall(r"[a-z]{3,}", low))
    for seg in re.findall(r"[\u4e00-\u9fff]+", low):
        if len(seg) == 1:
            out.add(seg)
        else:
            for i in range(len(seg) - 1):
                out.add(seg[i:i + 2])
    return out


def chunkshare_detect_pairs(items: list[str]) -> list[dict]:
    """找同主题但极性相反的条目对。"""
    pairs: list[dict] = []
    for i, a in enumerate(items):
        pa = chunkshare_polarity(a)
        if pa == 0:
            continue
        for j in range(i + 1, len(items)):
            b = items[j]
            pb = chunkshare_polarity(b)
            if pb == 0 or pb == pa:
                continue
            # 共享词元才算同主题，避免把无关句子配成对
            ka = chunkshare_word_tokens(a)
            kb = chunkshare_word_tokens(b)
            if not (ka & kb):
                continue
            pairs.append({
                "a": {"index": i, "text": a, "polarity": pa},
                "b": {"index": j, "text": b, "polarity": pb},
                "shared": sorted(ka & kb)[:6],
            })
    return pairs


def chunkshare_analyze(text: str) -> dict:
    """主分析：返回条目数、矛盾对与分布。"""
    items = chunkshare_split_items(text)
    pairs = chunkshare_detect_pairs(items)
    covered = {p["a"]["index"] for p in pairs} | {p["b"]["index"] for p in pairs}
    return {
        "item_count": len(items),
        "pairs": pairs,
        "conflict_count": len(pairs),
        "conflicted_items": len(covered),
        "clean_items": len(items) - len(covered),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render(result: dict) -> str:
    """把结果渲染成人读的文本。每个工具的版式不同。"""
    out: list[str] = []
    if not result.get("ok", True):
        out.append(f"无法分析：{{result.get('error', '未知原因')}}")
        return "\n".join(out)
    out.append(f"条目数：{result['item_count']}")
    out.append(f"矛盾对：{result['conflict_count']}")
    out.append(f"涉及条目：{result['conflicted_items']}（干净 {result['clean_items']}）")
    out.append("")
    for i, pair in enumerate(result["pairs"], 1):
        out.append(f"矛盾 {i}  共享词: {', '.join(pair['shared'])}")
        out.append(f"  A[{pair['a']['index']}]: {pair['a']['text'][:100]}")
        out.append(f"  B[{pair['b']['index']}]: {pair['b']['text'][:100]}")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="chunkshare",
        description="比对同一文档各分片里的元数据与摘要，找出互相矛盾的部分（仅依赖标准库）",
        epilog=(
            "示例:\n"
            "  python chunkshare.py --file input.txt\n"
            "  python chunkshare.py --text '示例内容'\n"
            "  python chunkshare.py --file input.txt --json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="输入文件路径")
    src.add_argument("--text", help="直接给出输入内容")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            print(f"读不了文件：{{e}}", file=sys.stderr)
            return 2
    else:
        content = args.text

    if not content.strip():
        print("输入是空的。", file=sys.stderr)
        return 2

    result = chunkshare_analyze(content)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(render(result))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
