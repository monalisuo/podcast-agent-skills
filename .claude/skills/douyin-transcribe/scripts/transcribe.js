#!/usr/bin/env node
/**
 * 抖音视频转文字脚本
 * 用法: node transcribe.js <抖音链接或本地文件路径> [--output <dir>] [--model <model>]
 */

const { execSync, execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');

// 加载 .env 文件
function loadEnvFile() {
  const envPath = path.join(__dirname, '..', '.env');
  if (fs.existsSync(envPath)) {
    const envContent = fs.readFileSync(envPath, 'utf-8');
    envContent.split('\n').forEach(line => {
      const match = line.match(/^([A-Z_]+)=(.*)$/);
      if (match && !process.env[match[1]]) {
        process.env[match[1]] = match[2].replace(/^["']|["']$/g, '');
      }
    });
  }
}
loadEnvFile();

// 自动检测命令路径（跨平台）
function findCommand(cmd) {
  // 1. 先试 which/where
  try {
    const which = process.platform === 'win32' ? 'where.exe' : 'which';
    const result = execSync(`${which} ${cmd}`, { stdio: 'pipe', encoding: 'utf-8' }).trim().split('\n')[0].trim();
    if (result && !result.includes('not found') && !result.includes('Could not find')) return result;
  } catch (e) {}

  // 2. Windows 常见安装路径
  if (process.platform === 'win32') {
    const windowsPaths = [
      `C:\\ffmpeg\\bin\\${cmd}.exe`,
      `C:\\Program Files\\ffmpeg\\bin\\${cmd}.exe`,
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'yt-dlp', `${cmd}.exe`),
      path.join(process.env.LOCALAPPDATA || '', 'Programs', cmd, `${cmd}.exe`),
      path.join(process.env.USERPROFILE || '', 'scoop', 'shims', `${cmd}.exe`),
      path.join(process.env.USERPROFILE || '', 'AppData', 'Local', 'Microsoft', 'WinGet', 'Links', `${cmd}.exe`),
    ];
    for (const p of windowsPaths) {
      if (fs.existsSync(p)) return p;
    }
  }

  // 3. Mac/Linux 常见路径
  const unixPaths = [
    `/usr/local/bin/${cmd}`,
    `/usr/bin/${cmd}`,
    `/opt/homebrew/bin/${cmd}`,
  ];
  for (const p of unixPaths) {
    if (fs.existsSync(p)) return p;
  }

  return cmd; // fallback，让后续报错处理
}

// 配置
const CONFIG = {
  sttProvider: process.env.STT_PROVIDER || 'groq',
  whisperModel: process.env.WHISPER_MODEL || 'whisper-large-v3',
  outputDir: process.env.OUTPUT_DIR || path.join(__dirname, '..', 'douyin-transcripts'),
  tempDir: process.env.TEMP_DIR || path.join(__dirname, '..', 'temp'),
  groqApiKey: process.env.GROQ_API_KEY,
  openaiApiKey: process.env.OPENAI_API_KEY,
  ffmpegPath: process.env.FFMPEG_PATH || findCommand('ffmpeg'),
  ffprobePath: process.env.FFPROBE_PATH || findCommand('ffprobe'),
  ytdlpPath: process.env.YTDLP_PATH || findCommand('yt-dlp')
};

// 颜色输出
const colors = {
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  cyan: '\x1b[36m',
  reset: '\x1b[0m'
};

function log(msg, color = 'reset') {
  console.log(`${colors[color]}${msg}${colors.reset}`);
}

function error(msg) {
  console.error(`${colors.red}❌ ${msg}${colors.reset}`);
  process.exit(1);
}

function getCommandPath(cmd) {
  if (cmd === 'ffmpeg') return CONFIG.ffmpegPath;
  if (cmd === 'ffprobe') return CONFIG.ffprobePath;
  if (cmd === 'yt-dlp') return CONFIG.ytdlpPath;
  return cmd;
}

function runCommand(cmd, args, options = {}) {
  const fullPath = getCommandPath(cmd);
  const executable = fs.existsSync(fullPath) ? fullPath : cmd;
  return execSync(`"${executable}" ${args}`, { stdio: 'pipe', ...options });
}

// 检查依赖
function checkDependencies(isLocalFile = false) {
  log('🔍 检查依赖...', 'cyan');

  try {
    runCommand('ffmpeg', '-version');
    log('  ✓ ffmpeg 已安装', 'green');
  } catch (e) {
    error(`ffmpeg 未安装或未找到\n路径: ${CONFIG.ffmpegPath}\n请先安装 ffmpeg: https://ffmpeg.org/download.html`);
  }

  if (!isLocalFile) {
    try {
      runCommand('yt-dlp', '--version');
      log('  ✓ yt-dlp 已安装 (备选下载方式)', 'green');
    } catch (e) {
      log('  ℹ yt-dlp 未安装 (可选，本地文件模式不需要)', 'yellow');
    }
  }

  if (CONFIG.sttProvider === 'groq') {
    if (!CONFIG.groqApiKey) {
      error('未设置 Groq API Key，请在 .env 文件中配置 GROQ_API_KEY');
    }
    log(`  ✓ Groq API Key 已配置 (模型: ${CONFIG.whisperModel})`, 'green');
  } else {
    if (!CONFIG.openaiApiKey || CONFIG.openaiApiKey === 'sk-your-api-key-here') {
      error('未设置 OpenAI API Key，请在 .env 文件中配置 OPENAI_API_KEY');
    }
    log(`  ✓ OpenAI API Key 已配置 (模型: ${CONFIG.whisperModel})`, 'green');
  }
}

// 检查是否是本地文件
function checkIsLocalFile(input) {
  if (/^https?:\/\//.test(input)) return false;
  if (/^[a-zA-Z]:\\/.test(input)) return true;
  if (input.startsWith('/') && !input.startsWith('//')) return true;
  if (input.startsWith('./') || input.startsWith('../')) return true;
  if (/\.(mp4|mov|avi|mkv|webm|flv|m4a|mp3|wav)$/i.test(input)) return true;
  if ((input.includes('\\') || (input.includes('/') && !input.includes('://'))) && !input.includes('douyin.com')) return true;
  return false;
}

// 准备媒体文件
async function prepareMedia(url) {
  if (checkIsLocalFile(url)) {
    const resolvedPath = path.resolve(url);
    if (!fs.existsSync(resolvedPath)) {
      error(`本地文件不存在: ${resolvedPath}`);
    }

    log(`\n📁 检测到本地文件，跳过下载...`, 'cyan');
    const stats = fs.statSync(resolvedPath);
    const sizeMB = (stats.size / 1024 / 1024).toFixed(2);
    log(`  ✓ 文件大小: ${sizeMB} MB`, 'green');

    return {
      videoPath: resolvedPath,
      audioPath: null,
      title: path.basename(resolvedPath, path.extname(resolvedPath)),
      author: '本地文件',
      isLocal: true,
      directAudio: false
    };
  }

  // 抖音链接：尝试用环境变量中的音频 URL
  if (url.includes('douyin.com')) {
    try {
      return await browserExtract(url);
    } catch (e) {
      log(`  ⚠️ 浏览器提取失败: ${e.message}`, 'yellow');
      log(`  回退到 yt-dlp...`, 'yellow');
    }
  }

  // Fallback: yt-dlp
  return await ytdlpDownload(url);
}

// 方案 A：通过环境变量传入的音频 URL
async function browserExtract(url) {
  log(`\n🌐 提取音频信息...`, 'cyan');

  const tempDir = path.resolve(CONFIG.tempDir);
  if (!fs.existsSync(tempDir)) {
    fs.mkdirSync(tempDir, { recursive: true });
  }

  if (process.env.DOUYIN_AUDIO_URL) {
    const audioUrl = process.env.DOUYIN_AUDIO_URL;
    const title = process.env.DOUYIN_TITLE || '未知标题';
    const author = process.env.DOUYIN_AUTHOR || '未知作者';

    log(`  标题: ${title}`, 'cyan');
    log(`  作者: ${author}`, 'cyan');

    const timestamp = Date.now();
    const audioPath = path.join(tempDir, `audio_${timestamp}.mp3`);

    log(`  📥 下载音频流...`);
    try {
      const ffmpegPath = fs.existsSync(CONFIG.ffmpegPath) ? CONFIG.ffmpegPath : 'ffmpeg';
      execFileSync(ffmpegPath, [
        '-y',
        '-headers', 'Referer: https://www.douyin.com/\r\n',
        '-i', audioUrl,
        '-vn', '-ar', '16000', '-ac', '1',
        '-c:a', 'libmp3lame', '-q:a', '2',
        audioPath
      ], { stdio: 'pipe', timeout: 60000 });
    } catch (e) {
      if (!fs.existsSync(audioPath) || fs.statSync(audioPath).size < 1000) {
        throw new Error('ffmpeg 音频下载失败: ' + (e.stderr ? e.stderr.toString().slice(-200) : e.message));
      }
    }

    if (!fs.existsSync(audioPath) || fs.statSync(audioPath).size < 1000) {
      throw new Error('音频文件下载失败或为空');
    }

    const sizeMB = (fs.statSync(audioPath).size / 1024 / 1024).toFixed(2);

    let duration = 0;
    try {
      const durationOutput = runCommand('ffprobe', `-v error -show_entries format=duration -of csv=p=0 "${audioPath}"`, { encoding: 'utf-8' });
      duration = parseFloat(durationOutput.trim());
    } catch (e) {}

    const minutes = Math.floor(duration / 60);
    const seconds = Math.floor(duration % 60);
    log(`  ✓ 音频就绪 (${minutes}分${seconds}秒, ${sizeMB} MB)`, 'green');

    return {
      videoPath: null,
      audioPath,
      title,
      author,
      isLocal: false,
      directAudio: true,
      duration
    };
  }

  throw new Error('未设置 DOUYIN_AUDIO_URL 环境变量，请通过浏览器提取或使用 yt-dlp');
}

// 方案 B：yt-dlp 下载
async function ytdlpDownload(url) {
  log(`\n📥 使用 yt-dlp 下载视频...`, 'cyan');

  const tempDir = path.resolve(CONFIG.tempDir);
  if (!fs.existsSync(tempDir)) {
    fs.mkdirSync(tempDir, { recursive: true });
  }

  const timestamp = Date.now();
  const videoPath = path.join(tempDir, `video_${timestamp}.mp4`);

  const cookiesPath = path.join(__dirname, '..', 'temp', 'douyin-cookies.txt');
  let cookiesArg = '';
  if (fs.existsSync(cookiesPath)) {
    log('  🍪 使用 cookies 文件', 'cyan');
    cookiesArg = `--cookies "${cookiesPath}"`;
  }

  try {
    let videoInfo = {};
    try {
      const infoJson = runCommand('yt-dlp', `${cookiesArg} --dump-json "${url}"`, { encoding: 'utf-8', timeout: 30000 });
      videoInfo = JSON.parse(infoJson);
    } catch (e) {
      log('  ⚠️ 无法获取视频信息，继续下载...', 'yellow');
    }

    runCommand('yt-dlp', `${cookiesArg} -o "${videoPath}" "${url}"`, { timeout: 120000 });

    if (!fs.existsSync(videoPath)) {
      const files = fs.readdirSync(tempDir);
      const videoFile = files.find(f => f.startsWith(`video_${timestamp}`));
      if (videoFile) {
        return {
          videoPath: path.join(tempDir, videoFile),
          audioPath: null,
          title: videoInfo.title || '未知标题',
          author: videoInfo.uploader || '未知作者',
          isLocal: false,
          directAudio: false
        };
      }
      error('视频下载失败');
    }

    log(`  ✓ 下载完成`, 'green');
    return {
      videoPath,
      audioPath: null,
      title: videoInfo.title || '未知标题',
      author: videoInfo.uploader || '未知作者',
      isLocal: false,
      directAudio: false
    };
  } catch (e) {
    error(`下载失败: ${e.message}\n\n💡 解决方案:\n1. 手动下载视频文件: node transcribe.js "C:\\path\\to\\video.mp4"\n2. 安装 yt-dlp 或配置 cookies`);
  }
}

// 提取音频
function extractAudio(videoPath) {
  log(`\n🎵 提取音频...`, 'cyan');

  const audioPath = videoPath.replace(/\.[^.]+$/, '.mp3');

  try {
    runCommand('ffmpeg', `-i "${videoPath}" -vn -ar 16000 -ac 1 -c:a libmp3lame -q:a 2 "${audioPath}" -y`);

    if (!fs.existsSync(audioPath)) {
      error('音频提取失败');
    }

    const durationOutput = runCommand('ffprobe', `-v error -show_entries format=duration -of csv=p=0 "${audioPath}"`, { encoding: 'utf-8' });
    const duration = parseFloat(durationOutput.trim());
    const minutes = Math.floor(duration / 60);
    const seconds = Math.floor(duration % 60);

    log(`  ✓ 音频提取完成 (${minutes}分${seconds}秒)`, 'green');
    return { audioPath, duration };
  } catch (e) {
    error(`音频提取失败: ${e.message}`);
  }
}

// 调用 Whisper API
async function transcribeAudio(audioPath) {
  const provider = CONFIG.sttProvider === 'groq' ? 'Groq' : 'OpenAI';
  log(`\n📝 语音识别中... (${provider} ${CONFIG.whisperModel})`, 'cyan');

  const fileSize = fs.statSync(audioPath).size;
  const fileSizeMB = (fileSize / 1024 / 1024).toFixed(2);
  log(`  音频大小: ${fileSizeMB} MB`);

  if (fileSize > 25 * 1024 * 1024) {
    error(`音频文件过大 (${fileSizeMB} MB)，API 限制 25MB。请用更短的视频。`);
  }

  const isGroq = CONFIG.sttProvider === 'groq';
  const apiKey = isGroq ? CONFIG.groqApiKey : CONFIG.openaiApiKey;
  const hostname = isGroq ? 'api.groq.com' : 'api.openai.com';
  const apiPath = isGroq ? '/openai/v1/audio/transcriptions' : '/v1/audio/transcriptions';
  const model = isGroq ? CONFIG.whisperModel : 'whisper-1';

  return new Promise((resolve, reject) => {
    const audioData = fs.readFileSync(audioPath);
    const boundary = '----FormBoundary' + Math.random().toString(36).substring(2);

    const parts = [];

    parts.push(Buffer.from(
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="file"; filename="audio.mp3"\r\n` +
      `Content-Type: audio/mpeg\r\n\r\n`
    ));
    parts.push(audioData);

    parts.push(Buffer.from(
      `\r\n--${boundary}\r\n` +
      `Content-Disposition: form-data; name="model"\r\n\r\n` +
      `${model}\r\n`
    ));

    parts.push(Buffer.from(
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="language"\r\n\r\n` +
      `zh\r\n`
    ));

    parts.push(Buffer.from(`--${boundary}--\r\n`));

    const body = Buffer.concat(parts);

    const startTime = Date.now();

    const options = {
      hostname,
      path: apiPath,
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': `multipart/form-data; boundary=${boundary}`,
        'Content-Length': body.length
      }
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        try {
          const result = JSON.parse(data);
          if (result.error) {
            reject(new Error(`${provider} API 错误: ${result.error.message}`));
          } else {
            log(`  ✓ 识别完成 (耗时 ${elapsed}s)`, 'green');
            resolve(result.text);
          }
        } catch (e) {
          reject(new Error('API 返回解析失败: ' + data.substring(0, 500)));
        }
      });
    });

    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// 用 LLM 加标点分段
async function formatTranscript(rawText) {
  log(`\n✍️  添加标点和分段...`, 'cyan');

  const apiKey = CONFIG.groqApiKey;
  if (!apiKey) {
    log('  ⚠️ 未配置 Groq Key，跳过格式化', 'yellow');
    return rawText;
  }

  const startTime = Date.now();

  const CHUNK_SIZE = 2000;
  const chunks = [];
  for (let i = 0; i < rawText.length; i += CHUNK_SIZE) {
    chunks.push(rawText.slice(i, i + CHUNK_SIZE));
  }

  const formatted = [];
  for (let i = 0; i < chunks.length; i++) {
    if (chunks.length > 1) {
      log(`  处理第 ${i + 1}/${chunks.length} 段...`);
    }
    const result = await callGroqLLM(apiKey, chunks[i]);
    formatted.push(result);
  }

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  log(`  ✓ 格式化完成 (耗时 ${elapsed}s)`, 'green');
  return formatted.join('\n\n');
}

function callGroqLLM(apiKey, text) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      model: 'llama-3.3-70b-versatile',
      messages: [
        {
          role: 'system',
          content: '你是一个中文文本格式化助手。你的任务是给没有标点的语音转录文本添加标点符号和合理分段。\n\n规则：\n1. 添加中文标点（，。！？、：""）\n2. 按语义和话题切换分段（每段之间空一行）\n3. 不要改变任何原文内容，不要增删字词\n4. 不要添加标题、总结或任何额外内容\n5. 只输出格式化后的文本，不要任何解释'
        },
        {
          role: 'user',
          content: text
        }
      ],
      temperature: 0,
      max_tokens: 4096
    });

    const options = {
      hostname: 'api.groq.com',
      path: '/openai/v1/chat/completions',
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const result = JSON.parse(data);
          if (result.error) {
            log(`  ⚠️ LLM 格式化失败: ${result.error.message}，使用原始文本`, 'yellow');
            resolve(text);
          } else {
            resolve(result.choices[0].message.content.trim());
          }
        } catch (e) {
          log('  ⚠️ LLM 返回解析失败，使用原始文本', 'yellow');
          resolve(text);
        }
      });
    });

    req.on('error', () => {
      log('  ⚠️ LLM 请求失败，使用原始文本', 'yellow');
      resolve(text);
    });

    req.write(body);
    req.end();
  });
}

