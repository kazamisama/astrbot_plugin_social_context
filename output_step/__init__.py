"""输出微调步骤集合。

v0.5.0+ 新增。本目录下的模块在 AstrBot 的 `on_decorating_result`
钩子阶段运行，可以修改即将发送的消息链（result.chain）。

每个 step 是独立纯函数模块，方便单元测试和复用。
"""
