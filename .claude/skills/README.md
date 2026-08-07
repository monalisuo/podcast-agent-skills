# podcast-agent-skills

Claude Code / Claudian skills for investment learning and content capture.

## Skills

### douyin-transcribe

转录抖音视频为逐字稿，支持两种下载方式：

**工作流程：**
```
抖音链接 → 🎭 Playwright 无头浏览器提取 → 🎵 ffmpeg 下载音频 → 📝 faster-whisper 本地识别 → 📄 分段逐字稿
```

**特性：**
- 🎭 **Playwright 优先**：绕过抖音反爬，提取视频播放地址（回退到 SSR/yt-dlp）
- 📝 **small 模型优先**：~500MB 已缓存，无需重复下载
- ✂️ **VAD 自动分段**：按语音停顿逐句分行，排版好读
- 🔒 **完全本地**：无需 API Key，音频和模型都在本地处理

**依赖：**
- Node.js + Playwright
- Python 3 + faster-whisper
- ffmpeg

**用法：**
```bash
cd .claude/skills/douyin-transcribe
python scripts/douyin_transcribe.py "https://v.douyin.com/xxxxx"
```
