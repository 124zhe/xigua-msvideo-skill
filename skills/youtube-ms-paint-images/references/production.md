# 生成与交付

## 分镜数据

推荐以 JSON 的 `frames` 数组保存全片，按起始时间排序。以下为可执行示例，字段也可以增加：

```json
{
  "version": 3,
  "frames": [
    {
      "id": "007",
      "estimated_start_ms": 11839,
      "estimated_end_ms": 14148,
      "timing_status": "estimated_without_audio",
      "narration_fragment": "Finally. Some all-natural air.",
      "narration_context": "Finally. Some all-natural air.",
      "visual_subject": "旅人误把天然空气当作安全的推介笑点",
      "character_role": "笑点主体",
      "character_placement": "中右近景，突出表情和手势",
      "shot_type": "推介空气的中近景",
      "composition_action": "主角大脸和上半身占中右，一手握胸侧黄牌，一手像推销员向空白空气摊开，表情过分自信。后方只留少量海岸。",
      "color_structure": "黄牌为暖色重点，蓝背包和蓝海次要，白脸与黑线最清楚。",
      "major_change": "从环境全景切到表情、牌子与手势",
      "onscreen_text": "100% NATURAL"
    }
  ]
}
```

`visual_subject` 描述本镜的真正主体。人物参与时用 `character_role` 和位置/大小字段说明是主体、观察者、尺度参照、互动者或笑点；独立物件/环境镜头可记“无角色”。这些是逐镜构图选择，不按旁白是否出现人称词自动决定。有既有字段时保留并扩展，无须为字段名重做项目。

`major_change` 写出实际视觉变化，例如“从小人物与大海的全景，切到浪头撞击岩石的接触点”，而非只列两个镜头名称。按相邻 3–5 镜复核，并在生图后查看对应联系图。

保留原稿和时间依据；需要重切分时先另存新版本。一个口播段落可引用多个镜头，一个镜头只对应一个明确画面时刻。编号、毫秒时间和旁白是持续追踪的键。

## 命名与时间依据

默认使用“三位分镜编号 + 开始时间戳”约定：

```text
frame-001_00m00s000ms.png
frame-007_00m11s839ms.png
frame-119_03m57s746ms.png
frame-182_06m01s361ms.png
```

- `frame-` 后是从 001 开始的稳定编号；超过 999 时自然扩展，不截断数字。
- 后面依次是分钟、秒、毫秒，至少两位分钟、两位秒、三位毫秒。文件名不含 Windows 禁止的冒号。
- 数值取当前分镜的开始毫秒值。优先使用已确认的实际 `start_ms`，否则用 `estimated_start_ms`；保留来源字段和 timing_status。
- 已有 11839 ms 就使用 11s839ms，不从显示用的 00:11.8 反推并损失精度。
- 只有精确到整秒或十分之一秒的时间戳时，后补零仅为格式统一，不能宣称新获得毫秒精度。
- 不按图片生成成功的先后编号，不把时间戳写进图片画面。
- 重生成同一帧，先存独立尝试文件，检查后再选一张作为交付版本；旧尝试放在独立子目录，根目录每个时间点只保留一个选定版本。
- 时间轴有变动时，更新文件名及对照表，保留原时间/新时间映射；不静默覆盖另一版本。

默认目录 `outputs/<topic>-images-vN/`。至少保留图片、`timeline.csv`、提示词、逐帧生成记录和浏览页。版本号按项目现状递增。

## 单张提示词

把“遍历时间戳、帧数、文件名、并发与保存”留在编排层；单张生成模型只接收这张该怎么画。可使用如下固定风格载荷，再填写实际镜头：

```text
Use case: illustration-story.
One horizontal 16:9 YouTube frame. Intentionally crude beginner MS Paint
drawing, wobbly thick uneven black outlines, basic shapes, flat bucket-fill
colors, pure white background. All subjects use this same crude visual language.
When people are included in the planned composition, use simple round heads,
dot eyes, black stick bodies and limbs, and basic expressions and gestures.
A person may lead the shot or support an environmental scene as an observer,
scale reference, interaction partner or visual joke. Follow the planned role,
size and position; people are neither required nor banned by narration wording.
Vivid saturated colors with a clear primary focal area and quieter
supporting colors. Build a readable action scene with connected props
when the narration calls for one. Scene density follows the specific
composition; do not shrink everything into a tiny isolated icon.
Keep important faces, hands, labels and contact points fully visible.
Flat 2D; no gradients, shading, texture, 3D or cinematic lighting.
Amateur, funny and deliberately awkward, not polished illustration.
No narration subtitles, timestamps, extra labels or decorative objects.
```

