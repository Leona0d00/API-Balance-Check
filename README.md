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

## 供应商能力

| 供应商 | 功能 | 说明 |
| --- | --- | --- |
| OpenCode Go | 5 小时、周、月用量 | 使用 Go usage 接口 |
| DeepSeek | 账户余额 | 充值余额与赠金 |
| Kimi / Moonshot CN、Global | 账户余额 | 分别使用国内与国际 API 地址，币种 CNY / USD |
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

## 实际 API 活跃度

“活跃度 / Telemetry”页只读接入本机 OpenCode 数据库，按供应商显示近 7 个自然日的完成响应数、Token 数、每日趋势与最近调用时间。每 60 秒刷新，也可手动刷新。

- 数据来源是 OpenCode 中已完成、无错误的 assistant 响应元数据，不是本工具余额查询次数。
- Token 总量包括输入、输出、推理、缓存读写；没有读取对话正文、消息 parts、密钥或凭据表。
- 无法区分同一供应商的不同密钥，也不能覆盖其他客户端的调用。因此活跃度显示在供应商标题与 Telemetry 页，避免归属到错误账户。
- 未找到数据库或格式不兼容会显示状态，不将缺失记录解释成零调用。
- 默认读取 `$XDG_DATA_HOME/opencode/opencode.db` 或 `~/.local/share/opencode/opencode.db`。可通过 `API_BALANCE_OPENCODE_DB` 指定另一个路径。数据库以只读方式打开，读取最多等待 8 秒，不创建表或索引。

余额与接口结果来自当前会话手动查询，不跨会话缓存。余额请求失败会替换旧成功状态；请求期间不能删除账户或销毁窗口。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试使用临时配置、模拟接口和合成活动数据库，不调用真实供应商。

## 接口参考

- [OpenCode Providers](https://opencode.ai/docs/providers)
- [DeepSeek 余额](https://api-docs.deepseek.com/api/get-user-balance)
- [Kimi 国内余额](https://platform.kimi.com/docs/api/balance) / [国际余额](https://platform.kimi.ai/docs/api/balance)
- [SiliconFlow 官方 OpenAPI](https://github.com/siliconflow/siliconcloud/blob/main/openapi.yaml)
- [OpenRouter 密钥](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key) / [管理密钥余额](https://openrouter.ai/docs/api/api-reference/credits/get-remaining-credits)
- [OpenAI Models](https://developers.openai.com/api/reference/resources/models/methods/list)
- [Anthropic Models](https://platform.claude.com/docs/en/api/models/list)
- [Gemini Models](https://ai.google.dev/api/models)
- [Groq API](https://console.groq.com/docs/api-reference)
- [Mistral Models](https://docs.mistral.ai/api/endpoint/models)
