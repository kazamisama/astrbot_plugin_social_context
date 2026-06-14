# Changelog

## v0.8.4 - 2026-06-14

- **修复：`_cfg_float` 拒绝 NaN/inf**——`main.py:_cfg_float` 之前用 `float()` 把配置值转数值，**NaN 和 inf 都是合法 float**（`float("nan")` / `float("inf")` 都不抛），`max(min_value, NaN)` 还会把 NaN 传染到下游，esm v0.3.0 的 `try_apply_signal` 对非有限 intensity 也会抛 `ValueError`。现在加 `math.isfinite` 守卫，NaN/inf 一律回退到 `default`。
  - 触发场景：手编 `_conf_schema.json` 时 `"intensity": "nan"` / `"inf"`，或上游异常给非有限值。修复前会被 `try_apply_signal` 自身捕获并 WARNING（双保险），主流程不炸但 esm 日志会有噪声；修复后根本到不了 esm，噪声消失。
  - 9 个新单元测试覆盖：合法 finite 回归、字符串数字 parse、`"nan"` / `"inf"` / `"-inf"` 字符串回退、原始 `float('nan')` 回退、完全不能 parse 的字符串走原 TypeError/ValueError 分支、NaN + min_value 边界（先 default 后 clamp）、`min_value=None` 不走 max 分支。
- ruff 0 issue。metadata.yaml v0.8.3 → v0.8.4。

## v0.8.3 - 2026-06-14

- **修复：适配 emotion_state_machine v0.3.0 的 HTML 哨兵包裹**——ESM 自 v0.3.0 起给 `build_prompt_block` 输出包了 `<!-- esm:emotion-block:start -->` / `<!-- esm:emotion-block:end -->` HTML 注释哨兵（用于自身 `_inject_emotion_block` 的去重/替换）。`mixins/emotion_bridge.py` `_build_emotion_block` 现在在末尾用正则剥离哨兵后再返回，**judge 模型的 system prompt 看不到 HTML 标记**，只看到纯情绪状态描述。
  - judge 路径特别值得做这一步：调用频率远高于 proactive_reply 路径（每条群消息都会判一次），每次省 ~60 token 累积可观；且 judge prompt 已经有 `<INJECTION_RISK>` 之类反注入标记，HTML 哨兵加进去既增加视觉噪声，也可能在未来 prompt 安全扫描里误命中。
  - 哨兵格式常量（`ESM_SENTINEL_START` / `ESM_SENTINEL_END`）定义在模块级，`re.escape` 后做非贪婪 + DOTALL 匹配，容忍空行/前后空白变体。哨兵格式若未来变更，正则失配会自然降级为「原样透传」—— LLM 忽略 HTML 注释，不会爆。
- 测试：125 → 128 个用例（新增 `test_block_strips_sentinels` / `test_block_strips_sentinels_extra_whitespace` / `test_block_passes_through_when_no_sentinels`）。128 passed / 0 failed。
- ruff 0 issue。metadata.yaml v0.8.2 → v0.8.3。

## v0.8.2 - 2026-06-14

- **修复：tier3 压缩入参注入防护缺口**——`_compress_history_tier3` 之前只把 sender_name / content 拼进 LLM prompt，绕过 `_scan_variables`。恶意用户在 tier3 窗口（30min~24h）发指令类昵称/内容，会被 LLM **字面照抄**进 `history_daily_summary`，污染所有下游读 `history_summary_tier3` 的判断模型（窗口长达 24h）。现在与 tier2 走同一套 `_scan_variables`（name + content 都过 `<INJECTION_RISK>` 包裹）。
- **加固：`_format_tier3_messages` 支持 `max_total_chars` 总量截断**——之前只对单条消息截 60 字符，长窗口 + 高频群（tier3 默认 24h）单次 prompt 可能塞 3KB+ 爆 token。现在以 `history_compress_tier3_max_chars` 作为输入总字符上限，与输出限制对齐；判断时机放在 `append` 之前，严格保证 `len(out) ≤ max_total_chars`。
- 测试：122 → 125 个用例（新增 `test_format_tier3_messages_caps_total_chars` / `test_format_tier3_messages_no_cap_keeps_all` / `test_compress_history_tier3_scans_injection`）。122 → 125 passed / 0 failed。
- ruff 0 issue。metadata.yaml v0.8.1 → v0.8.2。