// 保存到 Markdown
function saveTranscript(source, info, transcript) {
  log(`\n💾 保存转录结果...`, 'cyan');

  const outputDir = path.resolve(CONFIG.outputDir);
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const filename = `${timestamp}-douyin.md`;
  const filepath = path.join(outputDir, filename);

  const sourceType = info.isLocal ? '本地文件' : '来源';

  const content = `# 抖音视频转录

**${sourceType}**: ${source}
**转录时间**: ${new Date().toLocaleString('zh-CN')}
**视频标题**: ${info.title}
**博主**: ${info.author}
**Whisper 模型**: ${CONFIG.whisperModel}

---

${transcript}
`;

  fs.writeFileSync(filepath, content, 'utf-8');
  log(`  ✓ 已保存到: ${filepath}`, 'green');
  return filepath;
}

// 清理临时文件
function cleanup(videoPath, audioPath, isLocal) {
  log(`\n🧹 清理临时文件...`, 'cyan');

  try {
    if (!isLocal && videoPath && fs.existsSync(videoPath)) {
      fs.unlinkSync(videoPath);
    }
    if (audioPath && fs.existsSync(audioPath)) {
      fs.unlinkSync(audioPath);
    }
    log('  ✓ 清理完成', 'green');
  } catch (e) {
    log('  ⚠️ 清理失败 (可忽略)', 'yellow');
  }
}