接着给出：

1. **涉及的连续性**：本镜实际出现的角色、设备、场地和状态；独立环境/物件镜头无需加载全片角色设定。
2. **具体构图**：主体位置/大小、动作或状态、作用对象、注意中心和环境；有人物时说明其主辅作用与面积关系。
3. **色彩关系**：哪块是主色，哪块退后，强调色指向哪里。
4. **画内准确文字**：逐字列出；没有就写 NONE。
5. **旁白语境**：只为理解含义，不印进图片。
6. **必要事实边界**：把“可能”“模型比较”“示意”转化为相应标签/构图。
7. **参考角色**：参考图只锁定线条、颜色或角色身份；新镜头不复制旧场景。

不要把所有片段涉及的角色或科学约束塞入每张图，以免引入无关对象；只加入当前帧需要的事实条件。少量关键排除项足够。不可将“长负面提示一定导致反向出图”写成未经验证的技术规律。

## 工具、检查与续作

- 内置生成可用时按其规范执行；若只有其他工具，核对其实际能力和授权。正常批量不自动切换付费 API、CLI 或供应商。
- 一个工具调用生成一张对应场景；一幅包含四格的联系图不能代替四张独立图。
- 已确认样图能直接复用，复制到整套目录并按统一规则命名，记录 reused_approved_sample。
- 每次成功立即保存来源路径、选定路径、帧号、实际尺寸、提示词和参考路径。视觉审查状态单独记录，文件存在不等于合格。
- 并发量按工具支持情况控制，不预设固定大并发；不要一次派发全部调用后无法逐张记录、检查或响应用户暂停。
- 明确失败可做针对性重试。结果未知先检查记录/输出，避免重复生成。持续同类错误时保留进度、说明阻碍，不无限自动重试，不擅自换生成渠道。
- 中断后的恢复检查设计版本、旁白、时码、样图风格和文件记录；找到相同编号的旧文件不代表符合最新设计。
- 检查生成结果是否有多肢体、文字乱码、遮挡、道具关系错误、科学条件丢失；修复明确问题，不能以“更精致”为目标。
- 把相邻 3–5 张一起看，检查人物主次、主体面积、主要轮廓、色块、姿态与信息结果；即使单张合格，连看近似也应改构图或动作。保留有叙事推进的连续镜头，不套固定镜型轮换或人物比例。
- 检查真实宽高。原生输出为近似 16:9 时记录实际尺寸；严格交付比例另按当前工具允许的方式处理，不拉伸、不裁掉主体，不偷偷用程序重绘或代替生成。
- 浏览页可以用 16:9 容器完整显示原图，但这不改变文件比例。把两者区分清楚。
- 用户切换到整理技能时，停止新派发，记录当前已知结果；不要创建后台自动续跑或定时任务。

## 命名与完整性工具

以下命令中的 skill 路径按实际安装目录替换：

```powershell
python "<skill>/scripts/frame_manifest.py" plan --storyboard "outputs/storyboard.json" --out-dir "outputs/topic-images-v1"
python "<skill>/scripts/frame_manifest.py" audit --plan "outputs/topic-images-v1/frame-plan.json"
```

输入支持数组、`frames` 或 `jobs`。要求每帧有唯一正整数 id（可用补零字符串）与非负整数毫秒开始值；无毫秒字段时支持 `MM:SS[.sss]` / `HH:MM:SS[.sss]` 的 start。时码必须递增，结束大于开始且不越过下一帧开始。间隙会报告，不自行补帧。

`frame-plan.json` 是独立的命名与库存清单，不是可直接交给合成器的最终分镜。全流程生产时，以总控技能的 [分镜接口](../../xigua-msvideo-skill/references/contracts.md) 为准：使用连续整数 `id`、核验后的 `start_ms/end_ms`、实际音频哈希及逐图审核信息。将规划结果回填权威分镜，不把字符串编号、估时或库存状态当成已完成对齐/审核。

plan 保存输入字段、确定的文件名和来源摘要；已有同名计划时拒绝覆盖，应检查现有版本或使用新目录。audit 只报告磁盘库存和 PNG 头部尺寸，不解码或修改图片，不替你判断画风、内容、CRC 或完整图像数据。缺图/坏头会返回非零退出码。额外文件和比例差异在报告里明确列出，不静默忽略。

视觉核对仍须逐张执行；不能用“脚本通过”代替观看图片。