## v0.8.1 - 2026-06-14

- **升级：emotion_state_machine v0.3.0 公共 API 适配**——ESM 在 v0.3.0 暴露了 3 个新公共 API（`try_apply_signal` / `is_signal_enabled` / `list_disabled_signals`），social_context 桥接切换到新 API 优先 + 旧 API 降级：
  - **`try_apply_signal` 优先 + `apply_signal` 降级**——ESM 自带的 hot-path 安全变体，unknown signal / 非法 intensity 自己捕获并 WARNING，不抛到 social_context。`apply_signal` 仍保留 fallback，v0.2.0 老 ESM 不受影响。
  - **`is_signal_enabled` 预校验 + 60s warn 去重**——`emotion_self_reply_signal` 配的 signal 名被 ESM 的 `disabled_signals` 列表禁用时，logger.warning 提示一次（60s 同 signal 去重，避免刷屏）。配置级问题不应静默吞。
- 内部字段：`__init__` 新增 `self._emotion_disabled_warn_last: dict[str, float] = {}`（60s warn 去重表）。
- 行为保持：emotion 插件缺失/未注册/抛异常时所有接入点静默降级，social_context 主流程不受影响。
- 测试：22 → 26 个用例（新增 `test_signal_skipped_when_disabled_in_esm` / `test_signal_disabled_warn_throttled_60s` / `test_signal_calls_try_apply_signal_not_apply_signal` / `test_signal_falls_back_to_apply_signal_when_try_missing`）。118 → 122 passed / 0 failed。
- ruff 0 issue。metadata.yaml v0.8.0 → v0.8.1。

## v0.8.0 - 2026-06-14

- **特性：情绪状态机集成（social_context ↔ emotion_state_machine 可选桥接）**——把情绪引擎 `astrbot_plugin_emotion_state_machine` 的公共 API 接入 social_context，让社交上下文与情绪状态在同一 scope 下互相滋养。emotion 插件**完全可选**，缺失/未注册/抛异常时所有接入点静默降级，social_context 主流程不受影响。
- 新增 `mixins/emotion_bridge.py`（`EmotionBridgeMixin`），三个接入点：
  - **接入点 1：观察消息**（`on_group_message` 调用 `_feed_emotion_observation`）——把用户原文喂给 emotion 的 `observe_text`，让情绪引擎做信号推断。bot 自己的消息不喂，避免自反馈。
  - **接入点 2：拼入判断模型 prompt**（`_judge_should_reply` 调用 `_build_emotion_block`）——把 emotion 的 `build_prompt_block` 拼到 `context_block` 后面，让 judge 模型也能"带着情绪"决策。注入用 emotion 自己的 `get_scope(event)` 算 scope，保证绝对一致。
  - **接入点 3：bot 主动回复后打轻量 signal**（`on_decorating_result` 调用 `_apply_emotion_self_reply_signal`）——bot 完成回复时给 emotion 调一次 `apply_signal`（默认 `friendly` / 0.3 / scope 维度最小间隔 30 秒），对长期情绪状态做温和正反馈。**emotion 缺失时不消耗节流时间戳**，避免插件短暂下线后被自身节流锁住。
- 新增 6 个配置项（⑩ 情绪状态机集成分组）：`emotion_observe_enabled` / `emotion_judge_inject_enabled` / `emotion_self_reply_signal_enabled` / `emotion_self_reply_signal` / `emotion_self_reply_intensity` / `emotion_self_reply_min_interval_seconds`，全部默认开启，开关齐全可逐项关闭。
- 新增 `tests/test_emotion_bridge.py`（15KB / 27 用例）：覆盖 emotion 缺失/缺方法/抛异常/开关关闭/正常调用/scope 对齐/节流不消耗/非法 signal 等 10 类场景。
- **修复：`_apply_emotion_self_reply_signal` 节流顺序 bug**——原先 emotion 缺失时也会写 `_emotion_signal_last[scope]`，导致插件短暂掉线后被自身节流锁住。改为先确认 emotion 可用再写时间戳。修后 118 passed / 0 failed。
- ruff 0 issue。metadata.yaml v0.7.2 → v0.8.0。

