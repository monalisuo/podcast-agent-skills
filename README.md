# Podcast Agent Skills

面向 Claude Code / AI Agent 的播客学习系统。资产先行、证据分级、预算驱动的结构化笔记生成。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## 包含的 Skills

### 🎙️ `/podcast` — 播客转写与深度研究

将播客从音频变为可追溯的结构化学习笔记。

**能力**：
- Apple Podcasts / 小宇宙 / RSS Feed 多源提取
- 本地 faster-whisper 转写（无需 API Key）
- 5 种场景模式路由（嘉宾访谈/市场评论/方法论提取/公司深度/快速筛选）
- 4 级证据等级系统（🟢嘉宾原话 / 🟡外部验证 / 🟠主持人判断 / 🔴AI推断）
- 数学公式驱动的笔记预算计算
- 资产包管理（transcript + metadata + shownotes + budget）
- 转录缓存 + 30 分钟超时保护

### 🎬 `/douyin-transcribe` — 本地音频转写

完全离线的音频转写管道，支持 CPU/GPU。

**能力**：
- 抖音链接 → 自动提取音频 → 本地转写
- 本地音频文件直接转写（播客/录音等）
- faster-whisper 本地识别（tiny/small/medium）
- **GPU 加速**（RTX 3060: 18x 实时，99 分钟音频仅需 5.5 分钟）
- **并行分块转录**（长音频切块多进程，CPU 模式 4-8x 提速）
- **实时进度条**（可视化转写进度）
- MD5 转录缓存（避免重复处理）
- 多进程超时保护

## 安装

```bash
# 1. 安装依赖
pip install faster-whisper
# ffmpeg 需单独安装

# 2. 复制 skill 到 Claude Code
cp -r podcast ~/.claude/skills/
cp -r douyin-transcribe ~/.claude/skills/
```

## 使用

```
/podcast https://podcasts.apple.com/cn/podcast/...
/douyin-transcribe https://v.douyin.com/xxxxx
```

## 核心方法论

### 证据等级系统

所有笔记中的信息标注来源等级：

| 等级 | 标记 | 含义 |
|------|------|------|
| L1 | 🟢 | 嘉宾原话/数据 — 事实主干 |
| L2 | 🟡 | 外部验证 — 增强可信度 |
| L3 | 🟠 | 主持人判断 — 观点参考 |
| L4 | 🔴 | AI 理解 — 需标注为推断 |

### 笔记预算算法

```
base = 500 + duration_min × 35 + transcript_chars × 0.06 + signals × 80
target = base × quality_multiplier
```

基于时长、信息密度、投资信号数、嘉宾权威度自动计算推荐笔记长度。

## 目录结构

```
podcast/
├── SKILL.md                          # Skill 定义 + 完整工作流
└── scripts/
    ├── compute_note_budget.py        # 笔记预算计算器
    └── inspect_podcast_state.py      # 资产状态检查器

douyin-transcribe/
├── SKILL.md                          # Skill 定义
├── .env.example                      # 环境配置模板
└── scripts/
    ├── douyin_transcribe.py          # 本地音频转写管道
    └── parallel_transcribe.py        # 并行分块转写（GPU/CPU）
```

## 设计参考

- [OpenClaw Podcast Summarizer](https://github.com/happynocode/openclaw-skill-podcast) — 转录缓存 + 超时控制
- [DyNote](https://github.com/Rimagination/dy-note) — 资产先行 + 证据分级 + 笔记预算

## License

MIT
