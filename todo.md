# social_context v0.8.12 TODO

> 来源：ESM v0.10.0 跨插件改造（详见 `astrbot_plugin_emotion_state_machine/_PUBLIC_API.md`）
> 状态：**阶段一+二已完工 (v0.8.12, commit 4c986c9)，阶段三推迟 1-2 周观察期再做**

## 1. 阶段一：social_context 迁移 v0.8.12

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

## 2. README 强依赖声明（与 §1 同 PR commit 4c986c9）

- [x] 在 `README.md` 显眼位置加 ESM v0.10.0+ 强依赖声明（独立"依赖要求"section，介于"当前功能"和"输出微调"之间）

  > **依赖要求：ESM v0.10.0+ 强依赖**
  >
  > 本插件 v0.8.12+ 调用了 [`astrbot_plugin_emotion_state_machine`](https://github.com/kazamisama/astrbot_plugin_emotion_state_machine) 的两个 v0.10.0 新 API：`to_text_part()` 和 `apply_self_reply_signal()`。
  >
  > - **如果没装 ESM**：emotion 注入会**静默 no-op**（social_context 检测不到 emotion 插件时整条链路降级），bot 主动回复的 self-reply signal 也不会打，但主流程仍正常工作。
  > - **如果装了 ESM 但 < v0.10.0**：judge 通道会**降级到字符串拼接**（`build_prompt_block` 仍可用但缺 `to_text_part`），self-reply signal 路径**直接缺失**。
  >
  > 推荐安装：`pip install astrbot-plugin-emotion-state-machine>=0.10.0` 或在 AstrBot 管理面板升级到 v0.10.0+。

## 3. 阶段三（推迟 1-2 周）：彻底清理 emotion_bridge

> ⚠ 必须先观察阶段一（v0.8.12）稳定 1-2 周无 emotion 相关 bug 再做

- [ ] social_context 完全移除 `emotion_bridge.py`
- [ ] "观察用户消息 → ESM" 逻辑并入主流程
- [ ] 重新设计 `_feed_emotion_observation` 的接入位置

---

## 验收记录

- 2026-06-27 v0.8.12 commit `4c986c9` 已 push 到 origin/main
- 测试：149 passed / 0 failed（v0.8.11 时 158 → 删 12 个 self-reply 测试 + 加 7 个新测试）
- ESM v0.10.0 release tag 已在 origin（不需 social_context 等）
- 待观察 1-2 周后开 §3