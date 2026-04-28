# 📊 AI Report Generator (基于 Chinook 数据库的 AI 报告自动生成系统)

基于 **Chinook 数据库** 和 **智谱 GLM 大语言模型** 构建的智能化数据分析与报告自动生成系统。
本项目旨在通过自然语言与大模型结合，自动分析底层业务数据（如音乐商店的销售、客户、库存等），并生成多维度的数据可视化图表及深度的 AI 洞察报告。

### 🔗 核心依赖与资源链接
- **Chinook 数据库源项目**: [https://github.com/lerocha/chinook-database](https://github.com/lerocha/chinook-database)
- **智谱 GLM 模型官方开发文档**: [https://bigmodel.cn/dev/api#glm-4](https://bigmodel.cn/dev/api#glm-4)


## 🌟 核心特性 (Key Features)

- **🤖 智能分析 (AI-Powered)**：无缝集成智谱 GLM 模型（支持 GLM-4 及其各版本 API），将冰冷的数据转化为具备商业洞察的自然语言报告。
- **📈 自动可视化 (Auto-Visualization)**：基于查询数据自动生成图表（支持前端动态渲染及后端 Matplotlib/Echarts 构建）。
- **🗃️ 深度数据联动 (Database Integration)**：内嵌 Chinook 示例数据库（数字音乐商店），支持复杂的跨表 SQL 数据提取。
- **📄 多格式导出**：提供将生成的分析结果直接导出为美观文档的能力（基于 `python-docx` 等模块）。
- **🌐 友好的 Web 交互**：采用 Python Flask 构建轻量级 Web 后端，结合 HTML/CSS/JS 提供响应式的用户操作界面。


---

## 🛠️ 技术栈 (Tech Stack)

### Backend (后端)
- **Python 3.8+**
- **Web 框架**: [Flask](https://flask.palletsprojects.com/)
- **数据库**: MySQL (通过 `pymysql`, `mysql-connector-python`, `aiomysql`)
- **数据处理与分析**: `pandas`
- **AI 引擎**: 智谱大模型 SDK (`GLM-4.7`)

### Frontend (前端)
- HTML5, CSS3, JavaScript (原生与轻量级框架组合)
- 可视化库: 支持数据图表动态渲染 (通过 `charts` 模块)

---

## 📁 目录结构 (Directory Structure)

项目采用清晰的 MVC/模块化结构，提升代码可维护性与复用性：

```text
├── app.py                      # Flask 应用入口与主配置
├── routes.py                   # 路由控制器（API 端点与页面导航）
├── config.py                   # 核心配置文件（数据库配置、API 密钥等）
├── .env                        # 环境变量文件（请勿提交敏感信息）
├── requirements.txt            # Python 依赖包列表
├── database_indexes.sql        # 数据库索引优化脚本
├── prompt_templates.json       # GLM 提示词模板配置 (基础版)
├── prompt_templates_pro.json   # GLM 提示词模板配置 (进阶版)
├── prompt_data.py              # 提示词数据处理模块
├── models/                     # 数据库模型与实体层
├── services/                   # 业务逻辑层（与大模型交互、数据聚合等）
├── adapters/                   # 外部接口适配器层
├── charts/                     # 图表生成与可视化逻辑
├── templates/                  # 前端 HTML 模板目录
└── static/                     # 静态资源目录 (CSS, JS, Images)
```

---

## 🚀 快速开始 (Getting Started)

### 1. 环境准备 (Prerequisites)
- 安装 [Python 3.8+](https://www.python.org/downloads/)
- 安装 [MySQL](https://www.mysql.com/) 数据库服务器
- 获取 **智谱 AI API Key**，详见 [智谱 AI 开放平台接入指南](https://bigmodel.cn/dev/howuse/introduction)。

### 2. 克隆项目 (Clone Repository)
```bash
git clone https://github.com/U202214011/AI_Report.git
cd AI_Report
```

### 3. 安装依赖 (Install Dependencies)
建议使用虚拟环境：
```bash
pip install -r requirements.txt
```

### 4. 数据库初始化 (Database Setup)
1. 下载并安装 [Chinook 数据库 MySQL 版本](https://github.com/lerocha/chinook-database/tree/master/ChinookDatabase/DataSources)。
2. 在本地 MySQL 中新建数据库（如命名为 `chinook`），并导入官方提供的 `.sql` 脚本初始化表结构和数据。
3. 运行本项目提供的索引优化脚本：
```bash
mysql -u root -p chinook < database_indexes.sql
```

### 5. 环境变量配置 (Environment Configuration)
在项目根目录创建或编辑 `.env` 文件，填入你的实际参数：

```env
# Database Settings
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=chinook

# Zhipu AI Settings
ZHIPUAI_API_KEY=your_glm_api_key_here
```

### 6. 运行应用 (Run Application)
```bash
python app.py
```
> 服务器启动后，在浏览器访问 `http://127.0.0.1:5000` 即可进入系统。

---

## 🧩 核心工作流设计 (How it Works)

1. **模板选择**：系统读取 `prompt_templates_pro.json` 模板。
2. **数据汇聚**：用户在 Web 端发起报告请求，后端依据请求路由至 `services` 层，执行 SQL 查询聚合 Chinook 数据库中的业务指标。
3. **Prompt 注入**：将结构化指标 (`prompt_data.py`) 和业务上下文组合，并根据 [智谱 GLM API 文档规范](https://bigmodel.cn/dev/api) 输入给大模型。
4. **生成与排版**：获取大模型的深度推理文本，并利用 `charts` 层生成配套图表，最终在 `templates` 渲染呈现。

---

## 🤝 贡献指南 (Contributing)
欢迎对本项目提出改进建议！如果您发现任何 Bug 或有新功能想法，请通过 [Issue](https://github.com/U202214011/AI_Report/issues) 进行反馈，或直接提交 Pull Request。

## 📜 许可证 (License)
本项目开源，使用时请遵守相关依赖库及第三方平台的使用协议：
- [Chinook Database License](https://github.com/lerocha/chinook-database/blob/master/LICENSE.md)
- [智谱大模型服务条款](https://open.bigmodel.cn/dev/howuse/service-terms)
