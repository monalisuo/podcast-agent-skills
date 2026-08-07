#!/usr/bin/env python3
"""
本地音频转录脚本（无需 API）— 支持抖音/播客/通用音频

用法: python douyin_transcribe.py <抖音链接 | 本地音频 | 音频URL>

工作流程:
  1. 从短链/分享文本提取视频 ID（抖音模式）
  2. 通过 SSR 页面获取视频元数据和播放地址（抖音模式）
  3. ffmpeg 下载音频
  4. faster-whisper 本地语音识别（带缓存 + 超时保护）
  5. 输出格式化逐字稿

依赖:
  - ffmpeg（音频下载）
  - faster-whisper（本地语音识别，首次运行下载模型 ~500MB）

新增特性:
  - 转录缓存：md5(音频路径) → ~/.cache/podcast-agent/transcripts/
  - 超时保护：长音频 30 分钟超时，自动终止保留部分结果
"""

import sys, os, re, json, time, subprocess, hashlib, multiprocessing
import urllib.request, urllib.error
from pathlib import Path

# ── 路径配置 ──────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMP_DIR = SKILL_DIR / "temp"
OUTPUT_DIR = SKILL_DIR / "douyin-transcripts"
CACHE_DIR = Path.home() / ".cache" / "podcast-agent" / "transcripts"
TRANSCRIPT_TIMEOUT = 1800  # 30 minutes for long audio

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── 工具函数 ──────────────────────────────────────────
def log(msg, emoji=""):
    prefix = f"{emoji} " if emoji else ""
    print(f"{prefix}{msg}")

def error(msg):
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)

# ── 第一步：提取视频 ID ──────────────────────────────
def extract_video_id(raw_input: str) -> str:
    """从抖音短链或分享文本中提取视频 ID"""
    # 直接是纯数字 ID
    if re.match(r'^\d{15,20}$', raw_input.strip()):
        return raw_input.strip()

    # 从短链重定向获取真实 URL
    short_link = re.search(r'(https?://v\.douyin\.com/\S+?)(?:\s|$)', raw_input)
    if short_link:
        url = short_link.group(1)
        log(f"解析短链: {url}", "🔗")
        try:
            req = urllib.request.Request(url, method='HEAD')
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            with urllib.request.urlopen(req, timeout=10) as resp:
                real_url = resp.geturl()
        except Exception:
            # HEAD 失败试试 GET
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            with urllib.request.urlopen(req, timeout=10) as resp:
                real_url = resp.geturl()
        log(f"→ {real_url}", "🔗")
    else:
        # 尝试从 douyin.com/video/xxx 格式提取
        match = re.search(r'douyin\.com/video/(\d+)', raw_input)
        if match:
            return match.group(1)
        # 尝试 iesdouyin.com
        match = re.search(r'iesdouyin\.com/share/video/(\d+)', raw_input)
        if match:
            return match.group(1)
        error("无法从输入中提取抖音链接或视频 ID")

    # 从重定向后的 URL 提取 ID
    match = re.search(r'video/(\d+)', real_url)
    if match:
        return match.group(1)

    error(f"无法提取视频 ID: {real_url}")

# ── 第二步：获取视频元数据和播放地址 ──────────────────
def fetch_video_info(video_id: str) -> dict:
    """通过 iesdouyin.com SSR 页面获取视频信息"""
    ssr_url = f"https://www.iesdouyin.com/share/video/{video_id}/"

    log(f"获取视频信息...", "🌐")
    req = urllib.request.Request(ssr_url)
    req.add_header('User-Agent',
        'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')
    req.add_header('Referer', 'https://www.douyin.com/')

    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode('utf-8')

    # 从 _ROUTER_DATA 提取视频信息
    match = re.search(r'window\._ROUTER_DATA\s*=\s*({.*?});\s*</script>', html)
    if not match:
        error("无法从页面提取视频数据")

    data = json.loads(match.group(1))
    try:
        item = data['loaderData']['video_(id)/page']['videoInfoRes']['item_list'][0]
    except (KeyError, IndexError):
        error("视频数据格式异常，可能需要登录抖音")

    # 提取元数据
    desc = item.get('desc', '未知标题')
    author = item.get('author', {}).get('nickname', '未知作者')
    duration_ms = item.get('video', {}).get('duration', 0)
    duration_sec = duration_ms // 1000

    # 提取播放地址
    play_addr = item.get('video', {}).get('play_addr', {})
    url_list = play_addr.get('url_list', [])
    if not url_list:
        error("未找到视频播放地址")

    # 统计信息
    stats = item.get('statistics', {})
    likes = stats.get('digg_count', 0)
    comments = stats.get('comment_count', 0)
    collects = stats.get('collect_count', 0)

    return {
        'video_id': video_id,
        'title': desc,
        'author': author,
        'duration_sec': duration_sec,
        'play_url': url_list[0],
        'likes': likes,
        'comments': comments,
        'collects': collects,
        'source_url': f"https://www.douyin.com/video/{video_id}",
    }

