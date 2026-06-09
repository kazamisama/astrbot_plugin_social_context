# AstrBot Plugin Social Context

轻量群聊状态感知层。它借鉴 heartflow 的“原始群聊状态缓冲 / 当前氛围判断”思路，但不接管主动发言裁决，定位为更稳定、可复用的 social context layer。

## 当前功能

- 监听群聊消息，维护最近窗口内的消息数、活跃用户、最近发言者。
- 监听 aiocqhttp 群戳一戳 notice，记录窗口内戳一戳事件。
- 维护用户今日互动与简单熟悉度。
- 在 LLM 请求前注入低优先级观察，不要求模型复述统计。
- 提供 `/social_context` 查看当前会话状态。
- 管理员可用 `/social_context_reset` 重置当前会话状态。
- JSON 持久化，默认保存到 `data/plugin_data/astrbot_plugin_social_context/social_context_state.json`。

## 注入示例

```text
[群聊状态观察]
最近60秒：群聊较活跃，8条消息，3人参与。
最近较活跃的人：chiriu、Alice、Bob。
窗口内有2次戳一戳。
你上次在这个群发言是3分钟前。
这些只是低优先级观察：自然使用，不要复述统计，不要因为看到观察就强行回应或解释。
```

## 设计边界

第一版只做状态层：观察、记录、摘要、注入。

暂不做：

- 主动发言裁决
- 调小模型打分
- 插件间强依赖 API
- 长期人格/情绪模拟

这些后续可以在状态层稳定后再接。
