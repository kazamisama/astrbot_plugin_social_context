"""测试共用的假对象（配置 / 事件 / provider / emotion star）。

原来这些假对象在两个测试文件里各抄一份，且 _Cfg 的默认值不一致——一处改了
另一处不会跟着改。集中到这里以后，行为差异只可能来自显式覆盖。
"""

from __future__ import annotations

import asyncio
import os
import sys
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

from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (  # noqa: E402
    AiocqhttpMessageEvent,
)
from main import SocialContextPlugin  # noqa: E402
from mixins.emotion_bridge import EMOTION_STAR_NAME  # noqa: E402

# 用例里出现过的群号。group_whitelist 为空时插件对所有群都不生效，
# 所以假配置默认把这些群放进白名单；专门测白名单语义的用例显式覆盖它。
DEFAULT_WHITELIST = ("group-1", "group-2", "g-injection", "QQ-20001")


class _Cfg(dict):
    """测试假配置。"""

    def __init__(self, data=None, **kwargs):  # noqa: ANN001, ANN204 - 测试假对象
        super().__init__(data or {}, **kwargs)
        self.setdefault("group_whitelist", list(DEFAULT_WHITELIST))

    def get(self, key, default=None):  # noqa: ANN001, ANN201 - 测试假对象
        return super().get(key, default)


class _Event:
    """鸭子类型的事件替身，覆盖插件用到的全部读/写接口。"""

    def __init__(
        self,
        sender_name: str = "alice",
        sender_id: str = "10001",
        group_id: str = "group-1",
        message: str = "当前消息",
        extras: dict[str, object] | None = None,
        raw_message: dict[str, object] | None = None,
        message_type: str = "group",
        self_id: str = "99999",
        message_id: str = "",
        chain: list | None = None,
        platform_name: str = "aiocqhttp",
        umo: str | None = None,
    ) -> None:
        self.sender_name = sender_name
        self.sender_id = sender_id
        self.group_id = group_id
        self.unified_msg_origin = umo or group_id
        self.message_str = message
        self.extras = dict(extras or {})
        self.message_type = message_type
        self.stopped = False
        self.result = None
        self.is_at_or_wake_command = False
        self._self_id = self_id
        self._platform_name = platform_name
        self._chain = chain if chain is not None else None
        self.message_obj = type(
            "MessageObj",
            (),
            {
                "raw_message": raw_message or {},
                "message_id": message_id,
                "message": self._chain,
            },
        )()

    def get_sender_name(self) -> str:
        return self.sender_name

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_group_id(self) -> str:
        return self.group_id

    def get_message_type(self) -> str:
        return self.message_type

    def get_session_id(self) -> str:
        return self.unified_msg_origin

    def get_self_id(self) -> str:
        return self._self_id

    def get_platform_name(self) -> str:
        return self._platform_name

    def get_result(self):
        return self.result

    def is_private_chat(self) -> bool:
        return self.message_type == "private"

    def get_extra(self, key: str, default=None):  # noqa: ANN001, ANN201 - 测试假对象
        return self.extras.get(key, default)

    def set_extra(self, key: str, value) -> None:  # noqa: ANN001 - 测试假对象
        self.extras[key] = value

    def plain_result(self, text: str) -> str:
        return text

    def set_result(self, result: object) -> None:
        self.result = result

    def stop_event(self) -> None:
        self.stopped = True


class _AiocqhttpEvent(_Event, AiocqhttpMessageEvent):
    """假事件 + 真实的 AiocqhttpMessageEvent 类型，用来过在线钩子的类型闸门。

    AstrMessageEvent 的 unified_msg_origin 是个会解析 session 串的 property，
    所以这里给一个合法的三段式 umo，而不是裸 group_id。
    """

    def __init__(self, **kwargs) -> None:  # noqa: ANN003 - 测试假对象
        kwargs.setdefault("umo", f"aiocqhttp:GroupMessage:{kwargs.get('group_id', 'group-1')}")
        super().__init__(**kwargs)


def _at(qq: str):
    """构造带 qq 字段的鸭子类型 chain 元素。"""
    return SimpleNamespace(qq=qq)


