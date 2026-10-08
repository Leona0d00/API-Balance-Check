# Field Console / API 余额查询

PySide6 桌面控制台，按供应商管理 API 账户、备注、余额与调用活跃度。界面使用系统衬线标题与无衬线正文，中性深灰纸感配色、1px 网格和统一矢量导航图标，无字体文件依赖。

## 运行

Python 3.9+，Windows / macOS / Linux。

```bash
python -m venv .venv
pip install -r requirements.txt
python -m script.menu
```

请先激活虚拟环境；Windows 使用 `.venv\Scripts\activate`，macOS / Linux 使用 `source .venv/bin/activate`。

## 命令行 / Agent 调用

命令行复用桌面程序已经添加的账户，无需打开窗口。默认查询全部账户、输出 UTF-8 JSON：

```powershell
# 在项目内运行
python -m script.cli

# 从任意目录调用（将路径替换为实际项目位置）
& "C:\Users\leonado\Desktop\余额查询\balance.cmd"

# 人工查看表格、按供应商或账户筛选
& "C:\Users\leonado\Desktop\余额查询\balance.cmd" --format table
& "C:\Users\leonado\Desktop\余额查询\balance.cmd" --provider deepseek
& "C:\Users\leonado\Desktop\余额查询\balance.cmd" --account deepseek/main
```

Windows 启动器依次使用 `BALANCE_PYTHON` 指定的解释器、项目 `.venv\Scripts\python.exe`、PATH 中的 `python`。也可直接使用 Python 绝对路径运行项目根目录 `balance.py`，适用于 Windows / macOS / Linux。CLI 只需 `requests`，不导入 PySide6。

默认并发数为 4，`--workers 1` 可串行查询，允许范围 1–32。`--provider` 和 `--account` 可以重复；两类筛选同时使用时取交集。配置目录始终是工具所在项目的 `.config/`，与调用方工作目录无关。

JSON 包含 `schema_version`、UTC 查询时间、成功/失败统计和按账户标识排序的 `accounts`。金额用十进制字符串表示，不混淆账户余额、密钥额度、订阅额度与连接检查。单个账户查询失败不会丢弃其他结果；没有余额接口的成功结果标记 `balance_supported: false`。不返回密钥或完整供应商响应，不修改账户凭据和备注。

退出码：`0` 全部查询成功，`1` 存在账户查询失败，`2` 参数/配置错误或无匹配账户，`130` 用户中断。Agent 应在退出码 `1` 时继续解析 JSON，保留成功结果。配置文件损坏等全局错误返回顶层 `error`，不发起查询。

完整调用约定与可直接复制给 Agent 的说明见根目录 **[使用指南.md](使用指南.md)**。该文档可复制到其他项目，按其中的绝对路径调用此工具。

## 供应商能力

| 供应商 | 功能 | 说明 |
| --- | --- | --- |
| OpenCode Go | 5 小时、周、月用量 | 使用 Go usage 接口 |
| DeepSeek | 账户余额 | 充值余额与赠金 |
| Kimi / Moonshot CN、Global | 账户余额 | 分别使用国内与国际 API 地址，币种 CNY / USD |
| Xiaomi MiMo / 小米 | 模型列表连接检查 | 普通 MiMo API `sk-` 密钥；余额需在小米控制台查看，Token Plan 密钥与普通 API 密钥不通用 |
| MiniMax Token Plan CN、Global | 5 小时 / 周剩余额度 | 使用订阅密钥查询官方额度接口；按量付费余额在 MiniMax 控制台查看 |
| SiliconFlow | 账户余额 | 使用 user/info 的 totalBalance |
| OpenRouter | 密钥额度和实际消耗 / 账户余额 | 普通密钥查询自身额度与日、周、月消耗；账户余额模式需要管理密钥 |
| 智谱 | 尝试余额，失败后检查密钥 | 保留原有控制台接口回退策略 |
| OpenAI、Anthropic、Gemini、Groq、Mistral、OpenCode Zen | 模型列表连接检查 | 不提供余额；成功获取模型列表不代表推理或计费一定可用 |
| OpenAI Compatible | 自定义 HTTPS Base URL 连接检查 | 支持代理服务，不假设它有余额接口 |

供应商能力与基础地址集中在 `script/providers.py`；增加一个兼容服务无需修改 UI 布局。

## 账户与备注

“供应商 / Providers”页中添加账户，在供应商下面管理多个密钥。搜索匹配供应商名称、账户标识或备注。选中账户后点击“备注”，修改显示名称；留空恢复账户标识。备注不改变 provider/api_name 或密钥。

凭据保留在原格式：

```text
.config/<provider>/<api_name>/<api_name>.json
```

示例使用占位密钥：

```json
{"apikey": "YOUR_API_KEY"}
```

自定义服务配置额外保存 `base_url`；OpenRouter 额外保存 `query_mode`（`key` 或 `account`）。非秘密备注存储在 `.config/metadata.sqlite3`，不会重写原凭据或丢弃其中未知字段。`.config/` 整体忽略，不提交到 Git。

余额、额度与接口结果只来自供应商官方接口的当前会话手动查询，不读取 OpenCode 数据库，也不收集本机使用记录。结果不跨会话缓存；请求失败会替换旧成功状态，请求期间不能删除账户或销毁窗口。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试使用临时配置和模拟接口，不调用真实供应商。

## 接口参考

- [OpenCode Providers](https://opencode.ai/docs/providers)
- [Xiaomi MiMo 模型列表](https://mimo.mi.com/docs/en-US/api/model/list-models)
- [Xiaomi MiMo OpenCode 配置与密钥区别](https://mimo.mi.com/docs/en-US/tokenplan/integration/opencode)
- [MiniMax Token Plan 剩余额度接口（国际）](https://platform.minimax.io/subscribe/token-plan)
- [MiniMax Token Plan 剩余额度接口（国内）](https://platform.minimaxi.com/subscribe/token-plan)
- [DeepSeek 余额](https://api-docs.deepseek.com/api/get-user-balance)
- [Kimi 国内余额](https://platform.kimi.com/docs/api/balance) / [国际余额](https://platform.kimi.ai/docs/api/balance)
- [SiliconFlow 官方 OpenAPI](https://github.com/siliconflow/siliconcloud/blob/main/openapi.yaml)
- [OpenRouter 密钥](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key) / [管理密钥余额](https://openrouter.ai/docs/api/api-reference/credits/get-remaining-credits)
- [OpenAI Models](https://developers.openai.com/api/reference/resources/models/methods/list)
- [Anthropic Models](https://platform.claude.com/docs/en/api/models/list)
- [Gemini Models](https://ai.google.dev/api/models)
- [Groq API](https://console.groq.com/docs/api-reference)
- [Mistral Models](https://docs.mistral.ai/api/endpoint/models)