# ── 第三步：下载音频 ──────────────────────────────────
def download_audio(info: dict) -> Path:
    """用 ffmpeg 从播放地址下载并提取音频"""
    audio_path = TEMP_DIR / f"douyin_{info['video_id']}.mp3"
    play_url = info['play_url']

    duration_str = f"{info['duration_sec'] // 60}分{info['duration_sec'] % 60}秒"
    log(f"下载音频 ({duration_str})...", "🎵")

    # 检测 ffmpeg
    ffmpeg = "ffmpeg"
    for possible in [r"C:\ffmpeg\bin\ffmpeg.exe", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if Path(possible).exists():
            ffmpeg = possible
            break

    cmd = [
        ffmpeg, '-y',
        '-user_agent', 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36',
        '-headers', 'Referer: https://www.douyin.com/\r\n',
        '-i', play_url,
        '-vn', '-ar', '16000', '-ac', '1',
        '-c:a', 'libmp3lame', '-q:a', '2',
        str(audio_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not audio_path.exists() or audio_path.stat().st_size < 1000:
        error(f"音频下载失败: {result.stderr[-300:] if result.stderr else '未知错误'}")

    size_mb = audio_path.stat().st_size / 1024 / 1024
    log(f"完成: {size_mb:.1f} MB", "✅")
    return audio_path

# ── 缓存管理 ──────────────────────────────────────────
def get_cache_key(audio_path: Path) -> str:
    """Generate MD5 cache key from audio file path"""
    return hashlib.md5(str(audio_path.resolve()).encode()).hexdigest()

def load_from_cache(cache_key: str) -> str | None:
    """Load cached transcript if exists"""
    cache_file = CACHE_DIR / f"{cache_key}.txt"
    if cache_file.exists():
        text = cache_file.read_text(encoding="utf-8")
        if len(text) > 100:  # Must have meaningful content
            log(f"命中缓存: {len(text)} 字", "💾")
            return text
    return None

def save_to_cache(cache_key: str, transcript: str):
    """Save transcript to cache"""
    cache_file = CACHE_DIR / f"{cache_key}.txt"
    cache_file.write_text(transcript, encoding="utf-8")
    log("已写入缓存", "💾")

# ── 转录工作进程（用于超时控制）──────────────────────
def _transcribe_worker(audio_path: str, language: str, model_names: list, result_queue):
    """Worker function for multiprocessing transcription"""
    try:
        from faster_whisper import WhisperModel

        model = None
        for model_name in model_names:
            try:
                model = WhisperModel(model_name, device="cpu", compute_type="int8")
                break
            except Exception:
                continue

        if model is None:
            result_queue.put({"success": False, "error": "所有模型加载失败"})
            return

        segments, info_obj = model.transcribe(
            audio_path, language=language, beam_size=5, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        lines = [seg.text.strip() for seg in segments if seg.text.strip()]
        result = "\n\n".join(lines)

        result_queue.put({
            "success": True,
            "transcript": result,
            "chars": len(result),
            "language": info_obj.language
        })
    except Exception as e:
        result_queue.put({"success": False, "error": str(e)})

# ── 第四步：本地语音识别（带缓存 + 超时）─────────────
def transcribe_local(audio_path: Path, info: dict) -> str:
    """用 faster-whisper 进行本地语音识别（带缓存和超时保护）"""
    duration_str = f"{info['duration_sec'] // 60}分{info['duration_sec'] % 60}秒" if info.get('duration_sec') else "未知时长"
    log(f"本地语音识别 ({duration_str})...", "📝")

    # 1. 检查缓存
    cache_key = get_cache_key(audio_path)
    cached = load_from_cache(cache_key)
    if cached:
        return cached

    # 2. 多进程转录（带超时控制）
    model_names = ["small", "tiny"]
    result_queue = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=_transcribe_worker,
        args=(str(audio_path), "zh", model_names, result_queue)
    )

    t0 = time.time()
    process.start()
    process.join(timeout=TRANSCRIPT_TIMEOUT)

    if process.is_alive():
        log(f"⏰ 转录超时 ({TRANSCRIPT_TIMEOUT}s)，正在终止...", "⚠️")
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
        error(f"转录超时。长音频（>2h）建议使用 tiny 模型或分段处理。")

    # 3. 获取结果
    if not result_queue.empty():
        result = result_queue.get()
        if result["success"]:
            transcript = result["transcript"]
            elapsed = time.time() - t0
            log(f"完成: {elapsed:.0f}s, {result['chars']} 字", "✅")
            # 保存到缓存
            save_to_cache(cache_key, transcript)
            return transcript
        else:
            error(f"转录失败: {result['error']}")
    else:
        error("转录进程异常退出，无输出")

# ── 第五步：保存输出 ──────────────────────────────────
def save_transcript(raw_text: str, info: dict) -> Path:
    """保存原始逐字稿到文件"""
    timestamp = time.strftime("%Y-%m-%d")
    safe_title = re.sub(r'[\\/*?:"<>|]', '', info['title'])[:40]
    filename = f"{timestamp}-{safe_title}.md"
    filepath = OUTPUT_DIR / filename

    content = f"""# {info['title']}

**来源**: {info['source_url']}
**博主**: {info['author']}
**时长**: {info['duration_sec'] // 60}分{info['duration_sec'] % 60}秒
**转录时间**: {time.strftime('%Y-%m-%d %H:%M')}
**方式**: faster-whisper 本地识别

---

{raw_text}
"""

    filepath.write_text(content, encoding='utf-8')
    log(f"已保存: {filepath}", "💾")
    return filepath

# ── 第六步：清理临时文件 ──────────────────────────────
def cleanup(audio_path: Path):
    try:
        audio_path.unlink(missing_ok=True)
    except Exception:
        pass

# ── 本地文件检测 ──────────────────────────────────────
def is_local_audio(user_input: str) -> bool:
    """判断输入是否为本地音频文件路径"""
    p = Path(user_input.strip().strip('"').strip("'"))
    if p.exists() and p.is_file():
        return True
    # 常见音频扩展名
    if re.search(r'\.(mp3|wav|m4a|flac|ogg|opus|aac|wma|webm)$', user_input, re.I):
        return True
    # Windows 绝对路径
    if re.match(r'^[A-Z]:\\', user_input):
        return True
    return False

# ════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════
def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print("""
抖音视频本地转录工具（无需 API）

用法: python douyin_transcribe.py <抖音链接 | 本地音频文件>

示例:
  python douyin_transcribe.py "https://v.douyin.com/xxxxx"
  python douyin_transcribe.py "C:\\Users\\Downloads\\podcast.mp3"
  python douyin_transcribe.py "7.61 复制打开抖音，看看... https://v.douyin.com/xxxxx"

依赖:
  - ffmpeg（抖音模式需要，本地音频可选）
  - faster-whisper（pip install faster-whisper，首次运行自动下载模型）
""")
        sys.exit(0)

    raw_input = sys.argv[1]
    is_local = is_local_audio(raw_input)

    if is_local:
        # ── 本地音频模式 ──────────────────────────────
        log("本地音频转录工具", "🎙️")
        audio_file = Path(raw_input).resolve()
        if not audio_file.exists():
            error(f"文件不存在: {audio_file}")

        log(f"文件: {audio_file.name}", "📁")
        info = {
            'video_id': audio_file.stem,
            'title': audio_file.stem,
            'author': '本地音频',
            'duration_sec': 0,
            'play_url': '',
            'likes': 0, 'comments': 0, 'collects': 0,
            'source_url': str(audio_file),
        }
        raw_text = transcribe_local(audio_file, info)
        save_transcript(raw_text, info)
        log("全部完成！", "🎉")

    else:
        # ── 抖音模式 ──────────────────────────────────
        log("抖音视频本地转录工具", "🎬")

        # 1. 提取视频 ID
        video_id = extract_video_id(raw_input)
        log(f"视频 ID: {video_id}", "📹")

        # 2. 优先尝试 Playwright 模式
        audio_path = None
        info = None

        audio_path = fetch_and_download_with_playwright(video_id)
        if audio_path:
            info = load_playwright_meta(video_id)
            if info:
                log(f"标题: {info['title']}", "📹")
                log(f"博主: {info['author']} | 时长: {info['duration_sec']//60}分{info['duration_sec']%60}秒 | ❤️ {info.get('likes', 0)}", "📹")

        # 3. 回退到 SSR 模式
        if not audio_path or not info:
            log("回退到 SSR / yt-dlp 模式...", "🔄")
            try:
                info = fetch_video_info(video_id)
                log(f"标题: {info['title']}", "📹")
                log(f"博主: {info['author']} | 时长: {info['duration_sec']//60}分{info['duration_sec']%60}秒 | ❤️ {info['likes']}", "📹")
                audio_path = download_audio(info)
            except Exception as e:
                msg = str(e)[:300]
                log(f"SSR 模式也失败: {msg}", "❌")
                if not audio_path:
                    error(f"所有下载方式均失败。请尝试手动下载视频后使用本地模式。\nSSR 错误: {msg}")

        # 4. 本地识别
        raw_text = transcribe_local(audio_path, info)

        # 5. 保存
        save_transcript(raw_text, info)

        # 6. 清理
        if audio_path and audio_path.exists():
            cleanup(audio_path)

        log("全部完成！", "🎉")

# ── Playwright 模式：下载音频 ─────────────────────────
def fetch_and_download_with_playwright(video_id: str):
    """用 Playwright 无头浏览器提取视频并下载音频（优先方案）"""
    pw_script = SCRIPT_DIR.parent / "temp" / "douyin_pw.cjs"
    if not pw_script.exists():
        log("Playwright 脚本不存在，回退到 SSR 模式", "⚠️")
        return None

    try:
        log("Playwright 模式提取视频...", "🎭")
        result = subprocess.run(
            ["node", str(pw_script), video_id],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "HTTPS_PROXY": "", "HTTP_PROXY": ""}
        )
        if result.returncode != 0:
            log(f"Playwright 失败: {result.stderr[-200:]}", "⚠️")
            return None

        audio_path = TEMP_DIR / f"douyin_{video_id}.mp3"
        if audio_path.exists() and audio_path.stat().st_size > 1000:
            size_mb = audio_path.stat().st_size / 1024 / 1024
            log(f"Playwright 成功: {size_mb:.1f} MB", "✅")
            return audio_path
    except Exception as e:
        log(f"Playwright 异常: {e}", "⚠️")
    return None


def load_playwright_meta(video_id: str) -> dict | None:
    """从 Playwright 生成的 JSON 加载元数据"""
    meta_path = TEMP_DIR / f"douyin_{video_id}.json"
    if meta_path.exists():
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            if meta.get('title') and meta.get('playUrl'):
                return {
                    'video_id': video_id,
                    'title': meta.get('title', '未知标题'),
                    'author': meta.get('author', '未知作者'),
                    'duration_sec': meta.get('duration', 0),
                    'play_url': meta.get('playUrl', ''),
                    'likes': meta.get('statistics', {}).get('digg_count', 0),
                    'comments': 0,
                    'collects': 0,
                    'source_url': f"https://www.douyin.com/video/{video_id}",
                }
        except Exception:
            pass
    return None


if __name__ == "__main__":
    main()
