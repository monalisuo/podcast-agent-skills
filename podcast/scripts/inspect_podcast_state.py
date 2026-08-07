#!/usr/bin/env python3
"""
播客工作流状态检查器

检查指定目录下已有的资产，输出：
- reusable_artifacts: 可直接复用的产物
- recommended_next_steps: 需要执行的下一步
- avoid_rework: 不要重复做的昂贵步骤
- missing: 缺失的资产

用法:
  python inspect_podcast_state.py --out-dir "📚 学习资源/高能量/"
  python inspect_podcast_state.py --audio-url "https://..." --out-dir "..."
"""

import argparse, json, sys, hashlib
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "podcast-agent" / "transcripts"


def get_cache_key(audio_url: str) -> str:
    return hashlib.md5(audio_url.encode()).hexdigest()


def file_age_hours(path: Path) -> float:
    """Age of file in hours"""
    mtime = path.stat().st_mtime
    age_seconds = datetime.now().timestamp() - mtime
    return age_seconds / 3600


def check_state(out_dir: Path, audio_url: str = "", podcast_name: str = "") -> dict:
    out_dir = Path(out_dir)
    assets_dir = out_dir / "assets"

    state = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out_dir),
        "reusable_artifacts": [],
        "recommended_next_steps": [],
        "avoid_rework": [],
        "missing": [],
        "stale": [],
    }

    # Check metadata
    metadata_path = assets_dir / "metadata.json"
    if metadata_path.exists():
        age = file_age_hours(metadata_path)
        state["reusable_artifacts"].append({
            "file": "assets/metadata.json",
            "age_hours": round(age, 1),
            "note": "元数据已存在，跳过 RSS/页面提取"
        })
        state["avoid_rework"].append("RSS/页面元数据提取")
    else:
        state["missing"].append("metadata.json — 需要从播客来源提取")

    # Check transcript
    transcript_path = assets_dir / "transcript.md"
    transcript_txt = assets_dir / "transcript.txt"
    has_transcript = False
    for tp in [transcript_path, transcript_txt]:
        if tp.exists():
            age = file_age_hours(tp)
            chars = len(tp.read_text(encoding="utf-8", errors="replace"))
            state["reusable_artifacts"].append({
                "file": str(tp.relative_to(out_dir)),
                "age_hours": round(age, 1),
                "chars": chars,
                "note": "转写稿已存在，跳过下载和转写"
            })
            state["avoid_rework"].append("音频下载 + 本地转写")
            has_transcript = True
            break

    # Check cache
    if audio_url:
        cache_key = get_cache_key(audio_url)
        cache_file = CACHE_DIR / f"{cache_key}.txt"
        if cache_file.exists():
            chars = len(cache_file.read_text(encoding="utf-8", errors="replace"))
            state["reusable_artifacts"].append({
                "file": f"~/.cache/podcast-agent/transcripts/{cache_key}.txt",
                "chars": chars,
                "note": "转写缓存命中，秒级可用"
            })
            state["avoid_rework"].append("音频下载 + 本地转写（缓存命中）")
            has_transcript = True

    if not has_transcript:
        state["recommended_next_steps"].append({
            "step": "download_and_transcribe",
            "priority": "high",
            "action": "下载音频 → 本地 faster-whisper 转写",
            "estimated_time": "2h 音频约需 15-25 分钟（tiny 模型）"
        })
        state["missing"].append("transcript.md — 需要下载音频并转写")

    # Check shownotes
    shownotes_path = assets_dir / "shownotes.md"
    if shownotes_path.exists():
        state["reusable_artifacts"].append({
            "file": "assets/shownotes.md",
            "note": "Shownotes + 时间轴已整理"
        })
    else:
        state["recommended_next_steps"].append({
            "step": "parse_shownotes",
            "priority": "medium",
            "action": "从 RSS 页面提取 shownotes 和时间轴"
        })

    # Check note budget
    budget_path = assets_dir / "note_budget.json"
    if budget_path.exists():
        age = file_age_hours(budget_path)
        if age < 24:
            state["reusable_artifacts"].append({
                "file": "assets/note_budget.json",
                "age_hours": round(age, 1),
                "note": "预算仍在有效期内（<24h）"
            })
        else:
            state["stale"].append({
                "file": "assets/note_budget.json",
                "age_hours": round(age, 1),
                "note": "预算已过期（>24h），建议重新计算"
            })
    else:
        state["recommended_next_steps"].append({
            "step": "compute_budget",
            "priority": "low",
            "action": "运行 compute_note_budget.py 计算推荐笔记长度"
        })

    # Check existing notes
    existing_notes = sorted(out_dir.glob("E*-*.md"))
    if existing_notes:
        state["reusable_artifacts"].append({
            "file": f"{len(existing_notes)} 篇已有笔记",
            "files": [n.name for n in existing_notes],
            "note": "该播客已有笔记，可能需要更新索引"
        })

    # Check podcast index
    index_path = out_dir / "podcast_index.md"
    if index_path.exists():
        state["reusable_artifacts"].append({
            "file": "podcast_index.md",
            "note": "播客索引已存在"
        })

    # Final summary
    if not state["missing"]:
        state["summary"] = "✅ 所有资产齐全，可直接基于已有材料写笔记"
    elif has_transcript:
        state["summary"] = "⚠️ 转写已有，缺元数据/shownotes（非阻塞），可先写笔记"
    else:
        state["summary"] = "❌ 缺少转写稿，需要先下载音频并转写"

    return state


def main():
    parser = argparse.ArgumentParser(description="播客工作流状态检查器")
    parser.add_argument("--out-dir", required=True, type=Path, help="播客资产输出目录")
    parser.add_argument("--audio-url", default="", help="音频 URL（用于缓存检查）")
    args = parser.parse_args()

    state = check_state(args.out_dir, args.audio_url)
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