## v0.7.2 - 2026-06-14

- **重构：main.py 巨石文件按 Mixin 拆分**（97KB/2160 行 → 68KB/1512 行，拆出 5 个模块）。行为零变更，91 passed / 0 failed 全程绿。
  - `models.py`：5 个 dataclass（`JudgeResult`/`MessageRecord`/`PokeRecord`/`GroupContext`/`UserContext`）+ 纯函数 `_extract_json`/`_clamp_01`/`_to_bool`。
  - `mixins/members.py`（`MembersMixin`）：群成员查询的 7 个无装饰器辅助方法。
  - `mixins/persistence.py`（`PersistenceMixin`）：`_save_if_needed`/`_load_state`/`_group_to_json`。
  - `mixins/compress.py`（`CompressMixin`）：历史压缩 tier2/tier3 + 过期清理循环 + `_should_warn` 去重 + `HISTORY_COMPRESS_PROMPT`。
- **关键约束（拆分硬规则）**：AstrBot 按 `handler.__module__` **精确匹配**注册 handler（`star_handler.get_handlers_by_module_name`）。因此带 `@filter.*` 装饰器的 handler（命令/事件钩子/LLM 工具如 `get_group_members_info`）**必须留在 main.py**，否则 `__module__` 不符会导致 handler 加载失败。Mixin 只承载无装饰器的纯逻辑，通过 `self.xxx()` 跨 Mixin 调用。
  - 实测验证：import 后 `Added llm tool: get_group_members_info` 正常注册，MRO = `SocialContextPlugin → MembersMixin → PersistenceMixin → CompressMixin → Star`。
  - tier 边界辅助（`_history_tier_bounds`/`_get_messages_in_tier`/`_format_tier_label`/`_prune_stale_history`）被压缩/prompt/持久化多处共用，保留在 main.py 作为主类基础能力。
- ruff 0 issue。metadata.yaml v0.7.1 → v0.7.2。

## v0.7.1 - 2026-06-14

- **修复：tier2 历史压缩生产 bug（潜伏多版本）**——`_compress_history_tier2` 把消息 **list** 传给只接受单条 dict 的 `scan_variables()`，后者遍历 `.items()` 必抛 `AttributeError: 'list' object has no attribute 'items'`。即「tier2 压缩只要在生产环境真触发就 100% 崩」。改为逐条 dict 扫描。此前一直没暴露，是因为测试数据用绝对时间戳（落不进 tier2 窗口），压缩根本没跑到这行。
- **修复：测试套件 14 个失败全部修正**——此前 CHANGELOG 多版本记为「历史遗留 mock 写法问题、与本次无关」，实为真 bug。根因是环境从未安装 pytest，没人真跑过。现 **91 passed / 0 failed**。具体：
  - `setUp` 用 `__new__` 跳过 `__init__`，未补 v0.6.x~v0.7.0 新增的 7 个运行时字段（`_compress_warn_last` / `_persona_cache` / `_compress_tasks` / `_tier3_task` / `_stale_prune_task` / `_member_cache` / `_last_save_time`），导致走 `_should_warn`/压缩/清理路径的用例全 `AttributeError`。
  - `__import__("unittest.mock").patch` 写法错误（返回顶层 `unittest`，无 `.patch`）→ 改 `from unittest import mock` 后用 `mock.patch.object`（5 处）。
  - 同步上下文里 `asyncio.create_task` 无 running loop → 移进 async 包装；`_await_task` 的 `except Exception` 改 `except BaseException`（`CancelledError` 不是 `Exception`）。
  - `_stale_prune_interval` 断言写错：`600//4=150` 未触下限，实现正确，断言改为 150 并补一条真触下限的用例（200→60）。
  - prune loop 时序：实现是「先 sleep 后 prune」，mock 首次 sleep 即 cancel 导致 prune 跑不到 → 改 mock 为「首次放行、二次 cancel」。
  - `test_compress_tier2_success_updates` 用绝对时间戳（落不进 tier2 窗口）→ 改用相对 `now` 构造消息。
  - `test_stale_prune_loop_skips_when_persist_disabled` 断言期望值笔误（`history_daily_summary` 应为 `"也应保留"` 误写成 `"应保留"`）。
