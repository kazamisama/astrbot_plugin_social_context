# Social Context 群聊状态感知层

> AstrBot 插件 · 平台 `aiocqhttp` · AstrBot >= 4.13.0 · 当前版本 v0.9.1

插件维护每个群的**短期氛围、互动事件、用户熟悉度**和**分层历史摘要**，在需要时把一段低噪声的社交上下文交给 LLM；也可以自己判断「现在适不适合插一句话」。

定位是**社交信号层**，不是聊天记录库：它只回答「这个群现在什么气氛、谁在跟谁说话、bot 该不该开口」，不代替 AstrBot 自带的对话上下文。

---

## 目录

- [主要能力](#主要能力)
- [安装与快速开始](#安装与快速开始)
- [配置项总览](#配置项总览)
- [工作机制](#工作机制)
- [模板与占位符](#模板与占位符)
- [状态与持久化](#状态与持久化)
- [命令](#命令)
- [故障排查](#故障排查)
- [开发与测试](#开发与测试)
- [版本与兼容](#版本与兼容)

---

## 主要能力

- **状态观察**：维护最近窗口内的消息数、活跃用户、最近发言者、戳一戳事件、今日互动与简单熟悉度。
- **分层历史**：tier1 保留原文（默认 3 分钟）、tier2 压缩成摘要（默认 30 分钟）、tier3 压缩成更早期摘要（默认 24 小时），解决「bot 失忆」。
- **正式回复注入**（默认关闭）：把群氛围观察注入主回复 LLM，属于可选的高级选项。
- **自主判断**（v0.5.1+ 默认开启）：用一个便宜的判断模型决定「该不该主动插话」，命中阈值后触发正式回复链路。
- **精力感知**（v0.8.13+，可选）：接入情绪状态机插件的精力值，疲劳时降低主动回复意愿、收敛语气。
- **情绪状态机桥接**（v0.8.0+，可选）：把用户消息喂给情绪引擎，并让判断模型带着情绪状态做决策。
- **智能引用**（v0.5.0+）：bot 准备回复时，若原消息之后被插了很多新消息，在回复头部补一个引用，避免上下文错位。
- **群成员查询工具**：给 LLM 一个 `get_group_members_info` 工具，按需查询群名片 / QQ 名 / QQ 号 / 群内身份。
- **群聊临时会话拦截**：阻止群成员通过「群临时会话」绕过群上下文私聊 bot。
- **统一的入口闸门**（v0.9.0+）：所有入口都受 `enabled` 与 `group_whitelist` 约束；状态按 TTL 与条数上限自动淘汰。

---

## 安装与快速开始

1. 把插件目录放进 AstrBot 的插件目录（或在插件市场安装），重启 AstrBot。
2. 到插件配置里填 **群聊白名单** `group_whitelist`，例如 `["123456789"]`。
   - 这里要填**纯数字群号**，不要填 `xxx:GroupMessage:123456789` 这类带标识的字符串。
   - **留空 = 对所有群都不生效**（v0.8.24 起）。插件不会报错，但什么都不会做；v0.9.0 起启动日志会给出明确提示。
3. 如果想用自主判断，再配置 `judge_provider_id`（建议选快速、便宜的模型）。
4. 在群里发 `/social_context` 验证：能看到窗口消息数、活跃用户、bot 上次发言时间等信息即已生效。

私聊**不受**群白名单约束；是否在私聊注入上下文由 `only_group` 决定（默认 false，即私聊也会注入）。

---

## 配置项总览

配置面板按 10 个分组组织。下面列出全部配置项与默认值。

### 1. 基础（basic）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `enabled` | `true` | 插件总开关。关闭后不监听、不注入、不判断、不保存状态，命令也静默返回。 |
| `only_group` | `false` | 仅群聊注入。开启后私聊跳过注入；注意消息观察钩子本身只处理群消息，不受本项影响。 |
| `group_whitelist` | `[]` | 群白名单，纯数字群号。留空表示对所有群都不生效。 |

### 2. 群聊状态观察（state_observation）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `window_seconds` | `60` | 短期状态窗口（秒），统计最近这么多秒内的消息与戳一戳。 |
| `active_message_threshold` | `6` | 活跃阈值：窗口消息数达到该值且至少 2 人参与，判为「群聊较活跃」。 |
| `quiet_message_threshold` | `1` | 安静阈值：窗口消息数小于等于该值，判为「群聊偏安静」。 |
| `familiarity_message_gain` | `0.4` | 每发一条消息增加的熟悉度。 |
| `familiarity_poke_gain` | `0.8` | 每戳一次增加的熟悉度。 |

### 3. 正式回复注入（reply_injection）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `reply_inject_enabled` | `false` | 把完整群聊观察注入主回复 LLM（高级选项）。通常 AstrBot 自带上下文已经够用，默认关闭。旧配置项 `inject_enabled` 仍作为兼容读取。 |
| `inject_cd` | `20.0` | 同一会话的注入间隔（秒），避免每条消息重复注入。 |
| `reply_prompt_template` | 见模板章节 | 群聊观察注入模板。 |
| `triggered_reply_hint_template` | 见模板章节 | 自主触发时注入主回复 LLM 的风格提示，不受 `reply_inject_enabled` 影响。 |

### 4. 自主判断与主动回复（judge）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `judge_enabled` | `true` | 是否启用自主判断。v0.5.1+ 默认开启；不需要请关闭。 |
| `judge_provider_id` | 空 | 判断模型提供商：填一个 chat 类型 provider 的实例 ID。留空则不会发生判断（启动时会有一次提示）。 |
| `judge_reply_threshold` | `0.65` | 置信度阈值：`should_reply=true` 且 `confidence` 达到该值才触发。 |
| `judge_min_reply_interval` | `60.0` | 同一会话两次主动回复的最小间隔（秒）。 |
| `autonomous_reply_budget_per_hour` | `3` | 每小时主动回复预算；0 = 不限制。直接 @ / 唤醒不计入。 |
| `autonomous_reply_budget_per_day` | `20` | 每日主动回复预算；0 = 不限制。 |
| `judge_max_retries` | `1` | 判断模型返回非法 JSON 时的重试次数。 |
| `judge_persona_aware_enabled` | `true` | 判断模型人格感知：运行时读取当前会话人格的 system_prompt，让它以同一人格视角判断。 |
| `judge_persona_prompt_max_chars` | `10000` | 人格提示词截断保护。 |
| `judge_persona_cache_ttl_seconds` | `300` | 人格拉取缓存 TTL（秒），避免每条消息都查人格；0 = 禁用缓存。 |
| `judge_context_max_age` | `180` | 判断上下文的时间范围（秒）。 |
| `judge_context_recent_lines` | `8` | 喂给判断模型的最近对话原文条数，帮助它锚定「你 / 他」到底指谁；0 = 关闭。 |
| `bot_relevance_keywords` | 见下 | 逗号分隔的关键词列表，用于估算消息与 bot 的相关度。默认是一组常见称呼（bot / 机器人 / 助手 / 插件 / 模型 / 配置 等）。**建议把 bot 自己的昵称加进去**。 |
| `judge_energy_gate_enabled` | `true` | 精力硬门槛：精力低于阈值时直接跳过判断模型调用（零 token 消耗）。 |
| `judge_energy_gate_threshold` | `0.2` | 精力门槛阈值，0.0～1.0。 |
| `judge_energy_inject_enabled` | `true` | 把 bot 当前精力注入判断 prompt（`{bot_energy}`）。 |
| `judge_prompt_template` | 见模板章节 | 判断上下文模板，填充 `{context_block}`。 |
| `judge_decision_prompt` | 见模板章节 | 最终发给判断模型的外层包装 prompt。 |

### 5. 历史分层与压缩（history）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `history_tier1_max_age` | `180` | tier1 边界（秒），完整消息列表。建议不超过 `judge_context_max_age`。 |
| `history_tier2_max_age` | `1800` | tier2 边界（秒），默认 30 分钟。 |
| `history_tier3_max_age` | `86400` | tier3 边界（秒），默认 24 小时。 |
| `history_discard_age` | `86400` | 摘要超过该年龄自动清空（载入 / 写入 / 注入前都检查）。 |
| `history_max_messages` | `2000` | 内存中供压缩使用的历史原文上限，不落盘。 |
| `history_compress_tier2_enabled` | `true` | tier2 压缩总开关；需要配置 `judge_provider_id` 才真正生效。 |
| `history_compress_tier2_on_message` | `true` | 消息进入时按需压缩（fire-and-forget），不阻塞消息处理。 |
| `history_compress_tier2_interval` | `300` | tier2 最小压缩间隔（秒）。 |
| `history_compress_tier2_max_chars` | `200` | tier2 摘要目标字数。 |
| `history_compress_tier3_enabled` | `true` | tier3 压缩总开关。 |
| `history_compress_tier3_interval` | `3600` | tier3 后台循环间隔（秒）。 |
| `history_compress_tier3_max_chars` | `300` | tier3 摘要目标字数。 |
| `history_compress_timeout` | `30.0` | 单次压缩的 LLM 超时（秒），超时视作失败并保留旧摘要。 |

### 6. 输出微调（output_step）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `reply_step_enabled` | `true` | 启用智能引用。 |
| `reply_step_threshold` | `3` | 原消息之后被插多少条新消息才补引用；0 = 关闭。 |
| `reply_step_include_at` | `true` | 补引用时再 @ 原消息发送者（仅 aiocqhttp 生效）。 |

### 7. 群成员查询工具（tools）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `member_cache_ttl` | `30` | 群成员名册缓存（秒）；0 = 每次都调用 API。 |
| `member_truncate_threshold` | `500` | 工具单次返回的成员上限，超出会截断并标记 `truncated=true`。 |

### 8. 情绪状态机集成（emotion_bridge）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `emotion_observe_enabled` | `true` | 把用户消息喂给情绪引擎（bot 自己的消息不喂，避免自反馈）。 |
| `emotion_judge_inject_enabled` | `true` | 把情绪状态块拼进判断模型 prompt。 |

### 9. 安全防护（safety）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `judge_prompt_injection_scan_enabled` | `true` | 扫描进入判断模型的用户可控字段，命中片段用 `<INJECTION_RISK>` 包裹。 |
| `block_group_temp_private` | `true` | 拦截由群聊入口发起的临时会话私聊；普通好友私聊不受影响。 |
| `block_group_temp_private_notice` | 空 | 拦截时回给对方的提示；留空即静默拦截。 |

### 10. 持久化（persistence）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `persist_enabled` | `true` | 是否把状态保存为 JSON。关闭后仅内存保留。 |
| `state_path` | 空 | 自定义状态文件路径；留空用默认路径。 |
| `save_interval` | `60` | 普通消息触发的最小写盘间隔（秒）；戳一戳会强制保存。 |
| `state_group_ttl` | `604800` | 群状态空闲多久（秒）后整条淘汰；0 = 不淘汰。 |
| `state_user_ttl` | `604800` | 用户状态空闲多久（秒）后淘汰；0 = 不淘汰。 |
| `state_user_max` | `5000` | 用户状态条数上限，超出按最近活动保留；0 = 不限制。 |

---

## 工作机制

### 状态观察

插件监听两类事件，都只对群消息生效：

- **群消息**（`on_group_message`）：记录发送者、内容、时间戳；bot 自己的消息也会记录（v0.8.23+），但不计入活跃用户与「最近发言者」。
- **戳一戳**（`on_group_poke`）：解析 `notice_type=notify` + `sub_type=poke`，记录发送者与目标，并给双方的熟悉度加分。

窗口内的消息数决定氛围标签：

| 条件 | 氛围 |
|---|---|
| 消息数 ≥ `active_message_threshold` 且活跃人数 ≥ 2 | 群聊较活跃 |
| 消息数 ≤ `quiet_message_threshold` | 群聊偏安静 |
| 其他 | 群聊有零散交流 |

今日消息数、戳一戳次数、主动回复次数等计数每天按本地时间自动归零。

### 三层历史结构

| 层级 | 时间范围（默认） | 内容 |
|---|---|---|
| tier1 | 0 ~ 180 秒 | 完整消息原文 |
| tier2 | 180 秒 ~ 30 分钟 | LLM 压缩摘要 |
| tier3 | 30 分钟 ~ 24 小时 | LLM 压缩摘要（含上一层的信息） |

压缩触发方式：

- **tier2**：每条群消息进来时检查「距上次压缩超过 `history_compress_tier2_interval` 且窗口里有新内容」，满足则起一个后台任务压缩，不阻塞消息处理。
- **tier3**：插件启动后由单一后台循环按 `history_compress_tier3_interval` 遍历所有群。
- **失败兜底**：LLM 返回空 / 超时时不更新时间戳，保留旧摘要下次再试；同一群同时只允许一个压缩任务。
- **冷启动**：没有旧摘要时，prompt 走「首次压缩」分支。
- **注入防护**：压缩的输入也要经过注入扫描，避免摘要被污染后又被注入到判断模型。

摘要过期（超过 `history_discard_age`）会在载入、写盘和注入前被清空；`history_max_messages` 只限制内存中的原文缓冲，不落盘。

### 正式回复注入

`reply_inject_enabled=true` 时，正式回复请求前会把 `reply_prompt_template` 渲染出的观察块追加到 prompt；同一会话 `inject_cd` 秒内不重复注入。

默认关闭的原因：AstrBot 自带最近对话上下文，重复的统计信息既占 prompt 又容易让回复变得不自然。

### 自主判断与主动回复

每个群消息（不含直接 @ / 唤醒）依次经过：

1. `judge_enabled` 与群白名单闸门。
2. 每小时 / 每日预算检查（预演不消耗）。
3. 冷却检查（`judge_min_reply_interval`）。
4. 精力硬门槛（低于 `judge_energy_gate_threshold` 直接跳过，零 token）。
5. 调用判断模型：把社交上下文、当前消息、最近对话原文、人格、精力一起给它。
6. 判断模型返回 JSON：`should_reply` / `confidence` / `reply_style` / `reply_intent` / `reasoning`。
7. `should_reply=true` 且 `confidence` 达到 `judge_reply_threshold` 才真正消耗预算、通知情绪引擎打 self-reply signal、设置唤醒标记，让 AstrBot 走正式回复链路。

判断上下文里有两个轻量信号：

- `bot_relevance`：当前消息与 bot / 插件 / 模型 / 配置等话题的相关度（`none` / `weak` / `medium` / `strong`）。
- `conversation_opening`：当前是否存在适合自然插话的社交空位（`none` / `low` / `medium` / `high`）。

两者只辅助判断，不直接触发回复，也不会出现在默认的主回复模板里。

`judge_persona_aware_enabled=true` 时，判断模型还会收到当前会话人格的 system_prompt（优先会话绑定人格，失败回落到默认人格，全失败则留空），让冷淡人格偏保守、活泼人格偏积极。`/social_context judge_last` 会显示本次使用的人格 id。

#### 判断模型怎么选

`judge_provider_id` 填 AstrBot 里任意 **chat 类型**的 provider（`chat_completion`）。判断模型要做的事很简单：读一段上下文，返回一个 JSON 对象。插件对缺字段有默认值（`reasoning` 缺省为空、`reply_style` 缺省 `short`、`reply_intent` 缺省 `join_topic`），只要模型能稳定吐出 JSON 就算接通。

**推荐用低成本大模型。** 每条群消息都可能触发一次判断（受预算、冷却、精力三道闸门约束），prompt 里带着历史摘要和最近对话原文，用旗舰模型的成本与延迟不划算；小参数 chat 模型或低价档通常就够。模型选择比插件本身更影响主动回复像不像人，建议拿自己的群聊记录实测。

**不直接支持决策模型**（Jev 的 `typesafe/jev-*`、OpenAI 的 `gpt-6-luna` 这类 Decisions API）。它们走独立的 typed decisions 协议（`POST /v1/systemone` 或 `POST /v1/decisions`，用 `state`/`input` 加 `questions` 请求 `noul` / `choice` / `score` 答案），不是 chat completions，AstrBot 也没有对应类型的 provider，所以填不进 `judge_provider_id`。要接得单独写一个 provider 适配器，把 answers 序列化成 JSON 文本交给 `text_chat`；另外决策模型不返回自由文本理由（`/social_context judge_last` 的「理由」会为空），人格与情绪注入对它也没有意义。

### 精力感知（v0.8.13+）

精力值来自情绪状态机插件的 `get_bot_energy()`，范围 0.0～1.0（1.0 = 充沛）。三层机制叠加：

| 层 | 配置 | 行为 |
|---|---|---|
| 硬门槛 | `judge_energy_gate_enabled` + `judge_energy_gate_threshold` | 低于阈值直接跳过判断模型调用，零 token 消耗。 |
| 软注入 | `judge_energy_inject_enabled` | 精力值作为 `{bot_energy}` 注入判断 prompt，让模型自行降权。 |
| 语气收敛 | `triggered_reply_hint_template` | 自主触发时把精力告诉主回复 LLM，偏低时语气更短更懒散。 |

情绪状态机不可用（未装 / 未注册 / 无该方法 / 抛异常）时，精力机制完全静默：硬门槛放行，软注入按 1.00 占位。

### 情绪状态机桥接（v0.8.0+）

情绪状态机插件（ESM）是**可选依赖**，缺失时所有接入点静默降级，主流程不受影响。

| 接入点 | 位置 | 行为 |
|---|---|---|
| 观察消息 | `on_group_message` | 把用户原文喂给 ESM 的 `observe_text`（bot 消息不喂）。 |
| 判断注入 | `_judge_should_reply` | 主路径用 ESM v0.10.0+ 的 `to_text_part` 生成独立 TextPart；老版本降级用 `build_prompt_block` 拼字符串。 |
| 自回复信号 | `_maybe_trigger_autonomous_reply` | 判断为「该回复」后调用 ESM 的 `apply_self_reply_signal(event)`，由 ESM 自己打 signal。 |

两个插件的 scope 优先取 ESM 的 `get_scope(event)`，保证读写同一份状态；ESM 不可用时回落到 social context 自己的会话标识。

### 智能引用（v0.5.0+）

在 `on_decorating_result` 阶段（发送前、priority 10）对回复链做一次轻量微调：

- 触发条件：原消息之后被插了不少于 `reply_step_threshold` 条新消息（只看窗口内的消息）。
- 动作：在回复头部插入 `Reply` 组件指向原消息；`reply_step_include_at=true` 时再插入 `At`（仅 aiocqhttp）。
- chain 白名单：`Plain` / `Image` / `Face` / `At`。出现 `Video` / `Forward` / `Nodes` 等组件时整步跳过。
- 平台：`dingtalk` 不支持，跳过。
- 修改发生在发送前，不影响 LLM 生成过程。

### 主语指向感知（v0.5.3+）

解决「群友互聊时提到 bot 关键词或用了问句，bot 误以为在叫自己」。每条消息的地址信号在需要时现算，不挂在消息记录上：

| 场景 | bot 相关度 / 插话空位 |
|---|---|
| 消息里提到 bot 昵称，但没有 @ | 相关度保留，插话空位中等 |
| @ 了别的群友，同时提到 bot 关键词 | 相关度降为 weak |
| @ bot / 回复 bot | 相关度 strong，插话空位 high |
| @ 全体 | 相关度 strong |

判断 prompt 顶部会多一行「当前消息对象」，把「明确 @ bot」「@全体成员」「回复某条消息」「@ 了 N 个群友」「未明确指向」直接告诉判断模型，并在模板里给出相应的置信度指引。

### Prompt 注入防护

进入**判断模型**的用户可控字段会做一层数据扫描：`sender_name`、`sender_id`、`message`，以及上下文块里的 `recent_speakers`、`latest_poke_sender`、`latest_poke_target`、`current_user_name`、`recent_dialog`、历史摘要等。命中片段用 `<INJECTION_RISK>` 与 `</INJECTION_RISK>` 包裹，并提示模型视作不可信输入。

覆盖的典型形态：中文的「忽略以上指令 / 你现在是 / 你扮演」，英文的 `system:` / `assistant:` / `user:` 伪装，`<|im_start|>` 之类的 chat template token，`--- END SYSTEM ---` 分隔符，`[系统消息]` / `[管理员]` 标签，`IMPORTANT:` / `DO NOT IGNORE` 等。

正式回复模型**不会**收到这些标记，避免回复阶段出现噪声。关闭开关后只剩模板里的提示词防御，不推荐。

### 群成员查询工具

LLM 工具 `get_group_members_info(name_hint="")`：

- 返回字段：`group_id`、`current_sender`、`members`、`member_count`、`truncated`、`source`，出错时返回 `error`。
- 每个成员含 `user_id`、`display_name`（群名片）、`username`（QQ 名）、`role`（群内身份）。
- `name_hint` 传 `self` / `我` / `me` 等时，直接从消息事件里取出当前发信人，**零 API 调用**。
- 传名字片段时按群名片 / QQ 名 / QQ 号过滤；留空返回全量（按 `member_truncate_threshold` 截断）。
- 结果按 `member_cache_ttl` 缓存，缓存命中时不再请求 API。

工具同样受 `enabled` 与群白名单约束，且只支持 aiocqhttp 平台。

### 群聊临时会话拦截

`block_group_temp_private=true` 时，拦截「从群聊入口发起的临时会话私聊」，防止陌生群成员绕过群上下文直接私聊 bot。普通好友私聊不受影响。`block_group_temp_private_notice` 留空则静默拦截，填写后会把提示回给对方。

---

## 模板与占位符

### 四个可编辑模板

| 模板 | 配置分组 | 注入目标 | 用途 |
|---|---|---|---|
| `reply_prompt_template` | reply_injection | 主回复 LLM | 群聊观察注入（仅 `reply_inject_enabled=true`） |
| `triggered_reply_hint_template` | reply_injection | 主回复 LLM | 自主触发时的风格提示 |
| `judge_prompt_template` | judge | 判断模型 | 上下文块，填充进 `{context_block}` |
| `judge_decision_prompt` | judge | 判断模型 | 外层包装，含当前消息、精力、输出格式要求 |

### 可用占位符

观察类模板与判断上下文模板共享同一套变量：

```text
scope / group_id            会话标识与群号
window_seconds             统计窗口（判断上下文里等于 judge_context_max_age）
vibe                       氛围标签
message_count              窗口消息数
active_user_count          活跃人数
recent_speakers            最近较活跃的人（最多 3 个）
recent_dialog              最近 N 条对话原文
poke_count                 窗口内戳一戳次数
latest_poke_sender/target  最近一次戳一戳的双方
last_bot_reply_elapsed     bot 上次发言距今
current_user_id/name       当前发言者
current_user_message_count_today / poke_sent_today / poke_received_today
current_user_familiarity   当前发言者熟悉度
bot_relevance(_reason)     bot 相关度及理由
conversation_opening(_reason)     插话空位及理由
topic_heat_trend(_reason)  话题热度趋势及理由
current_user_recent_style(_reason) 当前用户近期风格及理由
addressee_label            当前消息对象（主语指向标签）
is_at_bot / is_at_all      是否 @ bot / @ 全体
reply_to_sender_id         回复链指向
mentioned_user_count       @ 了几个群友
history_tier1/2/3_max_age  三层时间边界
history_tier1/2/3_message_count  各层消息数
history_summary_tier2(_label)    tier2 摘要及时间标签
history_summary_tier3(_label)    tier3 摘要及时间标签
```

判断专用（`judge_decision_prompt`）：

```text
context_block    由 judge_prompt_template 渲染出的上下文块
sender_name      当前消息发送者昵称
sender_id        当前消息发送者 QQ 号
message          当前消息内容
threshold        触发阈值（judge_reply_threshold）
bot_energy       当前精力（ESM 不可用时为 1.00 占位）
```

自主触发提示专用（`triggered_reply_hint_template`）：

```text
style       判断模型给出的回复风格
intent      判断模型给出的回复意图
bot_energy  当前精力
```

未知占位符会原样保留；模板格式错误（例如 JSON 示例里的大括号没写成双大括号）时会自动回退到默认模板，不影响主流程。

### 旧默认模板的自动升级

v0.9.0 起不再在代码里保存旧版默认模板，只保留它们的 sha1 摘要：配置文本如果**恰好等于**某个旧版内置默认模板，会自动升级为当前默认模板；自定义过的文本原样保留，不会被覆盖。

---

## 状态与持久化

- 默认路径：AstrBot 数据目录下的 `plugin_data/astrbot_plugin_social_context/social_context_state.json`（由 `StarTools.get_data_dir()` 解析），可用 `state_path` 覆盖。
- 普通消息触发写盘的最小间隔是 `save_interval`（默认 60 秒）；戳一戳会强制保存；重置命令和过期淘汰也会立即保存。
- 载入时**逐条容错**：某条群状态或用户状态解析失败只跳过那一条，其余照常载入；未知字段会被忽略（兼容旧版本文件）；整个文件读不出或不是 JSON 对象时，从空状态开始并记一条 warning。
- 读取状态不会创建条目：构造 prompt 时用只读方式取用户状态，看到陌生人不等于把他永久写进状态文件。
- 群状态按会话隔离；开启人格隔离时同一群的不同人格各自独立。

### 状态淘汰（v0.9.0+）

长期运行的实例如果只增不删，状态文件会越来越大、每次落盘也越来越慢。以下三项控制淘汰：

| 配置 | 默认 | 行为 |
|---|---|---|
| `state_group_ttl` | 7 天 | 群状态最后一次活动距今超过该值，整条删除 |
| `state_user_ttl` | 7 天 | 用户状态最后互动超过该值，删除 |
| `state_user_max` | 5000 | 用户条目超过上限时按最近活动保留 |

「活动」取消息、戳一戳、摘要更新、bot 发言里最新的时间戳；带戳一戳的用户不会仅因为没说话就被清掉。淘汰与持久化开关无关：关闭持久化时内存状态也会照常淘汰。

---

## 命令

| 命令 | 权限 | 作用 |
|---|---|---|
| `/social_context` | 普通 | 查看当前会话状态：窗口消息数、戳一戳、活跃用户、氛围、bot 上次发言、今日统计 |
| `/social_context judge_last` | 普通 | 查看最近一次自主判断（是否触发、置信度、风格、意图、人格、理由） |
| `/social_context_judge_last` | 普通 | 同上，独立命令形式 |
| `/social_context_reset` | 管理员 | 重置当前会话的状态并立即写盘 |

四个命令都受 `enabled` 与群白名单约束：白名单外会回复「当前会话未启用 social_context」，插件关闭时静默返回。

---

## 故障排查

**插件装了但什么都不做**

1. 确认 `enabled` 为 true。
2. 确认 `group_whitelist` 里填了当前群号（纯数字）。留空等于对所有群不生效；v0.9.0 起启动日志会提示。
3. 确认平台是 aiocqhttp。
4. 在群里发 `/social_context`，看是否返回「当前会话未启用 social_context」。

**bot 从不主动回复**

1. 检查 `judge_enabled` 与 `judge_provider_id`（留空则不会发生判断，启动日志会提示一次）。
2. 用 `/social_context judge_last` 看最近一次判断结果：是否触发、置信度多少、理由是什么。
3. 如果理由里出现「自主回复预算不足」「冷却中」「精力不足」，属于预期行为，可调整预算、间隔或精力门槛。
4. 直接 @ 或唤醒不会计入预算，也不走自主判断。

**历史摘要一直是「暂无」**

1. 压缩依赖 `judge_provider_id`，没配就不会调用 LLM。
2. 确认 `history_compress_tier2_enabled` / `history_compress_tier3_enabled` 开着。
3. tier2 需要窗口里真的有新消息，且距上次压缩超过 `history_compress_tier2_interval`。

**状态文件损坏或读不出来**

插件会跳过坏条目继续启动；如果整份文件不可用，删掉它即可，插件会从空状态重建（不会影响 bot 正常运行）。

**私聊被拦截**

对方是通过「群临时会话」发起的私聊，被 `block_group_temp_private` 拦了。需要放行就关掉这一项；想提示对方可以填 `block_group_temp_private_notice`。

---

## 开发与测试

插件按领域拆成多个模块，`main.py` 只保留插件类与全部事件钩子。模块职责与硬性契约（钩子位置、依赖方向、状态归属、配置入口、数据目录）见 [DEVELOPMENT.md](DEVELOPMENT.md)。

| 模块 | 职责 |
|---|---|
| `main.py` | 插件类、事件钩子、配置访问器、注入与判断编排、命令 |
| `models.py` | 数据结构与共享纯函数 |
| `prompt_security.py` | 注入扫描与变量扫描 |
| `mixins/` | 状态持久化、历史压缩、群成员查询、情绪桥接 |
| `output_step/` | 智能引用输出微调 |
| `tests/` | 单元测试与钩子集成测试 |

运行测试（需要 AstrBot 自带的 Python 环境，测试会导入 AstrBot 的模块）：

```bash
python -m pytest tests -q
```

代码风格检查：

```bash
python -m ruff check .
```

---

## 版本与兼容

- 当前版本 v0.9.1，完整变更见 CHANGELOG.md。
- 平台支持：aiocqhttp（QQ）。
- AstrBot 版本要求：>= 4.13.0。
- 情绪状态机插件（astrbot_plugin_emotion_state_machine）为可选依赖：未安装时情绪与精力相关功能静默降级，其余功能不受影响；完整功能建议 v0.10.0+。

