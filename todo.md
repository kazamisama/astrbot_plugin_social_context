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
- 2026-07-03 v0.8.16 适配 ESM v0.10.3 async 化已 push ✓
- **当前 main 头：v0.8.16**
- §3 已定论：观察期无 bug，且当前 design 不需要该重构
- 精力机制贯穿：judge 决策层（硬门槛 + 软注入）+ 主回复 LLM 语气层（triggered_reply_hint_template）
- §4 P0 修复（async 对齐 + scope 对齐）已发 v0.8.16，175/0 干净

---

## 4. 已知风险：scope 对齐 & ESM 异步化（v0.8.16 必修）

> 发现日期：2026-07-03
> 来源：扫 ESM v0.10.3 async 化的连带影响时发现
> 关联：ESM v0.10.3（commit `ff6c16c`）、ESM v0.10.2（commit `8693dd0`）

### 4.1 现状诊断

#### 代码事实

`mixins/emotion_bridge.py:74-91` 已有 `_emotion_scope(event)`：

```python
def _emotion_scope(self, event: object) -> str:
    emo = self._get_emotion_plugin()
    if emo is not None:
        try:
            getter = getattr(emo, "get_scope", None)
            if getter is not None:
                return str(getter(event))      # ← 优先调 ESM.get_scope
        except Exception:
            pass
    return self._scope_id(event)               # ← 降级本地
```

**但 main.py 只有 1 处用 `_emotion_scope`（`main.py:725` 喂消息），5 处仍直接用本地 `_scope_id(event)`：**

| 位置 | 行号 | 用途 |
|---|---|---|
| `main.py:1077` | `scope = self._scope_id(event)` | judge / on_message 旁路 |
| `main.py:1154` | 同上 | on_llm_request scope 计算 |
| `main.py:1196` | 同上 | 自主触发 scope |
| `main.py:1227` | 同上 | 自主回复 scope |
| `main.py:1287` | 同上 | judge 前置 scope |
| `main.py:1444` | `"scope": self._scope_id(event),` | HTTP/调试出口 |

`main.py:285` 的本地实现：

```python
def _scope_id(self, event: AstrMessageEvent) -> str:
    return event.get_group_id() or event.unified_msg_origin or "_private"
```

——**无 persona 隔离，无 webchat 折叠**。

#### 风险点 1：scope 字符串不一致（v0.10.2+ 引入）

ESM v0.10.2 起启用 `webchat_shared_scope=True`（默认）和 `persona_isolation_enabled=True`（默认）后，social_context 的本地 `_scope_id` 与 ESM 算出的 scope **必然不一致**：

| 场景 | social_context 算 | ESM 算 |
|---|---|---|
| webchat 私聊（默认配置） | `webchat:FriendMessage:chiriu` | `webchat:橘雪莉` |
| QQ 群 + persona 隔离 | `QQ群号` | `QQ群号:橘雪莉` |
| webchat 群聊 | `webchat:room-id`（如有 group_id） | `webchat:room-id:橘雪莉` |

#### 风险点 2：ESM v0.10.3 async 化后 `_emotion_scope` 静默坏掉

ESM v0.10.3（commit `ff6c16c`）把 `get_scope` 改 `async def`。`emotion_bridge.py:84` 的 `return str(getter(event))` 拿到的不再是字符串而是 coroutine 对象，`str(coroutine)` 字符串化后变成 `"<coroutine object ...>"`：

- `emo_scope` 变成 `<coroutine object EmotionStateMachineStar.get_scope at 0x...>`
- `_feed_emotion_observation(scope=emo_scope, ...)` 写到 ESM 的 scope 形如 `<coroutine object ...>` 的脏数据
- ESM 内部 `_scope_id` 用的是 `event.get_group_id() or event.unified_msg_origin`——和 `<coroutine ...>` 这个 scope 字符串**永远不匹配**
- 结果：`on_group_message` 的情绪观察**全部 miss**，emotion 状态机不再更新——**静默 bug**

#### 风险点 3：ESM `_PUBLIC_API.md` 警告被部分无视

文档明说"其他插件必须用 `get_scope(event)` 否则会状态碎片化"——social_context **只对 1 处遵守了**，5 处仍用本地推算。这条规则在 v0.10.2 之前是软建议（差异 = persona stamp），v0.10.2+ 变硬（差异 = webchat 折叠）。

### 4.2 影响评估