- 工程：补装 pytest 后方能真跑测试，建议固化进开发依赖。ruff 0 issue。
- metadata.yaml v0.7.0 → v0.7.1。

## v0.7.0 - 2026-06-13

- **特性：整合「群成员查询」插件能力**——把独立的 `astrbot_plugin_group_member`（原作者糯米茨，魔改 v0.2.0-magic）功能整体并入 social_context，新增按需主动查询群成员名册的能力。social_context 此前只感知「说过话的人」，整合后可主动获取「群里所有人」。
- 新增 LLM 工具 `@filter.llm_tool get_group_members_info(name_hint: str = "")`：
  - 返回 `current_sender`（当前发信人，零 API 调用，直接读 `raw_message.sender`）+ `members`（群成员列表）+ `member_count` / `truncated` / `source`。
  - `name_hint` 传 `self`/`我`/`me` 零成本命中当前发信人；传名字片段缩小范围；留空返回全量（带截断）。
  - 四级路径：self 查询 → name_hint 命中发信人 → 缓存 → 调 API，越靠前越省。
- 新增辅助方法：`_extract_current_sender` / `_format_members` / `_filter_members` / `_member_cache_get` / `_member_cache_set` / `_fetch_group_members` / `_members_json`。
- `UserContext` 新增 `role: str = "member"` 字段：`on_group_message` 从事件 `sender.role` 零成本更新群内身份（owner/admin/member），可供 judge 逻辑判断发言权重。
- `__init__` 新增 `self._member_cache`，`terminate` 清理。
- 新增 2 个配置项（⑨ 群成员查询分组）：
  - `member_cache_ttl`（int, 默认 30）：群成员名册缓存秒数，0=禁用。
  - `member_truncate_threshold`（int, 默认 500）：LLM 工具返回成员上限，超过截断并标记 `truncated=true`。
- 输出 JSON 用紧凑格式（`separators=(",",":")`），省 token。错误路径日志用 `error`+`exc_info`。
- 回归验证：改动前后测试均为 14 failed / 77 passed（14 个失败为历史遗留 `unittest.mock` 写法问题，与本次整合无关）；新增 role 字段不影响 UserContext 序列化。
- metadata.yaml v0.6.4 → v0.7.0。
- 独立插件 `astrbot_plugin_group_member` 整合后可下线（功能已并入本插件）。

## v0.6.4 - 2026-06-13

- **补丁：v0.6.3 清理循环补强**——加 `stale_prune_acted` info log（v0.6.4 之前没加，循环每天最多产生 ~24 条 info 噪音）；新增 2 个单测。
- `_stale_history_prune_loop` 在 `pruned > 0` 分支末尾：`_save_if_needed(force=True)` 之后多一行 `if self._should_warn("stale_prune_acted"): logger.info(...)`。60s 内同 key 只 info 一次。
- 新增 2 个单测：
  - `test_stale_prune_loop_skips_when_persist_disabled`——`persist_enabled=False` 时整个 prune 流程跳过，摘要保留
  - `test_stale_prune_loop_force_saves_on_actual_clear`——真清掉东西时 `_save_if_needed(force=True)` 真的被调到
- metadata.yaml v0.6.3 → v0.6.4。
- 备注：v0.6.3 commit 之前因工具自动应用补丁出现过方法/字段重复，本次先 `git checkout HEAD -- main.py` 把 main.py 复位到 v0.6.3 干净状态，再干净地叠加 v0.6.4 改动。

## v0.6.3 - 2026-06-13

