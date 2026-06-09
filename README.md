# AstrBot Plugin Social Context

轻量群聊状态感知层。它借鉴 heartflow 的“原始群聊状态缓冲 / 当前氛围判断”思路，但不接管主动发言裁决，定位为更稳定、可复用的 social context layer。

## 当前功能

- 监听群聊消息，维护最近窗口内的消息数、活跃用户、最近发言者。
- 监听 aiocqhttp 群戳一戳 notice，记录窗口内戳一戳事件。
- 维护用户今日互动与简单熟悉度。
- 在 LLM 请求前注入低优先级观察，不要求模型复述统计。
- v0.2.0 起提供双模块化 prompt：
  - `build_reply_prompt_block(scope, event)`：给正式回复模型，影响“怎么说”。
  - `build_judge_prompt_block(scope, event, max_age=None)`：给 heartflow/proactive 等判断模型，影响“回不回”。
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

供 heartflow / proactive_chat 等插件在小模型判断阶段调用，重点是辅助 social / timing / willingness。

```text
## Social Context 判断参考
- 最近180秒：群聊较活跃，12条消息，4名活跃用户，2次戳一戳。
- 最近较活跃的人：chiriu、Alice、Bob。
- bot 上次发言距今约3分钟。
- 当前发言者今日消息5条，戳人1次，熟悉度约12.4/100。
- 使用方式：只作为 social/timing/willingness 的参考；不要因为观察存在就强行判定应该回复。
```

## 设计边界

v0.2.0 仍只做状态层：观察、记录、摘要、prompt 生成。

暂不做：

- 主动发言裁决
- 自己调小模型打分
- 插件间强依赖 API
- 长期人格/情绪模拟

这些后续可以在状态层稳定后再接。
