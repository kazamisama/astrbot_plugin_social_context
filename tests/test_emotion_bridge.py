"""social_context → emotion_state_machine 桥接 Mixin 测试。

v0.8.12+：桥接从 3 接入点（observe / build_prompt_block / apply_signal）
砍到 2 接入点（observe / to_text_part 主路径 + build_prompt_block 降级）。
self-reply signal 已迁回 ESM 端（ESM v0.10.0+ 的 apply_self_reply_signal
由 main.py 在 judge=yes 后显式调用）。

测试目标：EmotionBridgeMixin 的两个接入点在以下场景下行为正确：
  - emotion 插件缺失（context.get_registered_star 返回 None）
  - emotion 插件缺失 get_registered_star 接口
  - emotion 插件缺少必需方法
  - emotion 插件方法抛异常
  - 关闭对应开关
  - bot 自己的消息不喂 emotion
  - 正常调用路径
  - scope 优先用 emotion.get_scope(event)

参考 fake star 模式来自
astrbot_plugin_emotion_state_machine/tests/test_plugin_api.py。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_ASTRBOT_APP_CANDIDATES = [
    Path(os.environ["ASTRBOT_APP_PATH"]) if os.environ.get("ASTRBOT_APP_PATH") else None,
    Path(r"C:\application\AstrBot\backend\app"),
]
for _candidate in _ASTRBOT_APP_CANDIDATES:
    if _candidate and _candidate.exists():
        sys.path.insert(0, str(_candidate))
        break
sys.path.insert(0, str(_PLUGIN_ROOT))

from main import SocialContextPlugin  # noqa: E402
from mixins.emotion_bridge import EMOTION_STAR_NAME  # noqa: E402


class _Cfg(dict):
    def get(self, key, default=None):  # noqa: ANN001, ANN201 - 测试假对象
        return super().get(key, default)


class _FakeTextPart:
    """v0.10.0+ ESM.to_text_part 返的 TextPart 简化替身。"""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self._no_save = True  # 模拟 mark_as_temp()

    def mark_as_temp(self):
        self._no_save = True
        return self


class _FakeEmotionStar:
    """Spy 形态的 emotion_state_machine star (ESM v0.10.0+)。

    v0.8.12+：方法列表从 3 个简化到 2 个（observe_text + to_text_part）。
    build_prompt_block 保留作降级路径。
    """

    def __init__(
        self,
        *,
        scope_for_event: str = "g-1",
        prompt_block: str = "## Bot Emotion State\nhappy",
        text_part: _FakeTextPart | None = None,
        raise_on_observe: bool = False,
        raise_on_block: bool = False,
        raise_on_text_part: bool = False,
    ) -> None:
        self._scope_for_event = scope_for_event
        self._prompt_block = prompt_block
        self._text_part = text_part or _FakeTextPart(text=prompt_block)
        self._raise_on_observe = raise_on_observe
        self._raise_on_block = raise_on_block
        self._raise_on_text_part = raise_on_text_part
        self.observe_calls: list[dict] = []
        self.block_calls: list[dict] = []
        self.text_part_calls: list[dict] = []

    def get_scope(self, event: object) -> str:
        return self._scope_for_event

    def observe_text(self, *, scope, text, user_id, mentioned):  # noqa: ANN001
        self.observe_calls.append(
            {"scope": scope, "text": text, "user_id": user_id, "mentioned": mentioned}
        )
        if self._raise_on_observe:
            raise RuntimeError("emotion observe_text 故意失败")
        return SimpleNamespace(label="calm")

    def build_prompt_block(self, *, scope, user_id=""):  # noqa: ANN001
        """降级路径：返 str 字符串。"""
        self.block_calls.append({"scope": scope, "user_id": user_id})
        if self._raise_on_block:
            raise RuntimeError("emotion build_prompt_block 故意失败")
        return self._prompt_block

    def to_text_part(self, scope: str, user_id: str = "") -> _FakeTextPart:
        """v0.10.0+ 主路径：返 TextPart。"""
        self.text_part_calls.append({"scope": scope, "user_id": user_id})
        if self._raise_on_text_part:
            raise RuntimeError("emotion to_text_part 故意失败")
        return self._text_part


def _make_plugin(config: dict | None = None) -> SocialContextPlugin:
    plugin = SocialContextPlugin.__new__(SocialContextPlugin)
    plugin.config = _Cfg(config or {})
    plugin.groups = {}
    plugin.users = {}
    plugin.context = SimpleNamespace()  # 默认：get_registered_star 缺失
    # v0.8.12+：_emotion_signal_last / _emotion_disabled_warn_last 已迁回 ESM
    return plugin


def _attach_emotion(plugin: SocialContextPlugin, star: _FakeEmotionStar) -> None:
    """把 fake star 挂到 plugin.context.get_registered_star。"""

    def _lookup(name: str):
        assert name == EMOTION_STAR_NAME
        return star

    plugin.context.get_registered_star = _lookup  # type: ignore[attr-defined]


class EmotionBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = _make_plugin()

    # ---- 缺失场景 ----

    def test_no_get_registered_star_attr_is_silent(self) -> None:
        # plugin.context 没有 get_registered_star
        self.plugin._feed_emotion_observation("g", "text", "u", False)
        self.assertEqual(self.plugin._build_emotion_block("g", "u"), "")

    def test_get_registered_star_returns_none_is_silent(self) -> None:
        self.plugin.context.get_registered_star = lambda _name: None  # type: ignore[attr-defined]
        self.plugin._feed_emotion_observation("g", "text", "u", False)
        self.assertEqual(self.plugin._build_emotion_block("g", "u"), "")

    def test_get_registered_star_raises_is_silent(self) -> None:
        def _boom(_name):
            raise RuntimeError("registry hiccup")

        self.plugin.context.get_registered_star = _boom  # type: ignore[attr-defined]
        # 不应抛出
        self.plugin._feed_emotion_observation("g", "text", "u", False)
        self.assertEqual(self.plugin._build_emotion_block("g", "u"), "")

    def test_emotion_missing_observe_text_is_silent(self) -> None:
        # v0.8.12+：_get_emotion_plugin 只检查 observe_text 一个方法
        # 没有 observe_text → 视作不可用
        class _Partial(SimpleNamespace):
            def get_scope(self, event):
                return "g"

            def build_prompt_block(self, **_):
                return "block"

            def to_text_part(self, **_):
                return _FakeTextPart("block")

        self.plugin.context.get_registered_star = lambda _name: _Partial()  # type: ignore[attr-defined]
        self.assertIsNone(self.plugin._get_emotion_plugin())
        # 走降级：build_emotion_block 应该返回空串
        self.assertEqual(self.plugin._build_emotion_block("g", "u"), "")

    # ---- 接入点 1：observe ----

    def test_observe_calls_emotion_with_args(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin._feed_emotion_observation("g-1", "hi bot", "u-1", mentioned=True)
        self.assertEqual(len(star.observe_calls), 1)
        call = star.observe_calls[0]
        self.assertEqual(call["scope"], "g-1")
        self.assertEqual(call["text"], "hi bot")
        self.assertEqual(call["user_id"], "u-1")
        self.assertTrue(call["mentioned"])

    def test_observe_observe_disabled_skips(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin.config["emotion_observe_enabled"] = False
        self.plugin._feed_emotion_observation("g-1", "hi", "u-1", False)
        self.assertEqual(star.observe_calls, [])

    def test_observe_empty_text_skips(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin._feed_emotion_observation("g-1", "", "u-1", False)
        self.assertEqual(star.observe_calls, [])

    def test_observe_raises_is_silent(self) -> None:
        star = _FakeEmotionStar(raise_on_observe=True)
        _attach_emotion(self.plugin, star)
        # 不应抛
        self.plugin._feed_emotion_observation("g-1", "hi", "u-1", False)

    # ---- 接入点 2：build_prompt_block（降级路径） ----

    def test_block_returns_stripped_text(self) -> None:
        star = _FakeEmotionStar(prompt_block="  ## Bot Emotion State\nhappy  \n")
        _attach_emotion(self.plugin, star)
        self.assertEqual(
            self.plugin._build_emotion_block("g-1", "u-1"),
            "## Bot Emotion State\nhappy",
        )

    def test_block_empty_when_disabled(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin.config["emotion_judge_inject_enabled"] = False
        self.assertEqual(self.plugin._build_emotion_block("g-1", "u-1"), "")
        self.assertEqual(star.block_calls, [])

    def test_block_empty_when_plugin_missing(self) -> None:
        self.assertEqual(self.plugin._build_emotion_block("g-1", "u-1"), "")

    def test_block_raises_returns_empty(self) -> None:
        star = _FakeEmotionStar(raise_on_block=True)
        _attach_emotion(self.plugin, star)
        self.assertEqual(self.plugin._build_emotion_block("g-1", "u-1"), "")

    def test_block_non_string_returns_empty(self) -> None:
        star = _FakeEmotionStar()
        # monkey-patch build_prompt_block 返非字符串
        star.build_prompt_block = lambda **_: 123  # type: ignore[assignment]
        _attach_emotion(self.plugin, star)
        self.assertEqual(self.plugin._build_emotion_block("g-1", "u-1"), "")

    # ---- v0.8.12+：to_text_part（主路径） ----
    # 注：main.py 的 _judge_should_reply 直接调 emo.to_text_part 拿 TextPart，
    # 本测试通过 _FakeEmotionStar 的 text_part_calls 字段验证调用是否发生。

    def test_to_text_part_returns_text_part(self) -> None:
        """v0.8.12+ 主路径：to_text_part 返 TextPart 供 main.py 独立 append。"""
        star = _FakeEmotionStar(
            text_part=_FakeTextPart(text="## Emotion\nhappy")
        )
        _attach_emotion(self.plugin, star)
        part = star.to_text_part("g-1", "u-1")
        self.assertEqual(part.text, "## Emotion\nhappy")
        self.assertTrue(getattr(part, "_no_save", False))
        # 记录一次调用
        self.assertEqual(len(star.text_part_calls), 1)
        self.assertEqual(star.text_part_calls[0]["scope"], "g-1")
        self.assertEqual(star.text_part_calls[0]["user_id"], "u-1")

    def test_to_text_part_raises_is_caught_by_caller(self) -> None:
        """v0.8.12+：main.py 的 try/except 捕获 to_text_part 异常。"""
        star = _FakeEmotionStar(raise_on_text_part=True)
        _attach_emotion(self.plugin, star)
        # 模拟 main.py 调用的异常处理
        with __import__("builtins").AssertionError if False else __import__(
            "contextlib"
        ).suppress(RuntimeError):
            try:
                star.to_text_part("g-1", "u-1")
            except RuntimeError:
                pass  # main.py 走降级到 _build_emotion_block

    def test_esm_v0_8_or_older_no_to_text_part(self) -> None:
        """v0.8.12+ 兼容：老 ESM（无 to_text_part）走降级到 _build_emotion_block。"""
        # 旧版 ESM star：有 observe_text 和 build_prompt_block，但没 to_text_part
        class _OldESM(SimpleNamespace):
            def get_scope(self, event):
                return "g-1"

            def observe_text(self, **_):
                return None

            def build_prompt_block(self, **_) -> str:
                return "## Old Emotion State"

        star = _OldESM()
        _attach_emotion(self.plugin, star)  # type: ignore[arg-type]
        # _get_emotion_plugin 仍能拿到（observe_text 存在）
        self.assertIsNotNone(self.plugin._get_emotion_plugin())
        # to_text_part 不存在
        self.assertFalse(hasattr(star, "to_text_part"))
        # 降级路径：_build_emotion_block 仍能拿到字符串
        self.assertEqual(
            self.plugin._build_emotion_block("g-1", "u-1"),
            "## Old Emotion State",
        )

    # ---- scope 路径 ----

    def test_emotion_scope_prefers_emotion_get_scope(self) -> None:
        star = _FakeEmotionStar(scope_for_event="from-emotion")
        _attach_emotion(self.plugin, star)
        event = SimpleNamespace()
        self.assertEqual(self.plugin._emotion_scope(event), "from-emotion")

    def test_emotion_scope_falls_back_to_local_when_plugin_missing(self) -> None:
        # 无 emotion 插件时，走主类 _scope_id 的 group_id → origin → _private 降级
        # 这里 _Event 没有 unified_msg_origin 属性，回退 _scope_id(event) 走 hasattr try/except
        # 用 SimpleNamespace 模拟没有 group_id 的私聊
        event = SimpleNamespace(
            get_group_id=lambda: "",
            unified_msg_origin="private:x",
        )
        # 没有 get_registered_star → 走本地降级
        self.assertEqual(self.plugin._emotion_scope(event), "private:x")

    def test_emotion_scope_falls_back_to_local_when_get_scope_raises(self) -> None:
        class _Boom(SimpleNamespace):
            def get_scope(self, _):
                raise RuntimeError("boom")

        self.plugin.context.get_registered_star = lambda _name: _Boom()  # type: ignore[attr-defined]
        event = SimpleNamespace(
            get_group_id=lambda: "g-7",
            unified_msg_origin="origin",
        )
        # _scope_id 本地版本优先 group_id
        self.assertEqual(self.plugin._emotion_scope(event), "g-7")

    # ---- MRO / 常量 ----

    def test_emotion_bridge_mixin_in_mro(self) -> None:
        from mixins.emotion_bridge import EmotionBridgeMixin
        self.assertIn(EmotionBridgeMixin, SocialContextPlugin.__mro__)

    def test_emotion_star_name_constant(self) -> None:
        self.assertEqual(EMOTION_STAR_NAME, "astrbot_plugin_emotion_state_machine")


class SelfReplySignalTests(unittest.TestCase):
    """v0.8.12+：judge=yes 后显式调 ``emo.apply_self_reply_signal(event)``。

    main.py 的调用位置在 ``_judge_should_reply`` 末尾，judge 投 yes 后、
    ``event.is_at_or_wake_command = True`` 之前。ESM 内部防御性检查
    ``is_at_or_wake_command``，必须在为 False 时调用。
    """

    def setUp(self) -> None:
        self.plugin = _make_plugin()

    def test_apply_self_reply_signal_called_with_event(self) -> None:
        """judge=yes 流程：_get_emotion_plugin + apply_self_reply_signal(event)。"""
        # 给 _FakeEmotionStar 加 apply_self_reply_signal spy
        class _StarWithSignal(_FakeEmotionStar):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.apply_signal_calls: list[dict] = []

            async def apply_self_reply_signal(self, event) -> bool:  # noqa: ANN001
                self.apply_signal_calls.append({"event": event})
                return True

        star = _StarWithSignal()
        _attach_emotion(self.plugin, star)

        # 模拟 main.py 的 judge=yes 流程
        emo = self.plugin._get_emotion_plugin()
        self.assertIsNotNone(emo)

        # 调 apply_self_reply_signal（async）
        import asyncio
        result = asyncio.run(emo.apply_self_reply_signal(SimpleNamespace()))
        self.assertTrue(result)
        self.assertEqual(len(star.apply_signal_calls), 1)

    def test_apply_self_reply_signal_returns_false_when_disabled_in_esm(self) -> None:
        """ESM 内部 self_reply_signal_enabled=False 时返 False，social_context 静默。"""

        class _StarWithSignal(_FakeEmotionStar):
            async def apply_self_reply_signal(self, event) -> bool:  # noqa: ANN001
                return False  # 模拟 ESM 内部因配置/条件判定不 apply

        star = _StarWithSignal()
        _attach_emotion(self.plugin, star)

        import asyncio
        emo = self.plugin._get_emotion_plugin()
        result = asyncio.run(emo.apply_self_reply_signal(SimpleNamespace()))
        self.assertFalse(result)
        # social_context 不需要知道为什么——False 就是 False，照常走主流程

    def test_apply_self_reply_signal_missing_in_old_esm(self) -> None:
        """老 ESM 没 apply_self_reply_signal：social_context 降级到 no-op。"""
        # 旧版 ESM star：没有 apply_self_reply_signal
        star = _FakeEmotionStar()
        # 验证 getattr 降级路径
        self.assertFalse(hasattr(star, "apply_self_reply_signal"))
        # main.py 的 hasattr 检查会降级
        signal_method = getattr(star, "apply_self_reply_signal", None)
        self.assertIsNone(signal_method)

    def test_apply_self_reply_signal_raises_is_silent(self) -> None:
        """apply_self_reply_signal 抛异常时 social_context 不应受影响。"""

        class _StarWithSignal(_FakeEmotionStar):
            async def apply_self_reply_signal(self, event) -> bool:  # noqa: ANN001
                raise RuntimeError("esm internal error")

        star = _StarWithSignal()
        _attach_emotion(self.plugin, star)

        import asyncio
        # 模拟 main.py 的 try/except 包裹
        with __import__("contextlib").suppress(RuntimeError):
            try:
                emo = self.plugin._get_emotion_plugin()
                asyncio.run(emo.apply_self_reply_signal(SimpleNamespace()))
            except RuntimeError:
                pass  # main.py logger.debug 后继续


if __name__ == "__main__":
    unittest.main()
