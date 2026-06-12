# Changelog

## v0.4.3 - 2026-06-12

- Prompt injection 扫描调整为判断模型专属：`<INJECTION_RISK>` 只进入判断模型 prompt，不再注入正式回复模型，降低回复阶段噪声。
- 新增 `prompt_security.py`，将扫描规则拆成纯函数模块，并避免已标记片段被重复包裹。
- 隐藏 `_conf_schema.json` 中的旧兼容项 `inject_enabled`；代码仍保留旧配置读取兼容，新用户 WebUI 不再看到旧字段。
- `_cfg_bool()` 增强字符串 bool 解析，避免 `"false"` / `"off"` / `"关闭"` 被 Python truthy 规则误判为开启。
- 自主判断触发成功时立即写入冷却时间，避免正式回复回流前重复触发判断。
- 持久化状态不再保存消息正文 `content`，降低落盘隐私风险；读取旧状态时保持兼容。
- README / 配置说明同步更新：明确 prompt injection 扫描只作用于判断模型输入。
- 新增 `tests/test_plugin_helpers.py`，覆盖 bool 解析、判断/正式回复扫描边界、消息正文不落盘等回归场景。

## v0.4.2 - 2026-06-12

- 配置项 `judge_injection_scan_enabled` 改名为 `judge_prompt_injection_scan_enabled`，自解释更强、跟 `inject_enabled` / `reply_inject_enabled` 的"注入"双关明确划开。
- `_conf_schema.json` 同步改名 + description / hint 写清楚：标明本项是 **prompt injection 防护**（inbound），不是 **social context 注入**（outbound），方向相反。
- `README.md` 新增对比表，说明 `inject_enabled` / `reply_inject_enabled` / `judge_prompt_injection_scan_enabled` 三者职责边界。
- **迁移路径**：旧 key `judge_injection_scan_enabled` 不再被读取；默认值为 true，升级后行为不变（扫描保持开启）。如需关闭，请在 WebUI 中把新 key 设为 false。

## v0.4.1 - 2026-06-12

- 新增数据层 Prompt 注入防护：对进入判断 / 正式回复 prompt 的用户可控字段（昵称、消息原文、戳一戳者）做正则扫描，命中片段用 `<INJECTION_RISK>…</INJECTION_RISK>` 包裹。
- 新增 `_scan_injection_risk` 私有方法 + `_scan_variables` 辅助方法，覆盖中文/英文指令、角色伪装、chat template token、分隔符、高优先级标签等模式。
- 在 `_judge_should_reply`、`build_judge_prompt_block`、`build_reply_prompt_block` 渲染前接入扫描；`judge_decision_prompt` / `judge_prompt_template` / `reply_prompt_template` 默认模板同步加 `<INJECTION_RISK>` 提示说明。
- 新增 `judge_injection_scan_enabled` 配置项，默认 true；关闭后只保留模板里的提示词防御。
- 移除未使用的孤儿 import `from astrbot.api.message_components import Plain`。

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
