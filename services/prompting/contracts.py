from typing import Any, Dict, List, Optional


def build_selected_dimensions_block(dims: List[str], dimension_labels_cn: Dict[str, str]) -> Dict[str, Any]:
    selected_keys: List[str] = [d for d in (dims or []) if d in dimension_labels_cn and d != "total"]
    selected_titles: List[str] = [dimension_labels_cn[k] for k in selected_keys]
    selected_h2_lines = "\n".join([f"## {t}" for t in selected_titles]) if selected_titles else "（本次未选择维度）"
    selected_titles_joined = "、".join(selected_titles) if selected_titles else "无"
    return {
        "selected_keys": selected_keys,
        "selected_titles": selected_titles,
        "selected_h2_lines": selected_h2_lines,
        "selected_titles_joined": selected_titles_joined,
    }


def build_markdown_constraints_text(selected_dim_titles: List[str]) -> str:
    base = (
        "1) 仅输出 Markdown 正文，不要输出解释、前言、代码块围栏或额外说明。\n"
        "2) 一级标题必须严格且按以下顺序输出，名称必须完全一致：\n"
        "# 一、概览\n"
        "# 二、维度关键发现\n"
        "# 三、原因分析\n"
        "# 四、建议\n"
        "3) 除'维度关键发现'外，其他一级标题下不要创建维度型二级标题。\n"
    )
    if selected_dim_titles:
        dim_lines = "\n".join([f"## {t}" for t in selected_dim_titles])
        dim_part = (
            "4) 在'维度关键发现'章节下，只能使用以下二级标题（名称必须完全一致）：\n"
            f"{dim_lines}\n"
            "5) 不得输出未在上述列表中的维度二级标题。\n"
            "6) 若某个允许维度数据不足，可在该标题下说明'数据不足'，但不能改标题、不能删标题。\n"
        )
    else:
        dim_part = (
            "4) 本次未选择维度。在'维度关键发现'下不要输出二级标题，写本次'未选择维度分析'。\n"
            "5) 不得新增任何维度型二级标题。\n"
        )
    tail = "7) 不要输出任何图片占位符（如 {{image:...}}）,图片由系统后处理插入。"
    return base + dim_part + tail


def build_report_type_contract(report_type: str) -> Dict[str, str]:
    if report_type == "statistical":
        return {
            "report_type_name": "统计型",
            "analysis_goal": "识别总体规模、结构分布、TopN贡献和集中度特征。",
            "focus_points": "总量、占比、TopN、其他、集中度、维度对比",
            "overview_rule": "先概述总体规模，再说明结构分布与头部集中情况。",
            "reasoning_rule": "重点解释结构差异、头部贡献与潜在业务含义。",
            "advice_rule": "建议围绕资源配置、重点维度经营、长尾优化展开。",
        }
    return {
        "report_type_name": "趋势型",
        "analysis_goal": "识别整体趋势方向、波动特征、异常节点及维度驱动因素。",
        "focus_points": "趋势、拐点、峰谷、波动、增长贡献、异常期",
        "overview_rule": "先判断整体走势，再说明关键拐点与阶段变化。",
        "reasoning_rule": "重点解释维度驱动、波动来源及异常期可能原因。",
        "advice_rule": "建议围绕趋势延续、风险预警、波动治理展开。",
    }


def build_report_style_contract(report_style: Optional[str]) -> Dict[str, str]:
    style = (report_style or "standard").strip().lower()
    base_contracts = {
        "simple": {
            "style_name": "简明分析性",
            "writing_goal": "先结论后展开，用最少文字表达最关键发现。",
            "focus_rule": "优先输出3-5条关键结论，每条尽量附数字证据。",
            "reasoning_rule": "只保留必要解释，避免冗长推演。",
            "advice_rule": "建议简洁明晰，不超过3-5条。",
            "language_rule": "语言精炼，管理层快速可读。",
        },
        "attribution": {
            "style_name": "归因解析型",
            "writing_goal": "不仅描述现象，还要解释变化由谁驱动、为什么发生。",
            "focus_rule": "必须区分主因、次因，并说明结构占比与关键贡献来源。",
            "reasoning_rule": "优先解释业务机制；无法验证因果必须标注推测",
            "advice_rule": "建议需与原因分析一一对应。",
            "language_rule": "强调因果链路和证据对应。",
        },
        "forecast": {
            "style_name": "预测建议型",
            "writing_goal": "在现有数据基础上做方向判断，并提出可执行动作。",
            "focus_rule": "必须包含短期/中期走势、风险点与触发条件。",
            "reasoning_rule": "预测必须基于已给数据，不得写成确定事实。",
            "advice_rule": "建议要含优先级、动作对象、预期影响。",
            "language_rule": "偏经营决策表达，强调行动性。",
        },
        "standard": {
            "style_name": "综合标准型",
            "writing_goal": "兼顾概览、发现、归因和建议，保持完整平衡。",
            "focus_rule": "覆盖事实、分析和建议，不偏废。",
            "reasoning_rule": "结论与证据必须对应。",
            "advice_rule": "建议与关键发现保持一致。",
            "language_rule": "专业、完整、稳定。",
        },
    }
    contract = base_contracts.get(style, base_contracts["standard"]).copy()
    style_instructions = f"""- 风格类型：{contract['style_name']}
- 写作目标：{contract['writing_goal']}
- 输出侧重点：{contract['focus_rule']}
- 推理要求：{contract['reasoning_rule']}
- 建议要求：{contract['advice_rule']}
- 语言要求：{contract['language_rule']}

【风格专属指令】
{contract['style_name']}：{contract['writing_goal']} 具体执行时，{contract['focus_rule']} 在分析原因时，{contract['reasoning_rule']} 提出建议时，{contract['advice_rule']} 整体语言风格要求：{contract['language_rule']}"""
    contract["style_instructions"] = style_instructions
    return contract


def build_format_requirements() -> Dict[str, str]:
    return {
        "sections": "概览/维度关键发现/原因分析/建议",
        "number_format": "金额保留2位小数，比例保留2位小数",
        "length_limit": "600-1000字",
        "data_boundary": "仅以本次提供的统计结果与时间区间为依据，不引用外部数据。",
        "evidence_rule": "每条关键结论都需对应具体数字、占比、变化幅度或排序证据。",
        "expression_rule": "先结论后解释，语句清晰、避免空泛描述，术语与口径保持一致。",
        "uncertainty_rule": "对无法由现有数据验证的因果与预测，必须明确标注为推测或不确定。",
        "forbidden_rule": "禁止编造数据、禁止与口径冲突、禁止输出与本次报告类型和风格无关的泛化段落。",
    }