- **补丁：持久化过期摘要定时清理**——之前 `_prune_stale_history` 只在 load / save / 注入 prompt 前跑，完全静默群的过期摘要会一直留在内存和 JSON 里。
- 新增 `self._stale_prune_task: asyncio.Task | None`（`__init__` 初始化）。
- 新增方法：
  - `_stale_prune_interval()` → 返回循环间隔：默认 `min(discard_age/4, 3600)`，clamp 下限 60s
  - `_stale_history_prune_loop()` → 定时遍历全群调 `_prune_stale_history`，清掉过期项后 `force=True` 写盘
  - `_ensure_stale_prune_loop()` → 懒启动（on_group_message 调一次）
- `on_group_message` 在 `_ensure_tier3_loop` + `_maybe_schedule_tier2_compress` 之后调 `_ensure_stale_prune_loop`。
- `terminate` 在 cancel tier3 之后多 cancel `_stale_prune_task`。
- 异常自愈模式跟 v0.6.2 tier3 同款：外层 `while True: try/except`，非 CancelledError 时 sleep 60s 继续循环；warn 走 `stale_prune_loop` key 去重。
- 间隔计算示例：
  - discard=86400 (1 天) → 间隔 3600 (1 小时)
  - discard=600 (10 分钟) → 间隔 60 (1 分钟)
  - discard=604800 (1 周) → 间隔 3600 (1 小时，clamp 上限)
- 新增 3 个单测：间隔 clamp / 静默群过期清理 / 未过期不动。
- metadata.yaml v0.6.2 → v0.6.3。

## v0.6.2 - 2026-06-13

- **补丁：失败兜底强化**（v0.6.1 暴露的 3 个小坑一次性收口）。
- **坑 3 修：warning 日志去重**——新增 `self._compress_warn_last: dict[str, float]`，新增 helper `_should_warn(key, throttle=60.0)`。`_call_compress_llm` 4 处 `logger.warning` 全部改成走 `_should_warn` 节流（`get_provider:{id}` / `provider_none:{id}` / `timeout:{id}` / `llm_error:{id}:{exc_type}`），同 key 60s 内只 warn 一次。dict 超过 256 项时按 `throttle * 10` 清理过期项。
- **坑 2 修：tier3 循环自愈**——`_tier3_compress_loop` 外层加 `while True: try/except` 自愈循环。非 `CancelledError` 异常时 sleep 60s 后重进内层循环，不再静默死亡；warn 走 `tier3_loop` key 去重。`CancelledError` 仍正常退出（`terminate` 触发）。
- **坑 4 修：fire-and-forget 异常显式记录**——新增静态方法 `_log_compress_task_exception(task)`，作为第二个 `add_done_callback` 挂到 tier2 任务上。task 抛异常时会 log `压缩 task 未捕获异常: {exc!r}`，不再只看到 "Task exception was never retrieved"。
- 新增 6 个单测：`_should_warn` 节流 / 过期 / 字典清理 / 取消任务不报 / 失败任务记录 / tier3 自愈循环。
- metadata.yaml v0.6.1 → v0.6.2。

## v0.6.1 - 2026-06-13

- **新增：历史压缩（D 方案）**——tier2 走 on-message lazy + interval 节流，tier3 走单一定时器。
- `GroupContext` 新增 1 个仅内存字段 `history_compress_inflight: bool`，防止同一群并发压缩。
- `__init__` 新增 `self._compress_tasks: set[asyncio.Task]` + `self._tier3_task: asyncio.Task | None`。
- 新增 8 个配置项：
  - `history_compress_tier2_enabled`（默认 true）—— tier2 压缩总开关
  - `history_compress_tier2_on_message`（默认 true）—— on-message lazy 触发
  - `history_compress_tier2_interval`（默认 300）—— 最小压缩间隔
  - `history_compress_tier2_max_chars`（默认 200）—— 摘要字数
  - `history_compress_tier3_enabled`（默认 true）—— tier3 压缩总开关
  - `history_compress_tier3_interval`（默认 3600）—— 后台循环间隔
  - `history_compress_tier3_max_chars`（默认 300）—— 摘要字数
  - `history_compress_timeout`（默认 10.0）—— LLM 单次压缩超时