| 风险 | 触发条件 | 表现 | 严重度 |
|---|---|---|---|
| **scope 不一致（1）** | `webchat_shared_scope=True`（默认） | observe_text 写到错 scope，ESM 数据不更新 | 高（私聊场景） |
| **scope 不一致（1）** | `persona_isolation_enabled=True`（默认） + QQ 群 | observe_text 写到错 scope | 中（群场景） |
| **async 静默坏掉（2）** | ESM v0.10.3+ 部署后立即 | 所有 `on_group_message` 的 emotion 观察 miss | **极高（静默全停）** |
| **文档脱节（3）** | 任何时候 | 维护风险（新人不知道为啥 1+5 不一致） | 低 |

**风险 2 是 blocker**——ESM v0.10.3 一发布，social_context 的 emotion 数据流就停了，且无任何报错日志。

### 4.3 解决路径

#### 方案 A（推荐）：`_emotion_scope` 改 async + 5 处统一调用

**步骤**：

1. `mixins/emotion_bridge.py:74` `def _emotion_scope` → `async def _emotion_scope`
2. `emotion_bridge.py:84` `return str(getter(event))` → `return str(await getter(event))`
3. `main.py:725` 已有 `emo_scope = self._emotion_scope(event)` → `emo_scope = await self._emotion_scope(event)`（在 async 上下文里）
4. `main.py:1077, 1154, 1196, 1227, 1287, 1444` 5 处 `self._scope_id(event)` → `await self._emotion_scope(event)`
5. `_scope_id(event)` 本地方法保留——降级路径用

**验证**：
- 单元测试：mock `emo.get_scope` 为 `async def get_scope(event) -> str`，验证 `_emotion_scope` 返回字符串而非 `<coroutine ...>`
- 集成测试：mock ESM `_scope_id` 返回 `webchat:橘雪莉`，验证 5 处替换点都走 ESM 路径
- 回归测试：6 处原有 `test_emotion_bridge` 测试要保留（降级路径 + ESM 不可用路径）

**估时**：约 45min（grep 5 处 + 改 + 测试 + 跑全套）

#### 方案 B（不推荐）：局部异步包装

把 `_emotion_scope` 保留 sync，内部用 `asyncio.run` 跑 coroutine——已在 ESM 那边被否决（`asyncio.run` 在已有 running loop 时 RuntimeError，AstrBot 消息钩子就是在 loop 里），social_context 这边同样不能采用。

#### 方案 C（应急）：5 处全部加 `if asyncio.iscoroutine: await` 嗅探

每处用 `scope_or_coro = self._scope_id(event)` 或 `self._emotion_scope(event)`，然后嗅探是不是 coroutine，是则 await——但 `_scope_id` 不是 coroutine，`_emotion_scope` 在改完之后才是，所以这种"嗅探"实际就是赌设计，未来不稳健。

### 4.4 优先级与时间窗

| 优先级 | 动作 | 估时 | 阻塞 | 状态 |
|---|---|---|---|---|
| **P0** | `_emotion_scope` 改 async | 10min | v0.8.16 必 | ✅ v0.8.16 完成 |
| **P0** | main.py 5 处统一 `await self._emotion_scope(event)` | 20min | v0.8.16 必 | ✅ v0.8.16 完成（实际 6 处 5 改 1 保留：1444 在 sync 函数里仅用于 prompt 展示） |
| **P0** | mock async get_scope 的单测 | 15min | v0.8.16 必 | ✅ v0.8.16 完成（新增 2 条） |
| P1 | 集成测试覆盖 webchat_shared_scope 路径 | 20min | v0.8.16 推荐 | ⏳ 下次补（v0.8.17） |
| P2 | 删 `main.py:285` 的 `_scope_id`（如确认无外部调用） | 5min | 后续顺手 | ⏳ 不动（1444 还在用） |

**v0.8.16 实际改动**：
- commit message：`fix: 对齐 ESM v0.10.3 async 化，统一 scope 计算路径`
- 关联：ESM v0.10.3（commit `ff6c16c`）+ ESM v0.10.2（commit `8693dd0`）
- 阻塞：✅ 已修复，v0.8.16 已发
- 测试：175/0 干净（0 回归）

### 4.5 验证清单

修完跑以下用例：

- [ ] `_emotion_scope(event)` 在 ESM 不可用时返回本地 `_scope_id(event)` 结果
- [ ] `_emotion_scope(event)` 在 ESM 同步 get_scope 时返回 str
- [ ] `_emotion_scope(event)` 在 ESM 异步 get_scope 时返回 str（**关键回归**）
- [ ] `on_group_message` 喂入 ESM 的 scope 与 ESM 内部 `_scope_id(event)` 算出的 scope 完全一致
- [ ] `apply_self_reply_signal(event)` 路径下，social_context 传出去的 scope 与 ESM 接收的 scope 一致
- [ ] webchat 私聊 + 默认配置：social_context 写到 `webchat:橘雪莉`，与 ESM 内部一致
- [ ] `pytest tests/` 0 failed
