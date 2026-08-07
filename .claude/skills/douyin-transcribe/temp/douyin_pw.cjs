// Playwright-based Douyin video extractor (CommonJS)
const { chromium } = require('playwright');
const { execSync } = require('child_process');
const { writeFileSync } = require('fs');
const path = require('path');

const VIDEO_ID = process.argv[2] || '7670900131406810418';
const DOUYIN_URL = `https://www.douyin.com/video/${VIDEO_ID}`;

async function main() {
  console.log(`🎬 启动 Playwright 提取视频: ${VIDEO_ID}`);

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    viewport: { width: 1920, height: 1080 }
  });

  const page = await context.newPage();

  // Intercept API responses to capture video data
  let videoData = null;

  page.on('response', async (response) => {
    const url = response.url();
    if (url.includes('aweme/v1/web/aweme/detail') && url.includes(VIDEO_ID)) {
      try {
        const json = await response.json();
        const detail = json?.aweme_detail;
        if (detail) {
          const video = detail.video || {};
          const playAddr = video.play_addr || video.play_addr_h264 || {};
          const urlList = playAddr.url_list || [];

          // Get all quality options
          const bitRates = (video.bit_rate || []).filter(b => b.play_addr?.url_list?.[0]);

          videoData = {
            title: detail.desc || '未知标题',
            author: (detail.author || {}).nickname || '未知作者',
            duration: Math.floor((video.duration || 0) / 1000),
            playUrl: urlList[0] || (bitRates[bitRates.length - 1]?.play_addr?.url_list?.[0]),
            allPlayUrls: bitRates.map(b => ({
              quality: b.gear_name || 'unknown',
              url: b.play_addr.url_list[0]
            })),
            statistics: detail.statistics || {},
            createTime: detail.create_time || 0
          };
          console.log(`✅ 拦截到视频数据: ${videoData.title}`);
          console.log(`   作者: ${videoData.author}`);
          console.log(`   时长: ${videoData.duration}秒`);
          console.log(`   质量选项: ${videoData.allPlayUrls.length}个`);
        }
      } catch (e) {
        // Ignore parse errors
      }
    }
  });

  // Navigate and wait for video data
  console.log('🌐 加载页面...');
  try {
    await page.goto(DOUYIN_URL, { waitUntil: 'networkidle', timeout: 30000 });
    console.log('⏳ 等待 API 数据...');
    await page.waitForTimeout(5000);
  } catch (e) {
    console.log(`⚠️ 页面加载超时，尝试获取已拦截数据...`);
  }

  // If we didn't get data from interception, try from page
  if (!videoData || !videoData.playUrl) {
    console.log('🔄 尝试从页面提取数据...');
    try {
      videoData = await page.evaluate(() => {
        // Try to find any embedded video data in script tags
        const scripts = document.querySelectorAll('script');
        for (const s of scripts) {
          const text = s.textContent || '';
          if (text.includes('aweme_detail')) {
            // Try to extract the JSON
            const idx = text.indexOf('aweme_detail');
            const slice = text.substring(idx - 5, idx + 5000);
            const match = slice.match(/\{[\s\S]*?desc[\s\S]*?nickname[\s\S]*?\}/);
            if (match) {
              try {
                const d = JSON.parse(match[0]);
                return {
                  title: d.desc || '未知标题',
                  author: (d.author || {}).nickname || '未知作者',
                  duration: Math.floor(((d.video || {}).duration || 0) / 1000),
                  playUrl: ((d.video || {}).play_addr || {}).url_list?.[0] || '',
                };
              } catch(e) {}
            }
          }
        }
        return null;
      });
    } catch (e) {
      console.log(`⚠️ 页面提取失败: ${e.message}`);
    }
  }

  await browser.close();

  if (!videoData || !videoData.playUrl) {
    console.error('❌ 未能提取视频播放地址');
    console.log('Raw videoData keys:', videoData ? Object.keys(videoData) : 'null');
    process.exit(1);
  }

  console.log(`📹 标题: ${videoData.title}`);
  console.log(`👤 作者: ${videoData.author}`);
  console.log(`⏱️ 时长: ${Math.floor(videoData.duration / 60)}分${videoData.duration % 60}秒`);

  // Pick best quality URL
  let playUrl = videoData.playUrl;
  if (videoData.allPlayUrls && videoData.allPlayUrls.length > 0) {
    // Last one is usually highest quality
    const best = videoData.allPlayUrls[videoData.allPlayUrls.length - 1];
    console.log(`📺 选用画质: ${best.quality}`);
  }
  console.log(`🔗 播放地址: ${(playUrl || '').substring(0, 100)}...`);

  // Download audio with ffmpeg
  const audioPath = path.join(__dirname, `douyin_${VIDEO_ID}.mp3`);
  const ffmpeg = 'C:\\ffmpeg\\bin\\ffmpeg.exe';

  console.log(`🎵 下载音频...`);
  try {
    // Replace https with http for ffmpeg compatibility if needed
    const url = playUrl;
    execSync(`"${ffmpeg}" -y -user_agent "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36" -headers "Referer: https://www.douyin.com/" -i "${url}" -vn -ar 16000 -ac 1 -c:a libmp3lame -q:a 2 "${audioPath}"`, {
      stdio: 'inherit',
      timeout: 120000
    });
    console.log(`✅ 音频已保存: ${audioPath}`);

    // Also save metadata
    const metaPath = path.join(__dirname, `douyin_${VIDEO_ID}.json`);
    writeFileSync(metaPath, JSON.stringify(videoData, null, 2), 'utf-8');
    console.log(`✅ 元数据已保存: ${metaPath}`);

  } catch (e) {
    console.error(`❌ 音频下载失败: ${e.message}`);
    process.exit(1);
  }
}

main().catch(e => {
  console.error(`❌ 脚本异常: ${e.message}`);
  process.exit(1);
});
