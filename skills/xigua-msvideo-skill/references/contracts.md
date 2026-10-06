# 产物、时间轴与续作

## 生产记录

在项目内维护 `production.json`，保存当前权威版本，而不是汇总所有历史尝试：

```json
{
  "version": 1,
  "topic": "本期题目",
  "language": "en-US",
  "requested_end_stage": 6,
  "script": {"path": "narration.txt", "sha256": "实算哈希", "status": "passed"},
  "audio": {"path": "audio/narration.mp3", "sha256": "实算哈希", "duration_ms": 5000, "status": "passed"},
  "storyboard": {"path": "storyboard.json", "version": 1, "audio_sha256": "实算哈希", "status": "passed"},
  "images": {"expected": 2, "saved": 0, "reviewed": 0, "missing_ids": [1, 2]},
  "video": {"path": "final.mp4", "status": "pending"},
  "next_action": "生成第 1 张图片",
  "waiting_for": null
}
```

阶段状态可用 `pending / in_progress / waiting_user / passed / stale / failed`。根据真实文件、哈希和审核更新，不按调用提交数算完成；等待超时不等于批准。汇总文件用临时文件加原子替换更新，单帧记录独立保存，避免整份清单写入中断而丢失进度。

## 分镜接口

`storyboard.json` 路径均相对该 JSON 所在目录；允许绝对路径，交付便携包时改为相对路径并复制实际文件。默认字段：

```json
{
  "version": 1,
  "source_audio": "audio/narration.mp3",
  "audio_sha256": "实际音频 SHA256",
  "duration_ms": 5000,
  "timing_status": "audio_aligned_native_word_boundaries",
  "frames": [
    {
      "id": 1,
      "start_ms": 0,
      "end_ms": 2300,
      "filename": "frame-001_00m00s000ms.png",
      "image": "images/frame-001_00m00s000ms.png",
      "narration_fragment": "本镜对应原文",
      "visual_subject": "主体",
      "shot_type": "环境全景",
      "composition_action": "谁在什么位置做了什么",
      "major_change": "首次建立环境",
      "color_structure": "主色块、次色块、留白",
      "people_rule": "人物角色、位置、大小；无人物则写无",
      "onscreen_text": [],
      "accuracy_constraints": ["必要事实条件"],
      "image_review_status": "pending",
      "image_sha256": null
    },
    {
      "id": 2,
      "start_ms": 2300,
      "end_ms": 5000,
      "filename": "frame-002_00m02s300ms.png",
      "image": "images/frame-002_00m02s300ms.png",
      "narration_fragment": "下一段原文",
      "image_review_status": "pending",
      "image_sha256": null
    }
  ]
}
```

第二镜省略的视觉设计字段在真实生产中仍要补齐。`image_review_status` 仅在实际查看该文件后写 `passed`，同时把审核对象的 SHA256 写入 `image_sha256` 与逐帧记录，避免文件被更换后沿用旧审核。合成脚本核对该哈希。

编号从 1 连续递增；毫秒为整数；每镜 `end_ms > start_ms`；相邻边界严格相等；首镜 0，末镜等于 `duration_ms`。`filename` 按同版分镜的编号和开始时刻形成，不按生成顺序命名。

`timing_status`：尚未对齐用 `estimated`；核验原生边界用 `audio_aligned_native_word_boundaries`；ASR 或强制对齐用 `audio_aligned_asr` / `audio_aligned_forced`；人工核对用 `audio_aligned_manual`。状态字符串本身不是证据，另存对齐来源、全文匹配结果和检查范围。合成脚本拒绝 `estimated`。

## 逐帧记录与失效范围

每镜 `records/frame-NNN.json` 保存：编号、分镜版本、来源类型（生成/编辑/复用）、实际提示词、参考路径、图片路径、真实尺寸、SHA256、审核结论、任务标识（若有）。生成成功未审核、审核失败和未生成要分开计数。

| 变化 | 需要重新处理 |
| --- | --- |
| 修改口播 | 受影响配音、对齐、分镜、图片及成片；不重新研究无关段落 |
| 换声线或语速 | 配音与全轴重对齐；语义不变的已通过图片可复用并重新映射 |
| 修一张图片 | 该图审核及成片；不要重生全部图或配音 |
| 改分辨率/编码 | 仅重新渲染和成片检查 |
| 只有尚未登记的图 | 先查看与原始调用记录，明确对应关系后纳入，不猜编号 |

续作先核对用户当前要求、production、storyboard、records、真实文件；历史问题记录不等于当前失败列表。不要重跑会覆盖当前版本的旧分镜初始化器。

最终提示词集从实际 records 合并，而不是只交最早 prompts 文件。编辑提示词必须连同编辑目标/参考记录；复用图找不到原始提示词时明确 `null` 和来源，不能伪造为本次独立生成请求。
