"""SocialContextPlugin 的功能 Mixin 集合。

只搬迁**无 @filter.* 装饰器**的纯逻辑/辅助方法。
带装饰器的 handler 必须留在 main.py：AstrBot 按 handler.__module__ 精确匹配
注册（star_handler.get_handlers_by_module_name），跨模块会导致 handler 加载失败。
"""
