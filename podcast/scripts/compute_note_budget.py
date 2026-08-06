#!/usr/bin/env python3
"""
播客笔记预算计算器

根据转写字数、时长、投资信号数量、嘉宾权威度等因子，
计算推荐笔记长度和写作指引。

用法:
  python compute_note_budget.py --transcript transcript.txt --metadata metadata.json
  python compute_note_budget.py --transcript-chars 25000 --duration-min 152 --signals 12
"""

import argparse, json, math, sys
from datetime import datetime, timezone
from pathlib import Path


def clamp(value: float, low: int, high: int) -> int:
    return int(max(low, min(high, round(value))))


def visible_text_chars(text: str) -> int:
    """Count visible characters (exclude markdown syntax)"""
    import re
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+", "", text)
    return len(text)


def assess_topic_relevance(transcript: str, keywords: list[str] | None = None) -> float:
    """Score topic relevance based on keyword density"""
    if not keywords:
        keywords = [
            "投资", "ETF", "半导体", "股票", "估值", "交易",
            "基金", "风险", "仓位", "周期", "泡沫", "创新",
            "收益率", "资产", "组合", "对冲", "杠杆", "做空",
            "做多", "行业", "财报", "净利润", "营收", "市值",
        ]
    text_lower = transcript.lower()
    matches = sum(1 for kw in keywords if kw.lower() in text_lower)
    density = matches / max(len(keywords), 1)
    # Scale: ~10 matches → 0.5, ~20 matches → 0.9
    return min(1.0, density * 2.0)


def count_investment_signals(transcript: str) -> int:
    """Count distinct investment concepts mentioned"""
    signals = [
        # 投资方法论
        "护城河", "安全边际", "能力圈", "复利", "价值投资",
        "止损", "仓位管理", "分散", "集中投资", "定投",
        # 估值相关
        "PE", "PB", "PS", "DCF", "估值", "合理价格",
        # 交易策略
        "左侧", "右侧", "追涨", "抄底", "波段", "趋势",
        # 市场分析
        "宏观", "利率", "通胀", "GDP", "PMI", "美联储",
        # 具体标的信号
        "代码", "买入", "卖出", "持有", "目标价",
        # 方法论引用
        "巴菲特", "芒格", "彼得林奇", "达利欧", "索罗斯",
    ]
    text_lower = transcript.lower()
    found = set()
    for sig in signals:
        if sig.lower() in text_lower:
            found.add(sig)
    return len(found)


GUEST_AUTHORITY = {
    # 顶级投资人/企业家
    "徐新": 0.95, "张磊": 0.95, "沈南鹏": 0.95, "李丰": 0.85,
    "雷军": 0.90, "段永平": 0.95, "李开复": 0.85,
    # 知名分析师/经济学家
    "洪灏": 0.80, "高善文": 0.80, "李迅雷": 0.80,
    # 默认
    "_default": 0.65,
}


def get_guest_authority(guests: list[str]) -> float:
    """Get authority score for guest list"""
    if not guests:
        return 0.65
    scores = [GUEST_AUTHORITY.get(g, GUEST_AUTHORITY["_default"]) for g in guests]
    return sum(scores) / len(scores)


def compute_budget(
    transcript_chars: int,
    duration_minutes: float,
    investment_signals: int | None = None,
    guest_authority: float = 0.65,
    topic_relevance: float = 0.5,
    transcript_text: str = "",
) -> dict:
    """Compute recommended note budget"""

    if investment_signals is None and transcript_text:
        investment_signals = count_investment_signals(transcript_text)
    investment_signals = investment_signals or 0

    if topic_relevance == 0.5 and transcript_text:
        topic_relevance = assess_topic_relevance(transcript_text)

    # Base formula
    base = 500 + duration_minutes * 35 + transcript_chars * 0.06 + investment_signals * 80
    quality_multiplier = 1.0 + (guest_authority + topic_relevance) / 2

    target_min = clamp(base * quality_multiplier, 800, 65000)
    target_max = clamp(target_min * 1.45, 1200, 90000)

    # Determine granularity
    if duration_minutes >= 40 or transcript_chars >= 20000:
        granularity = "deep_dive"
        guidance = "深度访谈：按主题分章写，保留论证链、案例细节、反例和可操作清单"
    elif duration_minutes >= 15 or transcript_chars >= 8000:
        granularity = "structured_explainer"
        guidance = "结构化分析：保留结构、关键论点、代表性证据，每章补充投资关联"
    elif duration_minutes >= 5 or transcript_chars >= 3000:
        granularity = "short_deep_note"
        guidance = "精简笔记：写清核心观点、关键细节、可迁移方法和适用边界"
    else:
        granularity = "micro_episode"
        guidance = "微型笔记：提炼核心信息、场景、亮点和少量实践启发"

    if investment_signals >= 10:
        guidance += "。投资信息密度高，建议增设「投资方法论提取」板块"
    if topic_relevance >= 0.8:
        guidance += "。与用户投资体系高度相关，优先处理"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_minutes": round(duration_minutes, 1),
        "transcript_chars": transcript_chars,
        "investment_signals": investment_signals,
        "guest_authority": round(guest_authority, 3),
        "topic_relevance": round(topic_relevance, 3),
        "quality_multiplier": round(quality_multiplier, 3),
        "base_chars": round(base),
        "recommended_note_chars_min": target_min,
        "recommended_note_chars_max": target_max,
        "granularity": granularity,
        "writing_guidance": guidance,
    }


def main():
    parser = argparse.ArgumentParser(description="播客笔记预算计算器")
    parser.add_argument("--transcript", type=Path, help="转写稿文件路径")
    parser.add_argument("--metadata", type=Path, help="metadata.json 文件路径")
    parser.add_argument("--transcript-chars", type=int, help="转写字数（直接指定）")
    parser.add_argument("--duration-min", type=float, help="音频时长（分钟）")
    parser.add_argument("--signals", type=int, help="投资信号数")
    parser.add_argument("--guest-authority", type=float, default=0.65)
    parser.add_argument("--topic-relevance", type=float, default=0.5)
    parser.add_argument("--guests", nargs="*", help="嘉宾姓名列表")
    parser.add_argument("--out", type=Path, help="输出 JSON 文件路径")
    args = parser.parse_args()

    transcript_text = ""
    transcript_chars = args.transcript_chars or 0
    duration_minutes = args.duration_min or 0.0
    investment_signals = args.signals
    gauthority = args.guest_authority
    topic_relevance = args.topic_relevance

    # Load from files
    if args.transcript and args.transcript.exists():
        transcript_text = args.transcript.read_text(encoding="utf-8", errors="replace")
        if not transcript_chars:
            transcript_chars = visible_text_chars(transcript_text)

    if args.metadata and args.metadata.exists():
        meta = json.loads(args.metadata.read_text(encoding="utf-8"))
        if not duration_minutes:
            ds = meta.get("duration_seconds", 0)
            duration_minutes = ds / 60 if ds else 0
        if args.guests:
            gauthority = get_guest_authority(args.guests)
        elif meta.get("guests"):
            gauthority = get_guest_authority(meta["guests"])

    if not args.guests and not args.metadata:
        # Try --guests flag
        pass

    # Compute
    budget = compute_budget(
        transcript_chars=transcript_chars,
        duration_minutes=duration_minutes,
        investment_signals=investment_signals,
        guest_authority=gauthority,
        topic_relevance=topic_relevance,
        transcript_text=transcript_text,
    )

    # Output
    result = json.dumps(budget, ensure_ascii=False, indent=2)
    print(result)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(result + "\n", encoding="utf-8")
        print(f"\n💾 已保存: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
