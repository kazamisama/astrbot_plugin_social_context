# Changelog

## v0.4.0 - 2026-06-09

- 新增自主选择模型判断是否回复功能，可在配置中选择判断模型提供商。
- 新增 `judge_enabled`、`judge_provider_id`、`judge_reply_threshold`、`judge_min_reply_interval`、`judge_max_retries`、`judge_decision_prompt` 配置项。
- 判断模型输出 `should_reply/confidence/reasoning` JSON，达到阈值后触发正式回复链路。
- social context 主动触发的正式回复会自动追加“非点名主动参与”的低优先级说明。

## v0.3.2 - 2026-06-09

- 调整判断阶段配置措辞为“自主选择模型用于判断是否回复”，弱化插件依赖感。

## v0.3.1 - 2026-06-09

- 调整配置与文档措辞，移除对特定消费插件的绑定描述。
- 判断阶段 prompt 保持通用外部决策接口定位，与 heartflow 等具体插件配置解耦。

## v0.3.0 - 2026-06-09

- 新增用户可编辑的 `reply_prompt_template` 与 `judge_prompt_template` 配置项。
- prompt 模板支持 `{变量名}` 占位符，便于在 WebUI 中调整注入文案。
- 新增模板安全格式化：缺失变量保留原样，模板错误时自动回退默认模板。

## v0.2.0 - 2026-06-09

- 新增双模块化 prompt 生成：正式回复参考与判断模型参考分离。
- 新增 `build_reply_prompt_block(scope, event)`，用于正式 LLM 回复阶段。
- 新增 `build_judge_prompt_block(scope, event, max_age=None)`，用于自主选择模型判断是否回复的流程。
- 新增 `reply_inject_enabled` 配置项，并兼容旧 `inject_enabled`。
- 新增 `judge_context_max_age` 配置项，控制判断模型导出的状态时间范围。

## v0.1.0 - 2026-06-09

- 新增群聊消息短期窗口。
- 新增 aiocqhttp 群戳一戳 notice 记录。
- 新增用户今日互动与熟悉度。
- 新增 LLM 请求前低优先级 social context 注入。
- 新增 `/social_context` 与 `/social_context_reset` 命令。
- 新增 JSON 持久化。
