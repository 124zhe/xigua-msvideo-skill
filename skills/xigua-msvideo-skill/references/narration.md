# 配音与真实时间依据

## 选择路线

已有用户最终音频：保留原文件，测时长和 SHA256，转写/对齐后进入分镜，不重新合成声音。

新配音：沿用用户语言、声线、语速和预算。英文默认可采用 `edge-tts` 的 `en-US-BrianNeural`、`+0%`。它访问 Microsoft Edge 的在线 TTS 服务，不是离线模型，也不保证未来永久可用。没有授权不要因故障切换到付费生成。

首次选择声线时优先短样；已认可或明确允许默认声线时无需重复试听确认。指定 ChatCut 才读取当前插件的 basics 和 voice，继承其真实任务状态，保留 job/asset id。

## 运行本技能脚本

需要 Python 3.10+、可用的 `ffmpeg` / `ffprobe` 和支持 `WordBoundary` 的 `edge-tts`。版本见本技能的 `requirements-tts.txt`。先检查已安装版本；可把依赖安装到当前项目的 vendor，避免改全局环境：

```powershell
python -m pip install --target "work/<slug>/tts/vendor" -r "<skill>/requirements-tts.txt"
python "<skill>/scripts/narrate_edge.py" --text "outputs/<slug>/narration.txt" --work "work/<slug>/tts" --out "outputs/<slug>/audio" --dependency-dir "work/<slug>/tts/vendor" --voice en-US-BrianNeural --rate=+0%
```

若依赖已在环境内可省略 `--dependency-dir`。可用 `--ffmpeg` / `--ffprobe` 明确可执行文件路径。脚本按自然段/句子分块，每块默认至多 2400 字符；保持文字覆盖，不固定为三段。不会自动安装依赖、改声音、重试付费服务。

输出 `narration.mp3`、`word-timings.json`、`audio-manifest.json`。成功目标不会覆盖：新版本用新的输出目录；异常运行保留工作分段，可在输出尚未完成时用同一参数续作。

缓存键含全文块、voice/rate/pitch 和库版本；复用前核验文件哈希与完整元数据。下载中的 `.tmp.mp3` 不计完成。网络失败最多重试一次，持续失败退出并保留成功分段。

## 对齐依据

每段保存原生 WordBoundary：`offset` 和 `duration` 单位为 100ns。合并 MP3 后，用 ffprobe 的音频 packet SHA256 序列核对分段完整对应最终流，并以 packet PTS 差校准各段全局偏移。不能用字数、估算语速或上一段最后一词时间代替实际偏移。

脚本核对所有 packet 和全文归一化文本。两者成功才发布 `audio_aligned_native_word_boundaries`。无法对应时保留工作音频及 `failure.json`；可改对实际最终音频做逐词 ASR/强制对齐，不能把失败结果标为精准。

原生时间是服务提供的词边界；归一化匹配忽略标点与空格，不证明发音正确。抽听开头、难词、数字、拼接处与结尾；检查遗漏、重读、断词、异常空白。仅完成技术检查时记录 `listening_review: pending`，不能声称已经逐秒听审。

最终文件若又被裁剪、变速、压缩或换段，重新核对音频哈希与时间依据。配音时长以实际文件为准；字数估时只用于起稿。
