# 中文使用手册

`Sing Along Companion` 是一个可独立运行的参考实现，包含：

- 一起听房间的播放时间线和逐句歌词上下文；
- 浏览器本地 F0（基频）检测；
- 用户明确同意后，短暂分享稀疏音高点进行跟唱对比；
- 从已授权的原曲文件提取全混音主导音高和声学轮廓；
- 将歌词、播放位置、原曲轮廓和跟唱回执接入同一条主聊天线。

它不包含歌曲目录、音乐平台登录、账号 Cookie、真实歌词、音源、录音上传、聊天记录或个人资料。

## 1. 环境要求

- Python 3.10 或更高版本；
- Node.js 20 或更高版本；
- npm；
- 如需分析原曲文件：安装 `ffmpeg`。

检查 ffmpeg：

```bash
ffmpeg -version
```

## 2. 启动演示

在仓库根目录创建 Python 虚拟环境并安装 API 依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -r services/api/requirements.txt
.venv/bin/uvicorn app.main:app --app-dir services/api --reload --port 8000
```

另开一个终端启动网页：

```bash
cd apps/web
npm install
npm run dev
```

打开 Vite 输出的地址即可。初始房间的歌曲、歌词和参考线都是合成演示数据，不会请求任何第三方音乐服务。

## 3. 浏览器本地音高检测

在网页的“本地音高与可选跟唱”卡片中点击“开始本地音高检测”。浏览器会请求麦克风权限，并每约 180 毫秒使用归一化自相关估计一次 F0。

默认行为：

- 原始麦克风音频不离开浏览器；
- 音高点也不离开浏览器；
- 停止后会关闭音频轨道和 AudioContext。

这适合只想看自己音高走势的场景。

## 4. 跟唱分享和原曲对比

若要让主聊天自然接住一次跟唱，先勾选“结束时写入跟唱回执”，再开始检测。

此模式会：

1. 在开始时记录同一播放时间线上的歌曲位置；
2. 每秒向 API 发送一批稀疏 `{t_ms, hz}` 点；
3. API 只在内存中保留短窗口，绝不接收麦克风字节或转写；
4. 停止时把用户 F0 和原曲参考帧按时间轴对齐；
5. 在主聊天的同一时间线写入一条隐藏回执，并生成一条正常可见的助手回复。

对比输出包括：

- 用户和原曲的高低走势是否接近；
- 用户相对于原曲的中位调性偏移（半音）；
- 用户整体是高于、低于还是接近原曲调性。

它不是音准分数，也不是人声分离结果。完整混音中的伴奏、和声、混响都可能影响主导 F0，因此应把结果用于“旋律走势提示”，而不是严苛评分。

## 5. 从原曲生成参考音高

仅对你有权分析的本地音频文件执行下面的命令。不要把受版权保护、无授权的音频、平台缓存或账号下载文件提交到 Git。

```bash
cd services/audio-analysis
npm run analyze-file -- \
  --input /path/to/authorized-track.mp3 \
  --song-id demo-signal \
  --output ../../data/reference-contours/demo-signal.json
```

参数说明：

| 参数 | 含义 |
| --- | --- |
| `--input` | 已授权的本地音频路径。URL 会被拒绝。 |
| `--song-id` | 和播放器/房间使用的歌曲 ID 一致，只能含字母、数字、`_`、`-`。 |
| `--output` | 派生 JSON 输出路径。默认是 `data/reference-contours/<song-id>.json`。 |
| `--max-seconds` | 最多分析秒数，默认 720 秒。 |

分析器会通过 ffmpeg 解码到进程内存，提取：

- 稀疏的原曲全混音主导 F0 帧；
- 10% / 90% 音高范围及音名；
- 能量分段、动态、运动密度、粗粒度音色和旋律走势。

源音频不会被上传、缓存或写到输出目录。输出只有派生 JSON，且 `data/` 已在 `.gitignore` 中忽略。

## 6. 让 API 使用真实参考线

把参考 JSON 所在目录传给 API：

```bash
REFERENCE_CONTOUR_DIRECTORY=./data/reference-contours \
  .venv/bin/uvicorn app.main:app --app-dir services/api --reload --port 8000
```

当 `song_id` 与 JSON 文件名和文件内容中的 `song_id` 都匹配时：

- `GET /api/listen/songs/{song_id}/reference-pitch` 返回真实派生参考帧；
- `GET /api/listen/songs/{song_id}/profile` 返回真实派生声学轮廓；
- 跟唱停止后会自动用它进行时间轴对比。

例如演示房间使用 `demo-signal`，因此生成 `demo-signal.json` 就会覆盖演示用的合成参考线。接入真实播放器时，确保房间当前歌曲 ID、前端播放器和分析 JSON 使用同一个稳定 ID。

## 7. 主聊天如何拿到一起听上下文

普通聊天只有在文本提到歌曲、歌词、跟唱、音高、旋律或播放等线索时，才会附带必要的一起听数据。上下文是一个受长度限制的 JSON 数据块，包含：

- 播放状态和当前位置；
- 当前和下一句时间轴歌词；
- 派生声学轮廓；
- 最近两条房间备注。

歌词、标题、备注等外部文本会作为不可信数据传入模型适配器，不能被当作指令执行。

跟唱结束时不同：系统总会生成一个隐藏的回执输入，并在同一条主聊天线上产生可见的助手回复。因此不会另起一个“跟唱聊天”。

## 8. 接入自己的播放器或聊天系统

替换下面几个可插拔边界即可：

| 目标 | 对应位置 |
| --- | --- |
| 房间状态、歌曲 ID、播放位置 | `services/api/app/room.py` 的 `RoomStore` |
| 原曲参考 JSON | `services/audio-analysis/src/analyze-file.mjs` 和 `ReferenceContourRepository` |
| 主聊天模型 | `services/api/app/conversation.py` 的 `ConversationGateway` |
| 前端播放控件 | `apps/web/src/App.jsx` |

不要把音乐平台 Cookie、真实音源 URL 或个人账户逻辑放到浏览器，也不要提交到仓库。

## 9. 隐私与上线前检查

上线前至少完成：

```bash
.venv/bin/python -m pytest services/api/tests
cd services/audio-analysis && npm test
cd ../../apps/web && npm run build
cd ../.. && bash scripts/public-audit.sh
```

生产环境还必须补充身份认证、房间成员授权、HTTPS、精确 CORS、限流和数据删除策略。详细边界见：[PRIVACY.md](PRIVACY.md) 和 [SECURITY.md](SECURITY.md)。
