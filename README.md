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
python -m venv venv
source venv/bin/activate  # Windows 环境使用 venv\Scripts\activate
pip install -r requirements.txt
```

### 4. 数据库初始化 (Database Setup)
1. 下载并安装 [Chinook 数据库 MySQL 版本](https://github.com/lerocha/chinook-database/tree/master/ChinookDatabase/DataSources)。
2. 在本地 MySQL 中新建数据库（如命名为 `chinook`），并导入官方提供的 `.sql` 脚本初始化表结构和数据。
3. 运行本项目提供的索引优化脚本：
```bash
mysql -u root -p chinook < database_indexes.sql
```

> 说明：MySQL InnoDB 的普通索引/主键索引底层默认为 **B+Tree**。  
> 项目中 `database_indexes.sql` 的 `CREATE INDEX` 即为 B+Tree 索引（未指定 `USING` 时默认使用 B+Tree）。

### 4.1 索引自动化机制（应用启动自检）
- 项目除了支持手工执行 `database_indexes.sql` 外，还支持在应用启动时自动执行索引自检。
- 启动入口：`/home/runner/work/AI_Report/AI_Report/app.py` 的 `create_app()` 会调用 `ensure_indexes()`。
- 实现位置：`/home/runner/work/AI_Report/AI_Report/models/db_init.py`
  - 通过 `SHOW INDEX FROM Invoice` 查询现有索引；
  - 若 `idx_invoice_invoice_date` 或 `idx_invoice_customer_id` 缺失，则自动创建；
  - 全流程幂等，已存在时不会重复创建。

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

## ✅ 测试方案与测试结果（功能、性能、非功能）

### A. 功能测试（按模块）

#### 模块A：SQL预览 `/api/query-preview`
- **测试方案**：覆盖统计型/趋势型、单维度/多维度、合法与非法时间范围。
- **测试结果**：
  - 返回 `queries[]`，包含 `sql`、`params`、`columns`、`rows`。
  - 时间范围输入异常时可被标准化处理，不会直接导致服务崩溃。
  - `total` 维度与普通维度均可正确生成查询。

#### 模块B：报告生成 `/api/generate`
- **测试方案**：统计型（柱状图+饼图）与趋势型（折线图）分开验证，维度从1个逐步扩展到多维。
- **测试结果**：
  - 可返回图表 Base64 与结构化数据。
  - TopN 聚合策略生效，维度过多时可聚焦关键类别。
  - 空维度场景可回退到 `total` 路径。

#### 模块C：LLM流式生成 `/api-llm/sse`
- **测试方案**：验证 SSE 事件序列（start / reasoning / content / done）与异常分支。
- **测试结果**：
  - 事件流完整。
  - 异常时返回 `error` 事件，不会出现无响应挂起。

#### 模块D：追问对话 `/api/chat/sse` + `/api/chat/context-check`
- **测试方案**：多轮追问、空消息、上下文接近上限等场景。
- **测试结果**：
  - `messages` 为空时会返回 400。
  - 可返回上下文占用状态（如 ok / warn / danger）供前端提示。
  - `client_trigger=start_report` 场景可产生首字延迟 timing 事件。

#### 模块E：报告导出 `/api/export/report`
- **测试方案**：空正文、空标题、带图表导出、模板切换。
- **测试结果**：
  - `report_markdown` 为空时返回 400。
  - 标题为空时默认标题为“数据分析报告”。
  - docx 导出流程可用，图文可正确写入。

#### 模块F：模板中心 `/api/export/template/*`
- **测试方案**：模板列表、保存、删除、预览完整流程。
- **测试结果**：
  - 模板 CRUD 可用。
  - 空内容场景下预览接口有后端兜底策略。

#### 模块G：单元测试
- **测试方案**：执行 `pytest -q` 回归测试。
- **测试结果**：
  - 当前仓库历史记录显示：`pytest -q` 可通过 15 个测试用例（覆盖 TopN / othersSharePct 等关键逻辑）。

### B. 性能测试（详细方案）

#### 1. 测试目标与关键指标
- **目标接口**：`/api/query-preview`、`/api/generate`、`/api/export/report`、`/api/chat/sse`
- **关键指标**：
  - 响应时间：平均值 / P95 / P99
  - 吞吐量：RPS
  - 错误率：4xx / 5xx
  - SSE 首字延迟：TTFT（Time To First Token）
  - 资源指标：CPU 峰值 / 内存峰值

#### 2. 分层压测设计
1. **冷启动测试**：重启服务后发送首个请求，衡量初始化耗时。
2. **稳态单并发**：并发=1，连续100次请求，作为基线时延。
3. **中并发压力**：并发=10/20，持续5分钟，观测性能拐点。
4. **峰值冲击**：并发=50，持续1分钟，评估系统抗压极限。
5. **长稳测试**：并发=10，持续30分钟，观测内存与连接稳定性。

#### 3. 数据集与场景控制
- 固定 Chinook 数据库数据规模，避免测试期间数据漂移。
- 固定三类业务场景：
  - 轻量场景：1维度、短时间窗口
  - 中量场景：3维度、1年窗口
  - 重量场景：7维度、全时间范围 + 导出操作

#### 4. 结果记录模板（论文可直接引用）
- 普通接口记录字段：
  - `avg / p95 / p99 / error_rate / RPS / CPU_peak / MEM_peak`
- SSE接口附加字段：
  - `TTFT_avg / TTFT_p95 / full_response_time`

#### 5. 结果解读要点
- `/api/query-preview` 主要受 SQL 复杂度与索引命中影响。
- `/api/generate` 随图表数量增加近似线性增长。
- `/api/export/report` 受图片数量与文档长度影响更明显。
- `/api/chat/sse` 主要受外部模型推理时延影响。

### C. 非功能性需求测试结果（文字叙述）

1. **安全性（SQL注入防护）**  
   查询构造使用参数化 `%s + params`，非拼接式注入风险可控；异常输入场景下接口返回错误信息而非执行恶意语句。

2. **可靠性（容错与降级）**  
   数据库连接存在重试机制，接口普遍提供异常捕获与 JSON 错误返回，避免未处理异常直接暴露给前端。

3. **可用性（错误提示清晰度）**  
   关键参数缺失时返回明确提示（如 `messages 不能为空`、`report_markdown 不能为空`），便于用户修复输入。

4. **兼容性（跨平台显示）**  
   图表层针对 Windows/macOS/Linux 提供字体策略，中文显示与负号渲染兼容性较好。

5. **可观测性（日志与诊断）**  
   查询执行、SSE 流转、导出流程具备日志点，便于定位慢请求与异常链路。

6. **可维护性（模块化）**  
   路由层、查询构造层、Prompt编排层、导出层职责分离，后续性能优化（索引、缓存、SQL调优）可局部迭代。

---

## 🤝 贡献指南 (Contributing)
欢迎对本项目提出改进建议！如果您发现任何 Bug 或有新功能想法，请通过 [Issue](https://github.com/U202214011/AI_Report/issues) 进行反馈，或直接提交 Pull Request。

## 📜 许可证 (License)
本项目开源，使用时请遵守相关依赖库及第三方平台的使用协议：
- [Chinook Database License](https://github.com/lerocha/chinook-database/blob/master/LICENSE.md)
- [智谱大模型服务条款](https://open.bigmodel.cn/dev/howuse/service-terms)
