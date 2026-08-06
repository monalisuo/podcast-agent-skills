---
name: podcast
description: 播客转写+深度研究。资产先行、证据分级、预算驱动的播客学习系统。支持 Apple Podcasts、小宇宙、通用 RSS 链路，本地转写，自动生成可追溯的结构化笔记。
argument-hint: "[Apple Podcasts URL / 小宇宙链接 / RSS Feed / 播客名称]"
disable-model-invocation: true
---

# /podcast — 播客转写与深度研究

资产先行的播客学习系统：先把原始材料沉淀为可复用资产包，再按场景模式生成带证据等级的结构化笔记。

## 核心原则

1. **资产先行，笔记后置**：先保存转写、元数据、shownotes 为资产包，再写笔记
2. **证据分级**：每条信息标注来源等级，区分「嘉宾原话」「外部验证」「AI 推断」
3. **预算驱动**：根据时长、信息密度、投资相关度计算推荐笔记长度
4. **复用不返工**：已有资产绝不重复提取，只补真正缺失的部分

## 输入类型

`$ARGUMENTS` 可以是：
- Apple Podcasts URL（如 `https://podcasts.apple.com/cn/podcast/...`）
- 小宇宙播客链接（如 `https://www.xiaoyuzhoufm.com/episode/...`）
- RSS Feed URL（批量扫描最近单集）
- 已有转写文字（直接进入笔记生成阶段）
- 空（处理当前笔记中的转写内容）

---

## 执行步骤

### 第一步：判断输入类型 → 路由场景模式

先判断内容属于哪种**场景模式**，不同模式取证策略不同：

| 模式 | 适用场景 | 证据深度 | 笔记重点 |
|------|---------|---------|---------|
| `guest-interview` | 嘉宾对谈 | 完整转写 + Deep Research | 嘉宾观点、投资方法论、案例复盘 |
| `market-commentary` | 市场分析/宏观评论 | 转写 + 外部数据核验 | 数据事实 vs 个人判断、可操作建议 |
| `methodology-extract` | 投资框架/交易心法 | 转写 + 关联 Vault 笔记 | 提炼可执行规则、对比已有体系 |
| `company-deepdive` | 公司/行业深度分析 | 转写 + 财报/研报补充 | 产业链定位、竞争格局、估值逻辑 |
| `quick-scan` | 快速筛选/判断是否值得深听 | shownotes 分析 | 摘要 + 是否推荐深度学习 |

### 第二步：检查已有资产（避免返工）

处理前先检查是否已有可用资产：

1. **检查转写缓存**：`~/.cache/podcast-agent/transcripts/{audio_hash}.txt`
   - 命中 → 跳过下载和转写，直接进入笔记生成
2. **检查已有笔记**：搜索 Vault 中是否已处理过该播客/单集
3. **检查 shownotes 时间轴**：RSS feed 中已有时 → 复用

### 第三步：提取元数据与音频

按来源类型分别处理：

**Apple Podcasts URL：**
1. 从 URL 提取 podcast ID → `itunes.apple.com/lookup?id={id}&country=cn`
2. 获取 `feedUrl` → 请求 RSS XML
3. 按 episode guid 匹配 → 提取音频 URL、shownotes、发布时间、时长
4. 从 shownotes 解析时间轴（`MM:SS - 主题` 格式）

**小宇宙链接：**
1. 请求页面 HTML → 提取 `media.xyzcdn.net` 音频 URL
2. 提取标题（`__NEXT_DATA__` JSON 或 `<title>`）
3. shownotes 从页面解析

**已有 RSS Feed：**
1. `feedparser` 解析 → 筛选最近 24h/7d 的单集
2. 逐集处理

### 第四步：下载音频并本地转写

使用本地转写管道（复用 `douyin-transcribe` skill 的 faster-whisper）：

```bash
python ".claude/skills/douyin-transcribe/scripts/douyin_transcribe.py" "<音频文件路径>"
```

**缓存机制**：
- 转写结果按 `md5(audio_url)` 缓存在 `~/.cache/podcast-agent/transcripts/`
- 下次同一音频直接命中缓存，秒级返回
- 长音频（>2h）启用 30 分钟超时保护，超时自动终止

**模型策略**：
- 默认：tiny → small → medium 降级尝试
- 中文为主、需要高准确率时：建议 medium 模型
- 2h+ 播客：预计 15-25 分钟（tiny）/ 45-90 分钟（medium）

### 第五步：生成资产包

在 Vault 中创建标准化资产包：

```
📚 学习资源/{播客名}/
├── assets/
│   ├── transcript.md          # 转写逐字稿
│   ├── shownotes.md           # 整理的 shownotes + 时间轴
│   ├── metadata.json          # 元数据（来源/时长/嘉宾/日期）
│   └── note_budget.json       # 笔记预算计算
├── E{编号}-{主题}.md          # 结构化笔记
└── podcast_index.md           # 该播客的索引
```

`metadata.json` 格式：
```json
{
  "source_type": "apple_podcast | xiaoyuzhou | rss",
  "source_url": "...",
  "podcast_name": "高能量",
  "episode_title": "Vol.227 具身新贵与投资女王",
  "hosts": ["李翔", "李丰"],
  "guests": ["徐新", "高继扬"],
  "published": "2026-07-24",
  "duration_seconds": 9156,
  "extraction_date": "2026-08-06"
}
```

