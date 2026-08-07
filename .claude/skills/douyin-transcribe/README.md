# 抖音视频智能助手 🎬🧠

Claude Code Skill，本地转录抖音视频——无需任何 API Key。

> SkillsMP: [douyin-transcribe](https://skillsmp.com/creators/xianmingyao/openclaw-cayson/skills-douyin-transcribe-skill)

## ✨ 功能

- 🎬 抖音链接 → 全本地转录（无需 API）
- 📝 五种模式：默认总结 / 逐字稿 / 详细总结 / 归档 / 讨论
- 💰 完全免费，离线可用
- 🎯 中文优化

## 🚀 安装

```bash
# 1. 安装 Python 依赖
pip install faster-whisper

# 2. 安装 Playwright（绕过抖音反爬）
npm install playwright
npx playwright install chromium

# 3. GPU 加速（可选，NVIDIA 显卡）
pip install nvidia-cublas-cu12

# 4. ffmpeg（通常已预装）

# 5. 完成！无需 API Key
```

## 📋 依赖

| 依赖 | 费用 | 用途 |
|------|------|------|
| Python 3 | 免费 | 运行脚本 |
| Node.js + Playwright | 免费 | 绕过抖音反爬 |
| ffmpeg | 免费 | 音频下载 |
| faster-whisper | 免费 | 本地语音识别 |
| nvidia-cublas-cu12 | 免费（可选） | GPU 加速（~8x） |

## 🔧 工作原理

```
抖音链接 → 🎭 Playwright无头浏览器提取 → ffmpeg下载音频（~4MB/10分钟）
         → faster-whisper 本地识别（GPU优先，CPU回退）
         → ✂️ VAD自动分段，逐句分行 → AI 智能处理（总结/讨论/归档）
```
