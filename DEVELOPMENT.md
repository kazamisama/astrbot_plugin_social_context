# 开发说明（DEVELOPMENT）

面向贡献者：模块职责、硬性契约、本地命令。安装、配置与行为说明见 [README.md](README.md)。

## 结构总览

插件按领域拆成多个模块，`main.py` 只保留插件类与全部事件钩子；状态持久化、压缩、群成员查询、情绪桥接各自成模块。

## 模块 → 职责

| 模块 | 职责 |
|---|---|
| `main.py` | 插件类、所有 `@filter.*` 事件钩子与 LLM 工具、配置访问器、注入与判断编排、命令 |
| `models.py` | 数据结构 `GroupContext` / `UserContext` / `MessageRecord` / `PokeRecord` / `JudgeResult`，以及共享的纯函数 |
| `prompt_security.py` | 注入扫描与变量扫描 |
| `mixins/persistence.py` | 状态 JSON 落盘、读取、逐条容错、淘汰入口 |
| `mixins/compress.py` | 三层历史压缩、摘要过期清理、后台压缩与淘汰循环 |
| `mixins/members.py` | 群成员名册查询辅助方法 |
| `mixins/emotion_bridge.py` | 与 emotion_state_machine 的桥接 |
| `output_step/reply.py` | 智能引用（改写输出消息 chain） |
| `tests/` | 单元测试与钩子集成测试；`tests/_fakes.py` 集中放测试假对象并负责 `sys.path` 引导 |
| `_conf_schema.json` | WebUI 配置分组、类型与默认值 |
| `metadata.yaml` | 插件元数据与版本号 |

## 硬性契约

1. **事件钩子与工具定义在 `main.py`。** AstrBot 按函数 `__module__` 精确匹配注册，写进 mixin 会静默不触发。
2. **依赖单向**：`main.py` → `mixins/`、`output_step/` → `models.py`；`prompt_security.py` 与 `models.py` 不反向依赖。模块顶部使用相对导入并保留 `ImportError` 兜底（兼容测试以脚本方式导入 `main.py`）。
3. **可变状态单一归属**：`self.groups` / `self.users` 由 `mixins/persistence.py` 负责落盘；淘汰逻辑在 `mixins/compress.py`，且必须先淘汰、再判断 `persist_enabled`——顺序反了，关闭持久化时内存会无界增长。
4. **配置归一化只有一个入口**：`main.py` 的 `_cfg_*` 访问器。其他位置不要直接读 `self.config` 再自己夹取或抄一份默认值。
5. **数据目录走官方 API**：`StarTools.get_data_dir(_PLUGIN_NAME)`。插件目录名必须与 `metadata.name` 一致，否则卸载时 `data/plugin_data/<目录名>` 清不掉。

## 本地命令

运行测试（需要 AstrBot 自带的 Python 环境，测试会导入 AstrBot 模块）：

```bash
python -m pytest tests -q
```

只跑某个领域：

```bash
python -m pytest tests/test_hooks.py -q          # 钩子 / 命令面集成测试
python -m pytest tests/test_plugin_helpers.py -q # 纯逻辑与持久化
```

代码风格：

```bash
python -m ruff check .
```

## 测试约定

- `tests/_fakes.py` 负责把 AstrBot 的 app 目录与插件根目录加入 `sys.path`，因此测试文件应先 `from tests._fakes import ...`，不要随手改动这个顺序（会让 `sys.path` 引导晚于 `astrbot` 导入）。
- 用 `_real_plugin()` 构造真实插件（真实 `__init__` + 临时 `state_path`），不要用 `__new__` 手填字段绕过初始化。
- 测试测真实实现，不要把业务逻辑抄进测试再按同一公式算期望值。
- 新增配置项时同步更新 `_conf_schema.json`、README 配置表与测试假配置的默认值。

## 何时拆分与扩展

- 新增独立领域：依赖 `self` 的方法放 `mixins/<name>.py`，不依赖插件的纯逻辑放 `<domain>/`；不要建 `utils/`、`helpers/` 这类按技术层次分的桶。
- 拆分顺序：先补测试 → 抽纯逻辑 → 抽 mixin（不动装饰器）→ 清 `main.py`，每一步保持全量测试绿。
- `main.py` 接近 2000 行且仍在增长，或出现多个互相耦合的独立领域时再拆；没有测试的大拆分风险高于收益。

## 发布前检查

- `python -m py_compile main.py` 通过
- `python -m pytest tests -q` 全绿、`python -m ruff check .` 无新增告警
- `metadata.yaml`、CHANGELOG 顶部、README 版本引用三处一致
- README 配置表与 `_conf_schema.json` 键集合一致
- 没有未使用 import、死代码、只写不读的字段