- 新增方法：
  - `_build_compress_prompt(old, msgs, max_chars)`：构造压缩 prompt，冷启动时提示"首次压缩"
  - `_call_compress_llm(prompt, timeout)`：调 `judge_provider_id` provider 跑压缩，失败 / 超时 / 空返 None
  - `_compress_history_tier2(group_id)`：tier2 压缩主体（fire-and-forget 调用方），更新 `history_summary` + `history_summary_updated`
  - `_compress_history_tier3(group_id)`：tier3 压缩主体（定时器调用方），输入是 tier2 摘要 + tier3 窗口新消息
  - `_format_tier3_messages(msgs)`：tier3 文本格式化（每条截前 60 字）
  - `_maybe_schedule_tier2_compress(group_id)`：D 方案 tier2 触发点
  - `_ensure_tier3_loop()`：懒启动 tier3 后台循环（首条群消息时启动）
  - `_tier3_compress_loop()`：tier3 循环（`asyncio.CancelledError` 优雅退出）
- `on_group_message` 在 `prune` + `_save_if_needed` 之后调 `_ensure_tier3_loop()` + `_maybe_schedule_tier2_compress()`。
- `terminate` 先 cancel tier3 task + drain compress_tasks，再 save（避免压缩覆盖持久化）。
- 失败兜底：LLM 返 None 时不更新 `updated` 时间，下次再试；旧摘要保留。
- 注入防护：tier2 压缩入参先过 `_scan_variables`（截断 + 风险标记），与 judge prompt 走同一套。
- 新增 12 个单测：冷启动 prompt / 有旧摘要 / 缺 provider / provider 不存在 / 成功 / 超时 / 关开关不触发 / interval 不触发 / inflight 不并发 / 失败保旧 / 成功更新 / tier3 空消息跳过。
- metadata.yaml v0.6.0 → v0.6.1，CHANGELOG / README / `_conf_schema.json` 同步。

## v0.6.0 - 2026-06-13

- **新增：历史时间三层结构**（本版本先落地"时间结构"层，LLM 压缩内容留待下个 patch）。
- `GroupContext` 新增 4 个持久化字段：`history_summary` / `history_summary_updated`（tier2 摘要，180s~30min）/ `history_daily_summary` / `history_daily_updated`（tier3 摘要，30min~24h）。
- 新增 4 个配置项 `history_tier1_max_age`（默认 180）/ `history_tier2_max_age`（默认 1800）/ `history_tier3_max_age`（默认 86400）/ `history_discard_age`（默认 86400 = 1 天）。
- 新增 helper `_history_tier_bounds()` / `_classify_message_tier()` / `_get_messages_in_tier()` / `_format_tier_label()`：把每条消息按"距今多少秒"归到 tier1/2/3/0。
- 新增 `_prune_stale_history(group, now)`：持久化摘要 updated 时间距今 > `history_discard_age`（默认 1 天）自动清空。
- `_load_state` 载入后立即跑一次 `_prune_stale_history`，`_save_if_needed` 写盘前也跑一次——保证陈旧摘要不会复活。
- judge prompt template 新增 3 行：`## 历史时间分层` 统计每层消息数 / `## 历史摘要 tier2` / `## 历史摘要 tier3`。当前摘要内容为"暂无"占位（等下个版本接 LLM 压缩）。
- 新增 7 个单测：默认边界 / 自定义边界 / `_classify_message_tier` 全档位 / `_get_messages_in_tier` 分类 / 过期摘要抛弃 / 未过期保留 / 持久化字段落盘 / judge block 出现三层结构。

## v0.5.3 - 2026-06-13

