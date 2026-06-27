# social_context v0.8.12 TODO

> 来源：ESM v0.10.0 跨插件改造（详见 `astrbot_plugin_emotion_state_machine/_PUBLIC_API.md`）
> 状态：未开工

## 1. 阶段一：social_context 迁移 v0.8.12

- [ ] 升级对 ESM `to_text_part` 的依赖
- [ ] 删除接入点 3（self-reply signal）
  - 删 `_apply_emotion_self_reply_signal`（`mixins/emotion_bridge.py:171-240`，约 70 行）
  - 删 4 个配置项 + `_conf_schema.json` hint
  - 删 `self._emotion_signal_last` / `self._emotion_disabled_warn_last`
  - 删 `tests/test_emotion_bridge.py` 约 30 行
  - 简化 `_get_emotion_plugin` 检查列表
- [ ] judge=yes 后显式调用 `esm.apply_self_reply_signal(event)`（4 行）
- [ ] 接入点 2 改造：字符串拼接 → `to_text_part` 独立 TextPart
- [ ] 更新 CHANGELOG：v0.8.12 段落（提及 ESM v0.10.0+ 依赖）
- [ ] bump metadata.yaml 到 v0.8.12
- [ ] 跑测试确认无回归

## 2. README 强依赖声明（必须与 §1 同 PR 提交）

- [ ] 在 `README.md` 显眼位置（建议在"安装"或"配置"section 顶部）加以下文案：

  > **依赖要求：ESM v0.10.0+ 强依赖**
  >
  > 本插件 v0.8.12+ 调用了 [`astrbot_plugin_emotion_state_machine`](https://github.com/kazamisama/astrbot_plugin_emotion_state_machine) 的两个 v0.10.0 新 API：`to_text_part()` 和 `apply_self_reply_signal()`。
  >
  > - **如果没装 ESM**：emotion 注入会**静默 no-op**（social_context 检测不到 emotion 插件时整条链路降级），bot 主动回复的 self-reply signal 也不会打，但主流程仍正常工作。
  > - **如果装了 ESM 但 < v0.10.0**：judge 通道会**降级到字符串拼接**（`build_prompt_block` 仍可用但缺 `to_text_part`），self-reply signal 路径**直接缺失**。
  >
  > 推荐安装：`pip install astrbot-plugin-emotion-state-machine>=0.10.0` 或在 AstrBot 管理面板升级到 v0.10.0+。

## 3. 阶段二（推迟）：彻底清理 emotion_bridge

> ⚠ 必须先观察阶段一（v0.8.12）稳定 1-2 周无 emotion 相关 bug 再做

- [ ] social_context 完全移除 `emotion_bridge.py`
- [ ] "观察用户消息 → ESM" 逻辑并入主流程
- [ ] 重新设计 `_feed_emotion_observation` 的接入位置

---

**当前阻塞**：§1 全部未开工。等 ESM v0.10.0 release tag push 完即可开始。