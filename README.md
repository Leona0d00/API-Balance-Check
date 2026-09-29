# Field Console / API 余额查询

PySide6 桌面控制台，按供应商管理 API 账户、备注、余额与订阅额度。界面使用系统衬线标题与无衬线正文，中性深灰纸感配色、1px 网格和统一矢量导航图标，无字体文件依赖。

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
| OpenAI Codex / GPT 订阅 | 5 小时、周、GPT Reserve 与 credits | 自动显示本机 Codex 当前登录账户；通过本机 app-server 只读查询，不保存登录凭据 |
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

## 总览交互

总览卡片按可用宽度自动切换 1、2、3 列，并按各列当前高度紧凑排列。向下滚动卡片时顶部统计区自动收起，回到顶部后恢复。总览里的“查询”只更新当前卡片，不再跳转到供应商页。

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

普通供应商的余额、额度与接口结果来自当前会话的显式查询；Codex 订阅卡通过本机已安装的 `codex app-server` 读取当前账户额度。应用不读取 OpenCode 数据库、对话或本机使用记录，也不接触 Codex 登录令牌。结果不跨会话缓存；请求失败会替换旧成功状态，请求期间不能删除账户或销毁窗口。

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