// 主函数
async function main() {
  const args = process.argv.slice(2);

  if (args.length === 0 || args[0].startsWith('--')) {
    console.log(`
用法: node transcribe.js <抖音链接或本地文件> [选项]

选项:
  --output <目录>    输出目录 (默认: ./douyin-transcripts)
  --model <模型>     Whisper 模型 (默认: whisper-large-v3)

示例:
  # 下载抖音视频并转录
  node transcribe.js "https://v.douyin.com/xxxxx"

  # 转录本地视频文件
  node transcribe.js "C:\\Users\\Videos\\douyin.mp4"

  # 指定输出目录和模型
  node transcribe.js "https://v.douyin.com/xxxxx" --output ./my-notes

💡 提示:
  如果抖音下载失败，可以手动下载视频后用本地文件路径运行
  音频提取需要 ffmpeg，语音识别需要 Groq API Key（免费）
`);
    process.exit(1);
  }

  const input = args[0];
  const inputIsLocal = checkIsLocalFile(input);

  for (let i = 1; i < args.length; i++) {
    if (args[i] === '--output' && args[i + 1]) {
      CONFIG.outputDir = args[i + 1];
      i++;
    } else if (args[i] === '--model' && args[i + 1]) {
      CONFIG.whisperModel = args[i + 1];
      i++;
    }
  }

  if (!inputIsLocal && !input.includes('douyin.com')) {
    error('请输入有效的抖音链接或本地视频文件路径');
  }

  log('🦞 抖音视频转文字工具\n', 'cyan');
  log(`${inputIsLocal ? '文件' : '链接'}: ${input}`);
  log(`输出目录: ${path.resolve(CONFIG.outputDir)}`);
  log(`Whisper 模型: ${CONFIG.whisperModel}\n`);

  try {
    checkDependencies(inputIsLocal);

    const media = await prepareMedia(input);

    let audioPath, duration;
    if (media.directAudio) {
      audioPath = media.audioPath;
      duration = media.duration || 0;
    } else {
      const extracted = extractAudio(media.videoPath);
      audioPath = extracted.audioPath;
      duration = extracted.duration;
    }

    const rawTranscript = await transcribeAudio(audioPath);

    const transcript = await formatTranscript(rawTranscript);

    const savedPath = saveTranscript(input, { title: media.title, author: media.author, isLocal: media.isLocal }, transcript);

    cleanup(media.videoPath, audioPath, media.isLocal);

    log(`\n✅ 转录完成!`, 'green');
    log(`\n📄 文件: ${savedPath}`);
    log(`📝 字数: ${transcript.length} 字`);

    const preview = transcript.slice(0, 500);
    log(`\n--- 内容预览 ---\n${preview}${transcript.length > 500 ? '...' : ''}\n`, 'cyan');

  } catch (e) {
    error(e.message);
  }
}

main();
