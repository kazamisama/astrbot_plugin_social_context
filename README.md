# AstrBot Plugin Social Context

轻量群聊状态感知层。它维护短期群氛围、互动事件和用户熟悉度，并向回复模型或“自主选择模型用于判断是否回复”的流程提供可配置 social context。

## 当前功能

- 监听群聊消息，维护最近窗口内的消息数、活跃用户、最近发言者。
- 监听 aiocqhttp 群戳一戳 notice，记录窗口内戳一戳事件。
- 维护用户今日互动与简单熟悉度。
- 在 LLM 请求前注入低优先级观察，不要求模型复述统计。
- v0.3.0 起两个 prompt 都可在配置中自定义模板：
  - `reply_prompt_template`：正式回复注入模板。
  - `judge_prompt_template`：判断模型注入模板。
- 提供 `/social_context` 查看当前会话状态。
- 管理员可用 `/social_context_reset` 重置当前会话状态。
- JSON 持久化，默认保存到 `data/plugin_data/astrbot_plugin_social_context/social_context_state.json`。

## 双模块化 prompt

### 正式回复参考

用于 AstrBot `on_llm_request`，已经决定调用正式 LLM 后注入，重点是让回复更自然。

```text
[群聊状态观察 / 正式回复参考]
最近60秒：群聊较活跃，8条消息，3人参与。
最近较活跃的人：chiriu、Alice、Bob。
窗口内有2次戳一戳。
你上次在这个群发言是3分钟前。
这些只是低优先级观察：自然使用，不要复述统计，不要因为看到观察就强行解释。
```

### 判断模型参考

供“自主选择模型用于判断是否回复”的流程调用，重点是辅助 social / timing / willingness。

```text
## Social Context 判断参考
- 最近180秒：群聊较活跃，12条消息，4名活跃用户，2次戳一戳。
- 最近较活跃的人：chiriu、Alice、Bob。
- bot 上次发言距今约3分钟。
- 当前发言者今日消息5条，戳人1次，熟悉度约12.4/100。
- 使用方式：只作为 social/timing/willingness 的参考；不要因为观察存在就强行判定应该回复。
```

## 可用模板变量

`reply_prompt_template` 和 `judge_prompt_template` 都支持这些占位符：

```text
{scope}
{group_id}
{window_seconds}
{vibe}
{message_count}
{active_user_count}
{recent_speakers}
{poke_count}
{latest_poke_sender}
{latest_poke_target}
{last_bot_reply_elapsed}
{current_user_id}
{current_user_name}
{current_user_message_count_today}
{current_user_poke_sent_today}
{current_user_poke_received_today}
{current_user_familiarity}
```

缺失变量会保留原样；模板格式错误时会自动回退默认模板。

## 设计边界

v0.3.0 仍只做状态层：观察、记录、摘要、prompt 生成。

暂不做：

- 主动发言裁决
- 自己调小模型打分
- 插件间强依赖 API
- 长期人格/情绪模拟

这些后续可以在状态层稳定后再接。