class _FakeProvider:
    """text_chat 假 provider，记录调用参数。

    - `replies`：按序返回的 completion_text 列表；元素为 None 表示这次调用返回 None。
    - `delay`：每次调用先 await 指定秒数（模拟超时/慢响应）。
    """

    def __init__(
        self,
        replies: list[str | None] | None = None,
        *,
        completion_text: str = "",
        delay: float = 0.0,
    ) -> None:
        self.calls: list[dict] = []
        self._replies = list(replies or [])
        self._completion_text = completion_text
        self._delay = delay

    async def text_chat(self, **kwargs):  # noqa: ANN003, ANN201 - 测试假对象
        self.calls.append(kwargs)
        if self._delay:
            await asyncio.sleep(self._delay)
        text = self._replies.pop(0) if self._replies else self._completion_text
        if text is None:
            return None
        return SimpleNamespace(completion_text=text)


def _context_with_provider(provider: object) -> SimpleNamespace:
    """只带 get_provider_by_id 的假 context。"""
    ctx = SimpleNamespace()
    ctx.get_provider_by_id = lambda _pid: provider
    return ctx


class _FakeTextPart:
    """ESM.to_text_part 返的 TextPart 简化替身。"""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self._no_save = True  # 模拟 mark_as_temp()

    def mark_as_temp(self):
        self._no_save = True
        return self


class _FakeEmotionStar:
    """Spy 形态的 emotion_state_machine star (ESM v0.10.0+)。"""

    def __init__(
        self,
        *,
        scope_for_event: str = "g-1",
        prompt_block: str = "## Bot Emotion State\nhappy",
        text_part: _FakeTextPart | None = None,
        raise_on_observe: bool = False,
        raise_on_block: bool = False,
        raise_on_text_part: bool = False,
        bot_energy: float | None = 1.0,
        raise_on_get_bot_energy: bool = False,
    ) -> None:
        self._scope_for_event = scope_for_event
        self._prompt_block = prompt_block
        self._text_part = text_part or _FakeTextPart(text=prompt_block)
        self._raise_on_observe = raise_on_observe
        self._raise_on_block = raise_on_block
        self._raise_on_text_part = raise_on_text_part
        self._bot_energy = bot_energy
        self._raise_on_get_bot_energy = raise_on_get_bot_energy
        self.observe_calls: list[dict] = []
        self.block_calls: list[dict] = []
        self.text_part_calls: list[dict] = []
        self.get_bot_energy_calls: list[dict] = []

    async def get_scope(self, event: object) -> str:
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

    def get_bot_energy(self, scope: str | None = None) -> float:
        """v0.10.0+ 精力查询。返 [0.0, 1.0]；None 表示关闭。"""
        self.get_bot_energy_calls.append({"scope": scope})
        if self._raise_on_get_bot_energy:
            raise RuntimeError("emotion get_bot_energy 故意失败")
        if self._bot_energy is None:
            raise AttributeError("energy disabled in this fake")
        return self._bot_energy


def _make_plugin(config: dict | None = None) -> SocialContextPlugin:
    """绕过 __init__ 的轻量插件（不碰磁盘）。"""
    plugin = SocialContextPlugin.__new__(SocialContextPlugin)
    plugin.config = _Cfg(config or {})
    plugin.groups = {}
    plugin.users = {}
    plugin.context = SimpleNamespace()  # 默认：get_registered_star 缺失
    return plugin


def _real_plugin(state_path: Path, **overrides) -> SocialContextPlugin:
    """用真 __init__ 构造插件（临时 state_path），不要绕过初始化。"""
    config: dict = {"state_path": str(state_path)}
    config.update(overrides)
    return SocialContextPlugin(SimpleNamespace(), _Cfg(config))


def _attach_emotion(plugin: SocialContextPlugin, star: _FakeEmotionStar) -> None:
    """把 fake star 挂到 plugin.context.get_registered_star。"""

    def _lookup(name: str):
        assert name == EMOTION_STAR_NAME
        return star

    plugin.context.get_registered_star = _lookup  # type: ignore[attr-defined]