`note_budget.json` 由脚本自动计算：
```json
{
  "transcript_chars": 25000,
  "duration_minutes": 152,
  "topic_relevance": "high",
  "investment_signals": 12,
  "recommended_note_chars_min": 3500,
  "recommended_note_chars_max": 5200,
  "writing_guidance": "深度访谈：按主题分章，保留论证链和案例细节，每章补充投资关联"
}
```

### 第六步：生成结构化笔记

使用以下模板，**所有观点标注证据等级**：

```markdown
---
title: {播客名} E{编号}｜{标题}
date: {日期}
tags: [学习资源, 播客, {相关标签}]
source: {URL}
evidence_grading: true
---

# {标题}

## 基本信息
| 项目 | 内容 |
|------|------|
| 播客 | {名称} |
| 主持人 | {主持人} |
| 嘉宾 | {嘉宾} |
| 日期 | {发布日期} |
| 时长 | {时长} |

## 本期摘要
{200-300字摘要，概括核心讨论}

## 核心观点

> 证据等级说明：
> 🟢 嘉宾原话/数据 → 事实主干 | 🟡 外部验证 → 增强可信度
> 🟠 主持人判断 → 观点参考 | 🔴 Claude 理解 → 需标注为推断

### 1. {观点标题}
- **内容**（🟢 嘉宾原话）：节目中说了什么
- **数据/案例**（🟡 外部验证）：相关数据点，联网核验结果
- **我的理解**（🔴 需验证）：用自己的话重述并延伸
- **投资关联**：对 ETF/半导体投资的启发

### 2. {观点标题}
...

## 关键概念速览
| 概念 | 解释 | 证据来源 | 投资关联 |
|------|------|---------|---------|
| {概念} | 通俗定义 | 🟢 嘉宾定义 / 🟡 外部补充 | 投资意义 |

## 深度研究（Deep Research）
{对 3-5 个核心概念联网搜索补充}

### 📖 {概念A}
- **嘉宾说了什么**（🟢）：...
- **外部验证**（🟡）：联网搜索结果
- **投资意义**（🔴）：综合判断

## 时间轴导航
| 时间 | 主题 | 关键内容 |
|------|------|---------|

## 原文摘录
> 🟢 "值得记下来的原话"
> 🟠 "主持人的判断性表述"

## 投资方法论提取
{如果播客涉及投资方法论，单独提炼}
- **规则**：可执行的交易/研究规则
- **对应已有体系**：[[关联Vault笔记]]

## 关联 Vault 笔记
- [[已有笔记]] — 关联说明

## 行动清单
- [ ] 基于播客内容可做的具体投资操作
```

### 第七步：资产归档

1. 转写稿 → `📚 学习资源/{播客名}/assets/transcript.md`
2. 元数据 → `📚 学习资源/{播客名}/assets/metadata.json`
3. 笔记预算 → `📚 学习资源/{播客名}/assets/note_budget.json`
4. 结构化笔记 → `📚 学习资源/{播客名}/E{编号}-{主题}.md`
5. 更新 `📚 学习资源/{播客名}/podcast_index.md` 索引

---

## 证据等级系统

所有笔记中的信息必须标注证据来源等级：

| 等级 | 标记 | 含义 | 示例 |
|------|------|------|------|
| L1 事实 | 🟢 | 嘉宾原话/播客中直接陈述的数据 | "徐新说刘强东要200万，她给了1000万" |
| L2 验证 | 🟡 | 外部来源交叉验证的事实 | 联网查到的京东融资历史 |
| L3 观点 | 🟠 | 嘉宾/主持人的判断性表述 | "迭代是唯一的护城河" |
| L4 推断 | 🔴 | Claude 基于播客内容的延伸理解 | "这个方法论可以应用于..." |

> ⚠️ 投资相关的高风险结论（如"应该买入XX"）必须有 🟢 或 🟡 级别证据支撑，不能仅基于 🔴 推断。

---

## 笔记预算算法

转换完成后自动计算推荐笔记长度：

```
base = 500 + duration_min × 35 + transcript_chars × 0.06 + investment_signals × 80
quality_multiplier = 1.0 + (guest_authority + topic_relevance) / 2
target_min = base × quality_multiplier
```

其中：
- `investment_signals`：节目中涉及的具体投资概念/方法论/案例数量
- `guest_authority`：嘉宾权威度（0-1，如徐新≈0.95）
- `topic_relevance`：与用户投资体系的关联度（0-1，ETF/半导体直接相关≈0.9）

---

## 与已有技能的配合

- `/capture` — 处理单篇内容捕获，`/podcast` 专门处理播客
- `/learn` — 对播客中单个概念做深入学习
- `/connect` — 发现笔记间的隐藏关联
- `/organize` — 整理收件箱中的播客相关临时内容
- `/douyin-transcribe` — 本地音频转写（共享 faster-whisper）

---

## 故障排查

### 转写超时
- 默认 30 分钟超时保护
- 长播客（>2h）优先用 tiny 模型
- 超时后保留已完成部分，不丢数据

### 音频下载失败
- 检查 URL 是否仍有效
- 部分播客有限地区访问限制
- 尝试换用 RSS Feed 直接提取音频链接

### 转写质量差
- 升级模型：tiny → small → medium
- 中文播客可尝试 Qwen3-ASR（需额外安装）
- 多人对话且口音重时，质量下降属正常
