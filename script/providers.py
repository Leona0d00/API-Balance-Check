"""Provider catalog: capabilities and endpoints live in one place."""

PROVIDERS = {
    'opencode_go': {'label': 'OpenCode Go', 'group': '订阅', 'capability': '用量窗口', 'base': 'https://opencode.ai/zen/go/v1'},
    'opencode_zen': {'label': 'OpenCode Zen', 'group': '聚合', 'capability': '连接检查', 'base': 'https://opencode.ai/zen/v1'},
    'deepseek': {'label': 'DeepSeek', 'group': '国内', 'capability': '余额', 'base': 'https://api.deepseek.com'},
    'zhipu': {'label': 'Zhipu / 智谱', 'group': '国内', 'capability': '余额尝试 / 密钥检查', 'base': 'https://open.bigmodel.cn/api/paas/v4'},
    'moonshot': {'label': 'Kimi / Moonshot CN', 'group': '国内', 'capability': '余额', 'base': 'https://api.moonshot.cn/v1'},
    'moonshot_global': {'label': 'Kimi / Moonshot Global', 'group': '国际', 'capability': '余额', 'base': 'https://api.moonshot.ai/v1'},
    'siliconflow': {'label': 'SiliconFlow / 硅基流动', 'group': '聚合', 'capability': '余额', 'base': 'https://api.siliconflow.cn/v1'},
    'openrouter': {'label': 'OpenRouter', 'group': '聚合', 'capability': '密钥额度 / 实际用量', 'base': 'https://openrouter.ai/api/v1'},
    'openai': {'label': 'OpenAI', 'group': '国际', 'capability': '连接检查', 'base': 'https://api.openai.com/v1'},
    'anthropic': {'label': 'Anthropic', 'group': '国际', 'capability': '连接检查', 'base': 'https://api.anthropic.com/v1'},
    'gemini': {'label': 'Google Gemini', 'group': '国际', 'capability': '连接检查', 'base': 'https://generativelanguage.googleapis.com/v1beta'},
    'groq': {'label': 'Groq', 'group': '国际', 'capability': '连接检查', 'base': 'https://api.groq.com/openai/v1'},
    'mistral': {'label': 'Mistral', 'group': '国际', 'capability': '连接检查', 'base': 'https://api.mistral.ai/v1'},
    'custom': {'label': 'OpenAI Compatible', 'group': '自定义', 'capability': '连接检查', 'base': ''},
}


def provider_label(provider):
    return PROVIDERS.get(provider, {}).get('label', provider)
