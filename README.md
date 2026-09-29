# API 余额查询

桌面 GUI 工具，用于管理并查询以下 API：

- `opencode_go`：查询 OpenCode Go 的 5 小时、周、月用量。
- `deepseek`：查询 DeepSeek 官方账户余额。
- `zhipu`：优先尝试智谱控制台内部余额接口；失败后使用官方模型接口验证 API Key，并提示到控制台查看余额。

## 环境

- Python 3.9 或更高版本
- Windows、macOS 或 Linux
- PySide6

## 安装与运行

### 方式一：使用 pip

```bash
python -m venv .venv
```

Windows：

```bash
.venv\Scripts\activate
```

macOS/Linux：

```bash
source .venv/bin/activate
```

进入虚拟环境后安装依赖并运行：

```bash
pip install -r requirements.txt
python -m script.menu
```

### 方式二：使用 conda

```bash
conda create -n api-balance python=3.9
conda activate api-balance
pip install -r requirements.txt
python -m script.menu
```

必须在项目根目录运行命令。API Key 只保存在本地 `.config` 目录，界面不会展示完整密钥。

## 配置格式

每个 API 使用独立目录和 JSON 文件，唯一键格式为 `provider/api_name`：

```text
.config/
├── opencode_go/
│   └── my_account/
│       └── my_account.json
├── deepseek/
│   └── main/
│       └── main.json
└── zhipu/
    └── main/
        └── main.json
```

文件内容：

```json
{
  "apikey": "your-api-key"
}
```

GUI 中点击“添加 API”后，按照向导依次选择供应商、填写 `api_name` 和输入 `apikey`，无需手动编写 JSON。API Key 输入框默认隐藏内容。

## 接口说明

OpenCode Go 使用：

```text
GET https://opencode.ai/zen/go/v1/usage
Authorization: Bearer <API_KEY>
```

DeepSeek 使用：

```text
GET https://api.deepseek.com/user/balance
Authorization: Bearer <API_KEY>
```

智谱官方目前没有公开 API Key 余额查询接口。程序会先尝试控制台内部接口；该接口失败时不会影响程序运行，而是调用官方模型列表接口验证 Key，并显示控制台查询提示。

## 错误处理

程序会处理网络超时、HTTP 错误、无效 JSON、空 API Key、重复配置和非法配置文件。Go 的 `401`/`403`、DeepSeek 的余额错误、智谱的欠费或套餐超限错误都会显示在 GUI 中。

## 测试说明

`tests/` 目录用于验证项目的核心逻辑，不需要启动 GUI 或使用真实 API Key。

当前测试覆盖：

- 模糊搜索的匹配和排序
- API 配置的批量解析、新增和删除
- DeepSeek 查询响应的解析
- API Key 请求头的生成

在项目根目录运行：

```bash
python -m unittest discover -s tests -v
```

测试使用模拟 HTTP 响应，不会向 OpenCode、DeepSeek 或智谱服务发起真实查询，也不会修改项目中的正式配置文件。

## 自定义字体

字体文件属于本地资源，不会提交到仓库。`.gitignore` 会忽略 `script/ui/fonts/` 下的字体文件，但会保留其中的许可证文本。

### 文件放置位置

将字体文件放置到：

```text
script/ui/fonts/
```

当前程序默认查找以下文件：

```text
SourceHanSansSC-Regular.otf
SourceHanSansSC-Medium.otf
SourceHanSansSC-Bold.otf
JetBrainsMono-Regular.ttf
```

如果使用上述文件名，只需将字体复制到目录后运行程序即可。程序启动时会通过 `QFontDatabase.addApplicationFont()` 加载字体，加载失败时回退到系统字体。

### 使用其他字体

如果字体文件名不同，需要修改 `script/menu.py` 中的 `load_fonts()` 函数：

```python
fonts_dir = Path(__file__).with_name("ui") / "fonts"
regular_id = QFontDatabase.addApplicationFont(
    str(fonts_dir / "YourSans-Regular.ttf")
)
QFontDatabase.addApplicationFont(str(fonts_dir / "YourSans-Bold.ttf"))
QFontDatabase.addApplicationFont(str(fonts_dir / "YourMono-Regular.ttf"))
```

然后根据字体文件的实际字体族名称，修改 `script/ui/styles.qss` 中的字体配置：

```css
QMainWindow {
    font-family: "Your Sans";
}

QTextEdit, QLineEdit[role="secret"] {
    font-family: "Your Mono";
}
```

字体族名称应使用字体内部名称，不一定等于文件名。可以使用字体查看器确认名称。若字体包含授权限制，请确保使用方式符合其许可证要求。
