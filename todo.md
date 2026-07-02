# social_context TODO

> 历史脉络：原聚焦 ESM v0.10.0 跨插件改造（阶段一+二已完工，阶段三已定论取消）
> 当前版本：**v0.8.15**（commit `3f1ab20`，2026-07-01）

---

## 1. 阶段一：social_context 迁移 v0.8.12 ✅

- [x] 升级对 ESM `to_text_part` 的依赖
- [x] 删除接入点 3（self-reply signal）
  - [x] 删 `_apply_emotion_self_reply_signal`（`mixins/emotion_bridge.py:171-240`，约 70 行）
  - [x] 删 4 个配置项 + `_conf_schema.json` hint
  - [x] 删 `self._emotion_signal_last` / `self._emotion_disabled_warn_last`
  - [x] 删 `tests/test_emotion_bridge.py` 约 30 行（实际 12 个 self-reply 测试）
  - [x] 简化 `_get_emotion_plugin` 检查列表
- [x] judge=yes 后显式调用 `esm.apply_self_reply_signal(event)`（4 行）
- [x] 接入点 2 改造：字符串拼接 → `to_text_part` 独立 TextPart
- [x] 更新 CHANGELOG：v0.8.12 段落（提及 ESM v0.10.0+ 依赖）
- [x] bump metadata.yaml 到 v0.8.12
- [x] 跑测试确认无回归（149 passed / 0 failed）

---

## 2. README 强依赖声明 ✅

> 与 §1 同 PR commit `4c986c9`

- [x] 在 `README.md` 显眼位置加 ESM v0.10.0+ 强依赖声明（独立"依赖要求"section，介于"当前功能"和"输出微调"之间）

  > **依赖要求：ESM v0.10.0+ 强依赖**
  >
  > 本插件 v0.8.12+ 调用了 [`astrbot_plugin_emotion_state_machine`](https://github.com/kazamisama/astrbot_plugin_emotion_state_machine) 的两个 v0.10.0 新 API：`to_text_part()` 和 `apply_self_reply_signal()`。
  >
  > - **如果没装 ESM**：emotion 注入会**静默 no-op**（social_context 检测不到 emotion 插件时整条链路降级），bot 主动回复的 self-reply signal 也不会打，但主流程仍正常工作。
  > - **如果装了 ESM 但 < v0.10.0**：judge 通道会**降级到字符串拼接**（`build_prompt_block` 仍可用但缺 `to_text_part`），self-reply signal 路径**直接缺失**。
  >
  > 推荐安装：`pip install astrbot-plugin-emotion-state-machine>=0.10.0` 或在 AstrBot 管理面板升级到 v0.10.0+。

---

## 3. 阶段三：彻底清理 emotion_bridge ❌ **已定论 — 取消**

**定论日期**：2026-07-02
**观察期**：2026-06-27 ~ 2026-07-02，共 5 天，**无 emotion 相关 bug 反馈**。

**结论：§3 不必执行。** emotion_bridge.py 是当前 design 下正确的抽象层，不是技术债。

### 为什么不做了

1. **emotion_bridge 当前 195 行，做 5 件事**——每件都是 1-2 行核心 + try/except 兜底：
   - `_get_emotion_plugin()`：解析 ESM 实例
   - `_emotion_scope(event)`：优先 ESM.get_scope，降级本地
   - `_feed_emotion_observation(...)`：调 `esm.observe_text`
   - `_build_emotion_block(...)`：调 `esm.build_prompt_block`（降级路径）
   - `_get_bot_energy(scope)`：调 `esm.get_bot_energy`（v0.8.14+）

2. **当前 ESM 是可选依赖**——README §2 明确声明。缺失时所有调用静默降级，主流程不受影响。

3. **emotion_bridge 的核心价值 = 统一封装缺失/异常/降级**。如果直接调 `self.context.get_registered_star(...)`，每个调用点都要重写 try/except，代码散落更糟。

4. **§3 的真实收益 = 让 ESM 从可选变强依赖**。但那是 **breaking change**（没装 ESM 的用户全炸），不属于"清理"，属于**产品决策**。

### 何时重启 §3

仅当产品决定 ESM 变强依赖（emotion 是核心体验）。届时 emotion_bridge 可整文件删除，主流程直接 `esm.observe_text` / `esm.to_text_part`，无 try/except 散落问题。

---

## 后续进展（v0.8.13 → v0.8.15）

### v0.8.13 (commit `46b28b4`)

- **重构**：`_conf_schema.json` 按功能方向分框（engram 风格）
- 13 序号段 → 11 功能框；description 序号取消；数据层扁平保持不变
- 测试：149 passed / 0 failed（零代码改动，schema-only refactor）

### v0.8.14 (commits `95af797`, `475cc54`)

- **新功能：ESM 精力机制接入**（本次会话主要工作）
  - 硬门槛（`judge_energy_gate_enabled` 默认 true）：精力 < 0.2 直接跳过 judge，零 token 消耗
  - 软注入（`judge_energy_inject_enabled` 默认 true）：`{bot_energy}` 进 judge prompt，让 judge 自主降权
  - emotion_bridge 新增 `_get_bot_energy(scope)`，从 ESM `get_bot_energy()` 拉取
  - judge 默认 prompt 新增 "Bot 当前状态" 块
  - 3 个新配置项：`judge_energy_gate_enabled` / `judge_energy_gate_threshold` / `judge_energy_inject_enabled`
- 测试：149 passed / 0 failed（无回归）

### v0.8.15 (commits `122fdfc`, `93e4edb`, `149aa60`, `3f1ab20`)

- **新功能：自主触发风格提示模板化**——`on_llm_request` 中 `social_context_triggered` 分支原本是硬编码 note，改为可编辑模板 `triggered_reply_hint_template`，支持 `{style}` `{intent}` `{bot_energy}` 占位符，注入主回复 LLM 用户消息末尾
  - 精力偏低（<0.3）时主 LLM 被提示"语气可稍显慵懒、句子更短"，形成"judge prompt 软抑制 + 主 LLM 语气收敛"双层闭环
- **重构：4 个 prompt 模板归位**——删除顶层 `prompt_templates` 框，按功能归类：
  - `reply_injection` 下：`reply_prompt_template`（群聊观察注入）+ `triggered_reply_hint_template`（自主触发风格）
  - `judge` 下：`judge_prompt_template`（判断模型上下文）+ `judge_decision_prompt`（判断决策）
- hint/description 全面更新（标注依赖关系、占位符全集、version 标记）
- 测试：149 passed / 0 failed（无回归）

---

## 验收记录

- 2026-06-27 v0.8.12 commit `4c986c9` 已 push ✓
- 2026-06-30 v0.8.13 schema 分框 commit `46b28b4` 已 push ✓
- 2026-06-30 v0.8.14 ESM 精力接入 commit `95af797` 已 push ✓
- 2026-07-01 v0.8.15 模板化 + 归位 commit `3f1ab20` 已 push ✓
- **当前 main 头：`3f1ab20`**
- §3 已定论：观察期无 bug，且当前 design 不需要该重构
- 精力机制贯穿：judge 决策层（硬门槛 + 软注入）+ 主回复 LLM 语气层（triggered_reply_hint_template）