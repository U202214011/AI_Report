# AI_Report

基于 Chinook 数据库的大语言模型 AI 报告自动生成系统

---

## 项目结构

```
AI_Report/
├── app.py                    # Flask 应用入口
├── routes.py                 # 路由注册
├── config.py                 # 配置
├── requirements.txt          # Python 依赖
├── prompt_templates.json     # Prompt 模板
├── prompt_data.py
├── adapters/                 # 适配器层
├── models/                   # 数据模型
├── services/                 # 业务逻辑层
├── charts/                   # 图表生成
└── templates/                # Flask Jinja2 模板（前端页面）
    ├── index.html            # 主工作台（Vue 3 + Bootstrap 5）
    └── template_designer.html# 模板配置中心（Vue 3 + Bootstrap 5）
```

---

## 前端框架说明

前端使用 **Vue 3**（CDN 引入，无需构建工具）+ **Bootstrap 5**，所有依赖通过 CDN 加载，无需 npm / webpack。

| 库 | 版本 | 引入方式 |
|----|------|---------|
| Vue 3 | latest | CDN (`vue.global.prod.js`) |
| Bootstrap | 5.3.3 | CDN |
| marked.js | latest | CDN（Markdown 渲染） |
| jszip | latest | CDN（DOCX 预览） |
| docx-preview | 0.3.2 | CDN（DOCX 预览） |

> **注意**：Vue 模板定界符已改为 `[[ ]]`（而非默认的 `{{ }}`），以避免与 Flask/Jinja2 模板语法冲突。

---

## PyCharm 开发环境搭建

### 1. 配置 Python 解释器

在 PyCharm 中创建或使用已有的虚拟环境（推荐 Python 3.10+）：

```
文件 → 设置 → 项目 → Python 解释器 → 添加解释器 → 虚拟环境
```

### 2. 安装 Python 依赖

在 PyCharm 内置终端或系统终端中执行：

```bash
# 升级 pip（可选，推荐）
pip install --upgrade pip

# 安装全部项目依赖
pip install -r requirements.txt
```

`requirements.txt` 包含以下依赖：

```
Flask
pymysql
mysql-connector-python
zai-sdk
python-dotenv
matplotlib
python-docx
python-dateutil
aiomysql
pandas
```

如需单独安装，可逐条执行：

```bash
pip install Flask
pip install pymysql
pip install mysql-connector-python
pip install zai-sdk
pip install python-dotenv
pip install matplotlib
pip install python-docx
pip install python-dateutil
pip install aiomysql
pip install pandas
```

### 3. 配置环境变量

复制或新建 `.env` 文件并填入数据库等配置：

```env
DATABASE_URL=mysql+pymysql://用户名:密码@主机:端口/chinook
# 其他所需的 API Key 等
```

### 4. 启动项目

在 PyCharm 内置终端执行：

```bash
python app.py
```

或直接在 PyCharm 中右键 `app.py` → **运行**。

启动后访问：
- 主工作台：http://localhost:5000/
- 模板配置中心：http://localhost:5000/template-designer

### 5. PyCharm 前端支持（可选）

PyCharm Professional 内置 Vue.js / Bootstrap 支持，无需额外安装插件。

如使用 PyCharm Community 版，可安装以下插件获得语法高亮：
- **Vue.js**（JetBrains 官方）

> 由于前端通过 CDN 引入，**无需安装 Node.js、npm 或任何前端构建工具**，直接运行 Flask 即可。