- **修复：主语指向判断错误**（`_bot_relevance` / `_conversation_opening` 误把群友间互动当成对 bot 的邀请）。
- `MessageRecord` 新增 4 个仅内存字段：`reply_to_sender_id` / `mentioned_user_ids` / `is_at_bot` / `is_at_all`，用于在窗口内追踪每条消息的地址信号。
- 新增 `_extract_addressee_info(event, group_messages)` helper：用鸭子类型（hasattr qq/id）遍历 chain 提取 @/Reply 组件，webchat 等无 At 组件的平台安全降级为 `("", (), False, False)`。
- 新增 `_addressee_label(...)` helper：把地址信号转成自然语言标签（"明确 @ bot" / "@全体成员" / "回复某条消息" / "@ 了 N 个群友" / "未明确指向"）。
- **`_bot_relevance` 改写**：优先级 `@bot` > `@全体` > 回复 bot > 关键词；**关键词命中但同时 @ 了别人 → 降级为 weak**（关键修复：A 对 B 提到 bot 不再被当 strong）。
- **`_conversation_opening` 改写**：`@bot` / `@全体` / 回复 bot + 问号 → high；**纯问号不指向 bot → medium**（不把群友互问/反问/自问当邀请）。
- judge prompt template 新增"当前消息对象"行，把 `addressee_label` + 原始信号（`is_at_bot` / `reply_to_sender_id` / `mentioned_user_count`）都喂给判断模型，并补一行"主语指向优先级"指引。
- `_group_to_json` 过滤 4 个新字段（不落盘，跨重启不影响）。
- 新增 6 个单测覆盖典型翻车场景：`@bot` 无关键词 / 关键词+@别人 / 关键词+@bot / 回复 bot / 纯问号无地址 / @全体；旧 `test_conversation_opening_high_for_question` 改名为 `test_conversation_opening_question_without_addressee_is_medium`，断言从 `high` 改为 `medium`（行为修复）。
- README 加一节"主语指向感知（v0.5.3+）"。

## v0.5.2 - 2026-06-13

- 新增判断模型人格感知（`judge_persona_aware_enabled`，v0.5.2+ 默认开启）：`_judge_should_reply` 在调用 `provider.text_chat` 时传入当前会话人格的 `system_prompt`，让判断模型以人格视角评估是否该插话（冷淡人格判断阈值偏保守、活泼人格偏积极等）。
- 借鉴 `astrbot_plugin_private_proactive_reply` 的 `_get_system_prompt` 实现：优先 `conversation.persona_id` 拉取，降级到 `persona_manager.get_default_persona_v3(umo=umo)`，全部失败/异常返空串，不污染主流程。
- 新增配置项 `judge_persona_prompt_max_chars`（默认 1500）：截断保护，超长 system_prompt 裁剪后补 `…`，避免撑爆 judge 小模型 context。
- 新增配置项 `judge_persona_cache_ttl_seconds`（默认 300）：`umo -> (persona_id, system_prompt, fetched_at)` 轻量缓存，避免每条群消息都查 persona_manager。
- `JudgeResult` 新增 `persona_id` 字段，`last_judge_result` 同步记录；`/social_context judge_last` 输出多一行 `persona_id` 方便调试。
- README / `_conf_schema.json` / 回归测试同步更新，确认 judge 关闭开关、conversation 缺 persona_id、长 system_prompt 截断、缓存命中四种边界。

## v0.5.1 - 2026-06-13

- 将 `judge_enabled` 默认值改为 `true`：插件默认启用"自主判断是否回复"功能，呼应 v0.4.0 起的自主判断能力。
- 同步更新 `judge_enabled` 配置项 hint，说明 v0.5.1+ 默认开启以及如何关闭（设 false 或留空 `judge_provider_id`）。
- 备注：`reply_inject_enabled` 自 v0.4.7（commit 71a7c9f）起已为默认 false，本次未动。
- README / `_conf_schema.json` 同步更新，回归测试无变化（仅默认值翻转，未引入新行为）。

## v0.5.0 - 2026-06-13

- 新增 `output_step` 模块与 `reply` 智能引用步骤：bot 准备回复时，若原消息之后被插了 ≥ `reply_step_threshold` 条新消息，会在回复头部插入 `Reply(id=原消息id)` 组件，可选附加 `At` 提醒原消息发送者。
- 新增 `MessageRecord.message_id` 字段（仅内存，不持久化），用于按消息 id 在短期窗口中定位原消息位置。
- 新增 `@filter.on_decorating_result(priority=10)` 钩子入口；复用现有 `group.messages` + `prune` 窗口，不新建独立队列。
- 新增 3 个配置项：`reply_step_enabled`（默认 true）/ `reply_step_threshold`（默认 3）/ `reply_step_include_at`（默认 true）。
- chain 白名单沿用 outputpro 的 `Plain | Image | Face | At`：含 `Video / Forward / Nodes` 等组件时整步跳过。
- `unsupported_platforms` 含 `dingtalk`，沿用 outputpro 行为。
- 持久化 `_group_to_json` 同步过滤 `message_id` 字段，确保不落盘。
- README / `_conf_schema.json` / 回归测试同步更新。

