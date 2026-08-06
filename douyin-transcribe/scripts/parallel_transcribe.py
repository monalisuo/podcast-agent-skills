#!/usr/bin/env python3
"""
并行分块音频转录 — 将长音频切块，多进程并行转写，大幅提速

用法:
  python parallel_transcribe.py <audio_path> [--chunk-min 15] [--workers 4] [--model small]

示例:
  python parallel_transcribe.py podcast.mp3
  python parallel_transcribe.py podcast.mp3 --chunk-min 10 --workers 8 --model tiny
"""

import sys, os, re, time, json, hashlib, tempfile, shutil, subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse

# ── 路径配置 ──────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMP_DIR = SKILL_DIR / "temp"
OUTPUT_DIR = SKILL_DIR / "douyin-transcripts"
CACHE_DIR = Path.home() / ".cache" / "podcast-agent" / "transcripts"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def log(msg, emoji=""):
    prefix = f"{emoji} " if emoji else ""
    print(f"{prefix}{msg}", flush=True)


def find_ffmpeg():
    """Locate ffmpeg executable"""
    for p in [r"C:\ffmpeg\bin\ffmpeg.exe", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg", "ffmpeg"]:
        try:
            subprocess.run([p, "-version"], capture_output=True, timeout=5)
            return p
        except Exception:
            continue
    raise RuntimeError("找不到 ffmpeg，请安装后放到 PATH 或 C:\\ffmpeg\\bin\\")


def get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds using ffprobe"""
    ffprobe = str(Path(find_ffmpeg()).with_name("ffprobe.exe"))
    cmd = [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
           "-of", "csv=p=0", audio_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return float(result.stdout.strip())


def split_audio(audio_path: str, chunk_duration_sec: float, work_dir: Path) -> list[dict]:
    """Split audio into equal-duration chunks using ffmpeg segment muxer"""
    ffmpeg = find_ffmpeg()
    total_dur = get_audio_duration(audio_path)
    num_chunks = max(1, int(total_dur / chunk_duration_sec))

    # Adjust chunk duration so all chunks are equal
    actual_chunk_dur = total_dur / num_chunks

    log(f"总时长: {total_dur/60:.1f} 分钟 → 切成 {num_chunks} 块，每块 {actual_chunk_dur/60:.1f} 分钟", "✂️")

    chunks = []
    for i in range(num_chunks):
        start = i * actual_chunk_dur
        chunk_path = work_dir / f"chunk_{i:03d}.mp3"

        cmd = [
            ffmpeg, "-y", "-i", audio_path,
            "-ss", str(start), "-t", str(actual_chunk_dur),
            "-vn", "-ar", "16000", "-ac", "1",
            "-c:a", "libmp3lame", "-q:a", "2",
            str(chunk_path)
        ]
        subprocess.run(cmd, capture_output=True, timeout=60)

        if chunk_path.exists() and chunk_path.stat().st_size > 1000:
            chunks.append({
                "index": i,
                "path": str(chunk_path),
                "start_sec": start,
                "duration_sec": actual_chunk_dur,
            })
            log(f"  块 {i+1}/{num_chunks}: {chunk_path.stat().st_size/1024:.0f}KB", "✂️")
        else:
            log(f"  块 {i+1}/{num_chunks}: 失败，跳过", "⚠️")

    return chunks


def transcribe_chunk(chunk_info: dict, model_name: str, device: str = "cpu", compute_type: str = "int8") -> dict:
    """Transcribe a single audio chunk (runs in subprocess)"""
    chunk_path = chunk_info["path"]

    # Check cache first
    cache_key = hashlib.md5(chunk_path.encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.txt"
    if cache_file.exists():
        text = cache_file.read_text(encoding="utf-8")
        if len(text) > 50:
            return {**chunk_info, "text": text, "cached": True}

    # Transcribe
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(chunk_path, language="zh", beam_size=5, vad_filter=True)
    text = " ".join(seg.text for seg in segments)

    # Save to cache
    cache_file.write_text(text, encoding="utf-8")

    return {**chunk_info, "text": text, "cached": False}


def save_transcript(full_text: str, audio_path: str, info: dict):
    """Save merged transcript to markdown file"""
    timestamp = time.strftime("%Y-%m-%d")
    audio_name = Path(audio_path).stem
    safe_title = re.sub(r'[\\/*?:"<>|]', '', audio_name)[:60]
    filename = f"{timestamp}-{safe_title}.md"
    filepath = OUTPUT_DIR / filename

    content = f"""# {audio_name}

**来源**: {info.get('source_url', audio_path)}
**博主**: {info.get('author', '未知')}
**时长**: {info.get('duration_sec', 0) // 60}分{info.get('duration_sec', 0) % 60}秒
**转录时间**: {time.strftime('%Y-%m-%d %H:%M')}
**方式**: faster-whisper 并行分块识别 ({info.get('model', 'unknown')} 模型)

---

{full_text}
"""
    filepath.write_text(content, encoding='utf-8')
    log(f"已保存: {filepath}", "💾")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="并行分块音频转录")
    parser.add_argument("audio", help="音频文件路径")
    parser.add_argument("--chunk-min", type=float, default=12, help="每块时长（分钟），默认 12")
    parser.add_argument("--workers", type=int, default=0, help="并行进程数，默认 CPU 核心数-1")
    parser.add_argument("--model", default="small", choices=["tiny", "small", "medium"], help="Whisper 模型")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="推理设备（cpu/cuda）")
    parser.add_argument("--title", default="", help="自定义标题")
    parser.add_argument("--author", default="未知", help="作者/播客名")
    parser.add_argument("--source-url", default="", help="来源 URL")
    args = parser.parse_args()

    audio_path = args.audio
    if not Path(audio_path).exists():
        print(f"❌ 文件不存在: {audio_path}")
        sys.exit(1)

    chunk_sec = args.chunk_min * 60
    workers = args.workers or max(1, (os.cpu_count() or 4) - 1)
    model = args.model
    device = args.device
    compute_type = "float16" if device == "cuda" else "int8"

    log(f"并行转录: {Path(audio_path).name}", "🎙️")
    log(f"模型: {model} | 设备: {device} | 并行: {workers} 进程 | 块大小: {args.chunk_min} 分钟", "⚙️")

    # Clean up any old chunks
    chunk_dir = TEMP_DIR / "chunks"
    if chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # Step 1: Split audio
    chunks = split_audio(audio_path, chunk_sec, chunk_dir)
    if not chunks:
        log("切分失败！", "❌")
        sys.exit(1)

    # Step 2: Parallel transcribe
    log(f"开始并行转录...", "📝")
    results = []

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(transcribe_chunk, c, model, device, compute_type): c for c in chunks}

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            cached_str = " 💾缓存" if result.get("cached") else ""
            log(f"  完成块 {result['index']+1}/{len(chunks)}{cached_str}", "✅")

    # Step 3: Sort and merge
    results.sort(key=lambda r: r["index"])
    full_text = "\n\n".join(r["text"] for r in results)

    elapsed = time.time() - t0
    log(f"转录完成！{elapsed:.0f} 秒，共 {len(full_text)} 字", "🎉")

    # Step 4: Save
    info = {
        "title": args.title or Path(audio_path).stem,
        "author": args.author,
        "source_url": args.source_url or audio_path,
        "duration_sec": int(sum(c["duration_sec"] for c in chunks)),
        "model": model,
    }
    output_path = save_transcript(full_text, audio_path, info)

    # Step 5: Cleanup chunks
    shutil.rmtree(chunk_dir, ignore_errors=True)

    print(f"\n📄 转录文件: {output_path}")

    # Also print path for the podcast skill to pick up
    print(f"\n===ASSET_PATH===")
    print(str(output_path))


if __name__ == "__main__":
    main()