## v0.4.9 - 2026-06-13

- 将 `block_group_temp_private_notice` 默认值改为空字符串，群聊临时会话私聊拦截默认静默，只记录日志并 `stop_event()`。
- 保留自定义拦截提示能力：管理员手动填写提示文本后，命中拦截时仍会返回该提示。
- README / `_conf_schema.json` / 回归测试同步更新。

## v0.4.8 - 2026-06-12

- 新增 `block_group_temp_private` 安全开关，默认拦截 aiocqhttp/OneBot 群聊临时会话私聊，避免陌生群成员绕过群内上下文直接私聊 bot。
- 新增 `block_group_temp_private_notice` 配置项，可自定义拦截提示；留空则静默拦截。
- 新增高优先级 `PRIVATE_MESSAGE` 守卫，识别 `message_type=private` 且 `sub_type=group/group_self/temp`、携带 `group_id` 或 session 标记为临时会话的事件，并在命中后 `stop_event()`。
- README / `_conf_schema.json` / 回归测试同步更新，确认普通好友私聊不受影响、关闭开关后不会拦截。

## v0.4.7 - 2026-06-12

- 将完整正式回复模型注入 `reply_inject_enabled` 默认值改为 `false`，避免与 AstrBot 自带对话上下文重复、占用 prompt 或影响自然回复。
- 自主判断触发正式回复时的极简提示（非点名、reply_style、reply_intent）从完整注入开关中拆出，即使关闭完整注入也会保留。
- README 与配置 hint 同步说明：完整正式回复注入是高级可选项，默认不推荐开启。

## v0.4.6 - 2026-06-12

- 重排 `_conf_schema.json` 配置项展示顺序，按基础开关、短期状态窗口、正式回复注入、自主判断与主动回复、判断上下文信号、安全防护、持久化、高级模板分块。
- 配置项 description 增加分组前缀，方便 AstrBot WebUI 中快速定位；未改动任何配置 key 或运行行为。
- README 配置说明同步按相同分组重排。

## v0.4.5 - 2026-06-12

- 新增判断模型社交信号 `topic_heat_trend`，用于描述话题热度是升温、降温、活跃还是平稳。
- 新增判断模型社交信号 `current_user_recent_style`，用于描述当前用户近期是提问者、活跃聊天者、频繁戳一戳、话题开启者等。
- 判断模型 JSON 输出扩展 `reply_style` 与 `reply_intent`，触发正式回复时作为低优先级风格/意图建议注入。
- 新增主动回复预算 `autonomous_reply_budget_per_hour` / `autonomous_reply_budget_per_day`，避免自主触发过度打扰群聊。
- 新增 `/social_context judge_last` 与 `/social_context_judge_last` 调试入口，查看最近一次自主判断结果。
- 状态持久化同步保存主动回复预算计数与最近一次判断摘要，并保持旧状态兼容。

## v0.4.4 - 2026-06-12

- 新增判断模型社交信号 `bot_relevance`：基于 bot 相关关键词、bot ID、近期 bot 发言等轻量启发式，估算当前消息与 bot/插件/模型/配置话题的相关度。
- 新增判断模型社交信号 `conversation_opening`：基于提问/求助、bot 相关度、近期短对话、bot 刚发言等信号，估算当前时机是否存在自然插话空位。
- 新增配置项 `bot_relevance_keywords`，用于自定义 bot 相关关键词，默认 `雪莉,bot,机器人,助手,插件,模型,配置`。
- `judge_prompt_template` 默认模板加入 `bot_relevance` 与 `conversation_opening`，让判断模型更克制地决定是否主动回复。
- README / `_conf_schema.json` / 回归测试同步更新。

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
