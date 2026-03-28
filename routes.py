import logging
import json
import re
import html
from io import BytesIO
from flask import request, jsonify, render_template, Response, send_file

from api_adapter import normalize_request
from report_adapter import adapt_report_output
from prompt_data import build_prompt_bundle
from report_service import (
    build_period_trend,
    build_dimension_trend,
    build_period_range,
    build_total_series,
    run_query,
    generate_line_chart,
    run_aggregation,
    generate_grouped_bar_chart,
    select_top_categories,
    build_series_by_dimension,
    generate_pie_chart,
    normalize_time_range_for_debug,
    build_aggregation_query,
)
from llm_service import stream_glm_report, stream_glm_chat, estimate_messages_tokens
from export_service import (
    list_export_templates,
    load_template_config,
    render_markdown_to_docx_bytes,
    build_export_filename,
    inject_placeholders_by_sections,
    save_user_template_config,
    delete_user_template_config,
)
from schema_config import (
    get_metric_label_map,
    build_selected_dimensions,
    get_dimension_title_map
)

logger = logging.getLogger(__name__)

METRIC_LABELS = get_metric_label_map()
DIMENSION_TITLES = get_dimension_title_map(include_total=True)

SHOW_BAR_IN_TREND = True
SHOW_PIE_IN_STAT = True

MODEL_CONTEXT_LIMIT = 128000
CONTEXT_WARN_RATIO = 0.80
CONTEXT_DANGER_RATIO = 0.92

_UNRESOLVED_PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")

def _has_unresolved_placeholders(text: str) -> bool:
    return bool(_UNRESOLVED_PLACEHOLDER_RE.search(text or ""))

def _safe_float(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0

def _build_data_consistency_debug(raw_output: dict, normalized: dict) -> dict:
    prompt_data = raw_output.get("promptData") or {}
    report_type = normalized.get("reportType")
    metric = normalized.get("metric")
    since = normalized.get("since")
    until = normalized.get("until")

    time_norm = normalize_time_range_for_debug(since, until)

    series_sum = None
    total_val = None
    diff = None
    diff_pct = None

    llm_summary = (prompt_data.get("llmSummary") or {}).get("statistical" if report_type == "statistical" else "trend") or {}
    series = llm_summary.get("series") or []

    if report_type == "statistical":
        total_val = _safe_float(llm_summary.get("total"))
        if metric != "avg_order_value":
            series_sum = sum(_safe_float(i.get("y")) for i in series)
            diff = series_sum - total_val
            diff_pct = (diff / total_val * 100.0) if total_val else None

    prompt_text = raw_output.get("prompt") or ""
    template_debug = raw_output.get("templateDebug") or {}

    return {
        "metric": metric,
        "reportType": report_type,
        "normalizedRange": time_norm,
        "prompt": {
            "isEmpty": len(prompt_text.strip()) == 0,
            "length": len(prompt_text),
            "hasUnresolvedPlaceholders": _has_unresolved_placeholders(prompt_text),
            "templateDebug": template_debug
        },
        "consistency": {
            "seriesSum": series_sum,
            "total": total_val,
            "diff": diff,
            "diffPct": diff_pct,
            "isConsistent": (abs(diff) < 1e-6) if diff is not None else None
        }
    }

def _context_status(used_tokens: int, limit_tokens: int = MODEL_CONTEXT_LIMIT) -> dict:
    ratio = used_tokens / limit_tokens if limit_tokens > 0 else 0
    if ratio >= CONTEXT_DANGER_RATIO:
        level = "danger"
        msg = "上下文接近极限，建议立即开启历史压缩或新建会话。"
    elif ratio >= CONTEXT_WARN_RATIO:
        level = "warn"
        msg = "上下文已较高，建议精简历史消息。"
    else:
        level = "ok"
        msg = "上下文充足。"
    return {
        "level": level,
        "message": msg,
        "used_tokens_est": used_tokens,
        "limit_tokens_est": limit_tokens,
        "ratio": round(ratio, 4)
    }

def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {{json.dumps(data, ensure_ascii=False)}}\n\n"

def _sse_message(data) -> str:
    return f"data: {{json.dumps(data, ensure_ascii=False)}}\n\n"

def _log_sse_chunk(route_name: str, idx: int, chunk_type: str, content: str):
    logger.info(f"[{{route_name}}] chunk#{{idx}} type={{chunk_type}} len={{len(content or '')}}")

def _build_preview_html(report_title: str, report_markdown: str, template_cfg: dict) -> str:
    fonts = template_cfg.get("fonts", {})
    body_font = fonts.get("body", {"family": "宋体", "size_pt": 11})
    h1_font = fonts.get("h1", {"family": "微软雅黑", "size_pt": 15})
    page = template_cfg.get("page", {})
    margins = page.get("margin_cm", [2.5, 2.2, 2.5, 2.2])
    p_body = template_cfg.get("paragraph_styles", {}).get("body", {})
    line_spacing = p_body.get("line_spacing", 1.5)

    safe_title = html.escape(report_title or "模板预览")
    safe_text = html.escape(report_markdown or "").replace("\n", "<br/>")

    return f"""
    <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px;">
      <div style="margin:{{margins[0]}}cm {{margins[1]}}cm {{margins[2]}}cm {{margins[3]}}cm;">
        <h1 style="margin:0 0 10px 0;font-family:{{h1_font.get('family','微软雅黑')}};font-size:{{h1_font.get('size_pt',15)}}pt;">
          {{safe_title}}
        </h1>
        <div style="font-family:{{body_font.get('family','宋体')}};font-size:{{body_font.get('size_pt',11)}}pt;line-height:{{line_spacing}};">
          {{safe_text}}
        </div>
      </div>
    </div>
    """

def register_routes(app):

    def _dim_label(dim_key: str) -> str:
        return DIMENSION_TITLES.get(dim_key, dim_key)

    def _chart_title(dim_key: str | None, gran: str, chart_kind: str, top_n: int | None = None, report_type: str | None = None) -> str:
        dim_label = _dim_label(dim_key) if dim_key else "总量"

        if dim_key == "total":
            if chart_kind == "line":
                return f"{{dim_label}} {{gran}} 趋势"
            if chart_kind == "bar":
                return f"{{dim_label}} {{gran}} 柱状图"
            if chart_kind == "pie":
                return f"{{dim_label}} 饼图"
            return f"{{dim_label}} 图表"

        if report_type == "statistical":
            if chart_kind == "bar":
                return f"{{dim_label}} 统计柱状图 Top{{top_n}} + 其他"
            if chart_kind == "pie":
                return f"{{dim_label}} 饼图 Top{{top_n}} + 其他"

        if report_type == "trend":
            if chart_kind == "line":
                return f"{{dim_label}} {{gran}} 趋势 Top{{top_n}}"
            if chart_kind == "bar":
                return f"{{dim_label}} {{gran}} 柱状图 Top{{top_n}}"

        return f"{{dim_label}} 图表"

    def _make_plot(
        *,
        image: str,
        title: str,
        chart_kind: str,
        report_type: str,
        metric: str,
        metric_label: str,
        granularity: str,
        dim_key: str | None = None,
        top_n: int | None = None,
        scope: str = "dimension",
        categories: list | None = None,
        periods: list | None = None
    ) -> dict:
        dimension_key = dim_key or "total"
        dimension_label = _dim_label(dimension_key)

        return {
            "title": title,
            "image": image,
            "meta": {
                "dimension_key": dimension_key,
                "dimension_label": dimension_label,
                "metric_key": metric,
                "metric_label": metric_label,
                "chart_kind": chart_kind,
                "report_type": report_type,
                "granularity": granularity,
                "top_n": top_n,
                "scope": scope,
                "categories": categories or [],
                "periods": periods or []
            }
        }

    def _build_plot_images_and_meta(plots: list[dict]) -> tuple[dict, dict]:
        plot_images = {}
        plot_images_meta = {}

        for idx, plot in enumerate(plots, start=1):
            meta = plot.get("meta") or {}
            dim_key = str(meta.get("dimension_key") or "total").strip().lower()
            chart_kind = str(meta.get("chart_kind") or "chart").strip().lower()
            scope = str(meta.get("scope") or ("overview" if dim_key == "total" else "dimension")).strip().lower()

            image_key = f"{{scope}}__{{dim_key}}__{{chart_kind}}__{{idx}}"
            plot_images[image_key] = plot.get("image")
            plot_images_meta[image_key] = meta

        return plot_images, plot_images_meta

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/query-preview", methods=["POST"])
    def query_preview():
        """
        读取用户筛选配置，动态生成 SQL 并执行查询，返回 SQL 语句和查询结果。
        返回格式: { "queries": [ { "label", "sql", "params", "columns", "rows" } ] }
        """
        payload = request.get_json() or {}
        try:
            normalized = normalize_request(payload)
            report_type = normalized["reportType"]
            metric = normalized["metric"]
            gran = normalized.get("granularity") or "month"
            topN = int(normalized.get("topN", 10))
            since = normalized.get("since")
            until = normalized.get("until")

            dims = normalized.get("dimensions") or []
            if not dims:
                dims = ["total"]

            queries = []

            # --- 总量查询 ---
            if "total" in dims:
                sql, params = build_period_trend(metric, gran, since, until)
                rows = run_query(sql, params)
                columns = list(rows[0].keys()) if rows else ["period", "value"]
                queries.append({
                    "label": "总量趋势查询",
                    "sql": sql.strip(),
                    "params": [str(p) for p in params],
                    "columns": columns,
                    "rows": rows
                })

            # --- 各维度查询 ---
            for dim in [d for d in dims if d != "total"]:
                dim_label = DIMENSION_TITLES.get(dim, dim)

                if report_type == "statistical":
                    # 统计型：聚合查询
                    agg_payload = {
                        "reportType": "statistical",
                        "dimensions": [dim],
                        "metric": metric,
                        "since": since,
                        "until": until,
                        "topN": None,
                        "filters": {}
                    }
                    agg_sql, agg_params = build_aggregation_query(agg_payload)
                    rows = run_query(agg_sql, agg_params)
                    # 应用 TopN 筛选
                    top_categories = select_top_categories(rows, dim, topN)
                    display_rows = [r for r in rows if r.get(dim) in top_categories]
                    columns = list(display_rows[0].keys()) if display_rows else [dim, "value"]
                    queries.append({
                        "label": f"{{dim_label}} 统计聚合 (Top{{topN}})",
                        "sql": agg_sql.strip(),
                        "params": [str(p) for p in agg_params],
                        "columns": columns,
                        "rows": display_rows
                    })
                else:
                    # 趋势型：维度趋势查询
                    sql, params = build_dimension_trend(metric, gran, dim, since, until)
                    rows = run_query(sql, params)
                    top_categories = select_top_categories(rows, dim, topN)
                    display_rows = [r for r in rows if r.get(dim) in top_categories] if top_categories else rows
                    columns = list(display_rows[0].keys()) if display_rows else ["period", dim, "value"]
                    queries.append({
                        "label": f"{{dim_label}} 趋势查询 (Top{{topN}})",
                        "sql": sql.strip(),
                        "params": [str(p) for p in params],
                        "columns": columns,
                        "rows": display_rows
                    })

            return jsonify({"queries": queries})
        except Exception as e:
            logger.exception(f"[/api/query-preview] error: {{e}}")
            return jsonify({"message": str(e)}), 500

    @app.route("/api/prompt", methods=["POST"])
    def generate_prompt():
        payload = request.get_json() or {}
        try:
            normalized = normalize_request(payload)
            prompt_bundle = build_prompt_bundle(normalized, plots=[])  
            return jsonify({
                "prompt": prompt_bundle.get("prompt"),
                "templateDebug": prompt_bundle.get("templateDebug", {})
            })
        except Exception as e:
            return jsonify({"message": str(e)}), 500

    @app.route("/api-llm", methods=["POST"])
    def generate_llm_report():
        payload = request.get_json() or {}
        try:
            normalized = normalize_request(payload)
            prompt_bundle = build_prompt_bundle(normalized, plots=[])  
            prompt_text = prompt_bundle.get("prompt") or ""

            def event_stream():
                for chunk in stream_glm_report(prompt_text):
                    content = chunk.get("content") or ""
                    if content:
                        yield content

            return Response(event_stream(), mimetype="text/plain")
        except Exception as e:
            return jsonify({"message": str(e)}), 500

    @app.route("/api-llm/sse", methods=["POST"])
    def generate_llm_report_sse():
        payload = request.get_json() or {}
        try:
            logger.info(f"[/api-llm/sse] payload_keys={{list(payload.keys())}}")

            normalized = normalize_request(payload)
            prompt_bundle = build_prompt_bundle(normalized, plots=[])  
            prompt_text = prompt_bundle.get("prompt") or ""
            show_reasoning = bool(payload.get("show_reasoning", True))

            logger.info(f"[/api-llm/sse] normalized={{normalized}}")
            logger.info(f"[/api-llm/sse] prompt_len={{len(prompt_text)}} show_reasoning={{show_reasoning}}")

            def stream():
                yield _sse("meta", {"status": "start"})
                chunk_idx = 0
                try:
                    for chunk in stream_glm_report(prompt_text):
                        chunk_idx += 1
                        t = chunk.get("type")
                        c = chunk.get("content") or ""

                        _log_sse_chunk("/api-llm/sse", chunk_idx, str(t), c)

                        if not c:
                            continue

                        if t == "error":
                            logger.error(f"[/api-llm/sse] model_error={{c}}")
                            yield _sse("error", {"message": c})
                            break

                        if t == "reasoning":
                            if show_reasoning:
                                yield _sse("reasoning", {"text": c})
                        else:
                            yield _sse("content", {"text": c})

                except Exception as e:
                    logger.exception(f"[/api-llm/sse] stream exception: {{e}}")
                    yield _sse("error", {"message": str(e)})
                finally:
                    yield _sse("meta", {"status": "done"})
                    logger.info(f"[/api-llm/sse] stream done total_chunks={{chunk_idx}}")

            return Response(stream(), mimetype="text/event-stream")
        except Exception as e:
            logger.exception(f"[/api-llm/sse] route exception: {{e}}")
            return jsonify({"message": str(e)}), 500

    @app.route("/api/chat/context-check", methods=["POST"])
    def chat_context_check():
        payload = request.get_json() or {}
        messages = payload.get("messages") or []
        system_prompt = payload.get("systemPrompt") or ""
        full_messages = [{"role": "system", "content": system_prompt}] + (messages if isinstance(messages, list) else [])
        used = estimate_messages_tokens(full_messages)
        return jsonify(_context_status(used, MODEL_CONTEXT_LIMIT))

    @app.route("/api/chat/sse", methods=["POST"])
    def chat_sse():
        payload = request.get_json() or {}
        messages = payload.get("messages") or []
        system_prompt = payload.get("systemPrompt") or "你是资深数据分析助手，请严格依据给定报告数据进行回答。"
        show_reasoning = bool(payload.get("show_reasoning", True))

        logger.info(f"[/api/chat/sse] payload_keys={{list(payload.keys())}}")
        logger.info(f"[/api/chat/sse] messages_count={{(len(messages) if isinstance(messages, list) else -1)}} show_reasoning={{show_reasoning}}")
        if messages and isinstance(messages, list):
            last_msg = messages[-1]
            logger.info(f"[/api/chat/sse] last_message_role={{last_msg.get('role')}} content_length={{len(str(last_msg.get('content', '')))}}")

        if not isinstance(messages, list) or len(messages) == 0:
            return jsonify({"message": "messages 不能为空"}), 400

        full_messages = [{"role": "system", "content": system_prompt}] + messages
        used = estimate_messages_tokens(full_messages)
        ctx = _context_status(used, MODEL_CONTEXT_LIMIT)
        logger.info(f"[/api/chat/sse] context={{ctx}}")

        def stream():
            yield _sse("context", ctx)
            yield _sse("meta", {"status": "start"})
            chunk_idx = 0

            try:
                for chunk in stream_glm_chat(full_messages):
                    chunk_idx += 1
                    t = chunk.get("type")
                    c = chunk.get("content") or ""

                    _log_sse_chunk("/api/chat/sse", chunk_idx, str(t), c)

                    if not c:
                        continue

                    if t == "error":
                        logger.error(f"[/api/chat/sse] model_error={{c}}")
                        yield _sse("error", {"message": c})
                        break

                    if t == "reasoning":
                        if show_reasoning:
                            yield _sse("reasoning", {"text": c})
                    else:
                        yield _sse("content", {"text": c})

            except Exception as e:
                logger.exception(f"[/api/chat/sse] stream exception: {{e}}")
                yield _sse("error", {"message": str(e)})
            finally:
                yield _sse("meta", {"status": "done"})
                logger.info(f"[/api/chat/sse] stream done total_chunks={{chunk_idx}}")

        return Response(stream(), mimetype="text/event-stream")

    @app.route("/api/generate", methods=["POST"])
    def generate_report():
        payload = request.get_json() or {}
        try:
            normalized = normalize_request(payload)
            report_type = normalized["reportType"]

            plots = []
            data = []

            dims = normalized.get("dimensions") or []
            if not dims:
                dims = ["total"]

            metric = normalized["metric"]
            metric_label = METRIC_LABELS.get(metric, metric)
            gran = normalized.get("granularity") or "month"
            topN = int(normalized.get("topN", 10))
            since = normalized.get("since")
            until = normalized.get("until")

            periods = build_period_range(gran, since, until)
            periods_for_chart = periods if periods else None

            def build_total_rows(rows):
                series = build_total_series(rows, granularity=gran, periods=periods_for_chart)
                return [{"period": item["x"], "dimension": "总量", "value": item["y"]} for item in series]

            if report_type == "statistical":
                if "total" in dims:
                    sql, params = build_period_trend(metric, gran, since, until)
                    rows = run_query(sql, params)
                    bar_rows = build_total_rows(rows)
                    if bar_rows:
                        plots.append(_make_plot(
                            image=generate_grouped_bar_chart(
                                bar_rows,
                                granularity=gran,
                                period_key="period",
                                dim_key="dimension",
                                categories=["总量"],
                                periods=periods_for_chart,
                                y_label=metric_label,
                                x_label="时间"
                            ),
                            title=_chart_title("total", gran, "bar", report_type="statistical"),
                            chart_kind="bar",
                            report_type="statistical",
                            metric=metric,
                            metric_label=metric_label,
                            granularity=gran,
                            dim_key="total",
                            top_n=None,
                            scope="overview",
                            categories=["总量"],
                            periods=periods_for_chart or []
                        ))
                    data.extend(rows)

                for dim in [d for d in dims if d != "total"]:
                    agg_payload = {
                        "reportType": "statistical",
                        "dimensions": [dim],
                        "metric": metric,
                        "since": since,
                        "until": until,
                        "topN": None,
                        "filters": {}
                    }
                    rows = run_aggregation(agg_payload)
                    if rows:
                        top_categories = select_top_categories(rows, dim, topN)
                        top_rows = [r for r in rows if r.get(dim) in top_categories]
                        other_value = sum(float(r.get("value") or 0) for r in rows if r.get(dim) not in top_categories)
                        if other_value > 0:
                            top_rows.append({dim: "其他", "value": other_value})
                            top_categories = top_categories + ["其他"]

                        bar_rows = [{"period": "总计", dim: r.get(dim), "value": r.get("value")} for r in top_rows]
                        plots.append(_make_plot(
                            image=generate_grouped_bar_chart(
                                bar_rows,
                                granularity=gran,
                                period_key="period",
                                dim_key=dim,
                                categories=top_categories,
                                periods=["总计"],
                                y_label=metric_label,
                                x_label=None
                            ),
                            title=_chart_title(dim, gran, "bar", top_n=topN, report_type="statistical"),
                            chart_kind="bar",
                            report_type="statistical",
                            metric=metric,
                            metric_label=metric_label,
                            granularity=gran,
                            dim_key=dim,
                            top_n=topN,
                            scope="dimension",
                            categories=top_categories,
                            periods=["总计"]
                        ))
                    data.extend(rows)

                if SHOW_PIE_IN_STAT:
                    for dim in [d for d in dims if d != "total"]:
                        pie_payload = {
                            "reportType": "statistical",
                            "dimensions": [dim],
                            "metric": metric,
                            "since": since,
                            "until": until,
                            "topN": None,
                            "filters": {}
                        }
                        rows = run_aggregation(pie_payload)
                        if rows:
                            top_categories = select_top_categories(rows, dim, topN)
                            top_rows = [r for r in rows if r.get(dim) in top_categories]
                            other_value = sum(float(r.get("value") or 0) for r in rows if r.get(dim) not in top_categories)
                            if other_value > 0:
                                top_rows.append({dim: "其他", "value": other_value})
                            labels = [str(r.get(dim)) for r in top_rows]
                            values = [float(r.get("value") or 0) for r in top_rows]
                            plots.append(_make_plot(
                                image=generate_pie_chart(labels, values),
                                title=_chart_title(dim, gran, "pie", top_n=topN, report_type="statistical"),
                                chart_kind="pie",
                                report_type="statistical",
                                metric=metric,
                                metric_label=metric_label,
                                granularity=gran,
                                dim_key=dim,
                                top_n=topN,
                                scope="dimension",
                                categories=labels,
                                periods=[]
                            ))
            else:
                if "total" in dims:
                    sql, params = build_period_trend(metric, gran, since, until)
                    rows = run_query(sql, params)
                    series = [{"label": "总量", "data": build_total_series(rows, granularity=gran, periods=periods_for_chart)}]
                    if series[0]["data"]:
                        plots.append(_make_plot(
                            image=generate_line_chart(series, gran, y_label=metric_label),
                            title=_chart_title("total", gran, "line", report_type="trend"),
                            chart_kind="line",
                            report_type="trend",
                            metric=metric,
                            metric_label=metric_label,
                            granularity=gran,
                            dim_key="total",
                            top_n=None,
                            scope="overview",
                            categories=["总量"],
                            periods=periods_for_chart or []
                        ))
                    data.extend(rows)

                    if SHOW_BAR_IN_TREND:
                        bar_rows = build_total_rows(rows)
                        if bar_rows:
                            plots.append(_make_plot(
                                image=generate_grouped_bar_chart(
                                    bar_rows,
                                    granularity=gran,
                                    period_key="period",
                                    dim_key="dimension",
                                    categories=["总量"],
                                    periods=periods_for_chart,
                                    y_label=metric_label
                                ),
                                title=_chart_title("total", gran, "bar", report_type="trend"),
                                chart_kind="bar",
                                report_type="trend",
                                metric=metric,
                                metric_label=metric_label,
                                granularity=gran,
                                dim_key="total",
                                top_n=None,
                                scope="overview",
                                categories=["总量"],
                                periods=periods_for_chart or []
                            ))

                for dim in [d for d in dims if d != "total"]:
                    sql, params = build_dimension_trend(metric, gran, dim, since, until)
                    rows = run_query(sql, params)
                    top_categories = select_top_categories(rows, dim, topN)
                    if top_categories:
                        rows = [r for r in rows if r.get(dim) in top_categories]

                    series = build_series_by_dimension(rows, dim, granularity=gran, periods=periods_for_chart)
                    if series:
                        plots.append(_make_plot(
                            image=generate_line_chart(series, gran, y_label=metric_label),
                            title=_chart_title(dim, gran, "line", top_n=topN, report_type="trend"),
                            chart_kind="line",
                            report_type="trend",
                            metric=metric,
                            metric_label=metric_label,
                            granularity=gran,
                            dim_key=dim,
                            top_n=topN,
                            scope="dimension",
                            categories=top_categories,
                            periods=periods_for_chart or []
                        ))

                    if SHOW_BAR_IN_TREND and rows:
                        plots.append(_make_plot(
                            image=generate_grouped_bar_chart(
                                rows,
                                granularity=gran,
                                period_key="period",
                                dim_key=dim,
                                categories=top_categories,
                                periods=periods_for_chart,
                                y_label=metric_label
                            ),
                            title=_chart_title(dim, gran, "bar", top_n=topN, report_type="trend"),
                            chart_kind="bar",
                            report_type="trend",
                            metric=metric,
                            metric_label=metric_label,
                            granularity=gran,
                            dim_key=dim,
                            top_n=topN,
                            scope="dimension",
                            categories=top_categories,
                            periods=periods_for_chart or []
                        ))
                    data.extend(rows)

            prompt_bundle = build_prompt_bundle(normalized, plots=plots)

            logger.info(f"[/api/generate] normalized={{normalized}}")
            logger.info(f"[/api/generate] templateDebug={{prompt_bundle.get('templateDebug', {})}}")
            logger.info(f"[/api/generate] prompt_len={{len(prompt_bundle.get('prompt') or '')}}")
            logger.info(f"[/api/generate] prompt_head={{(prompt_bundle.get('prompt') or '')[:300]}}")

            raw_output = {
                "meta": {
                    "schema": "universal-report-v2",
                    "metric": metric,
                    "metricLabel": metric_label,
                    "reportType": report_type
                },
                "summary": {"metric": metric, "reportType": report_type},
                "plots": plots,
                "tables": [],
                "data": data,
                "prompt": prompt_bundle.get("prompt"),
                "finalPrompt": prompt_bundle.get("prompt"),
                "promptData": prompt_bundle.get("promptData"),
                "frontendSchema": prompt_bundle.get("frontendSchema"),
                "templateDebug": prompt_bundle.get("templateDebug", {})
            }

            debug_flag = str(request.args.get("debug", "")).lower() in ("1", "true", "yes") or bool(payload.get("debug"))
            if debug_flag:
                raw_output["debug"] = _build_data_consistency_debug(raw_output, normalized)

            return jsonify(adapt_report_output(raw_output))
        except Exception as e:
            return jsonify(adapt_report_output({"message": str(e)})), 500

    @app.route("/api/export/templates", methods=["GET"])
    def export_templates():
        try:
            return jsonify({"templates": list_export_templates()})
        except Exception as e:
            return jsonify({"message": str(e)}), 500

    @app.route("/api/export/template/save", methods=["POST"])
    def export_template_save():
        payload = request.get_json() or {}
        template_config = payload.get("template_config") or {}

        if not isinstance(template_config, dict) or not template_config:
            return jsonify({"message": "template_config 不能为空"}), 400

        try:
            saved = save_user_template_config(template_config)
            return jsonify({"ok": True, "template_id": saved.get("id")})
        except Exception as e:
            logger.exception("[EXPORT_TEMPLATE_SAVE] failed: %s", e)
            return jsonify({"message": str(e)}), 500

    @app.route("/api/export/template/delete", methods=["POST"])
    def export_template_delete():
        payload = request.get_json() or {}
        template_id = (payload.get("template_id") or "").strip()
        if not template_id:
            return jsonify({"message": "template_id 不能为空"}), 400
        try:
            delete_user_template_config(template_id)
            return jsonify({"ok": True})
        except FileNotFoundError as e:
            return jsonify({"message": str(e)}), 404
        except Exception as e:
            logger.exception("[EXPORT_TEMPLATE_DELETE] failed: %s", e)
            return jsonify({"message": str(e)}), 500

    @app.route("/api/export/template/<template_id>", methods=["GET"])
    def export_template_get(template_id: str):
        try:
            cfg = load_template_config(template_id)
            return jsonify(cfg)
        except Exception as e:
            logger.exception("[EXPORT_TEMPLATE_GET] failed: %s", e)
            return jsonify({"message": str(e)}), 500

    @app.route("/template-designer")
    def template_designer():
        return render_template("template_designer.html")

    @app.route("/api/export/template/preview-docx", methods=["POST"])
    def export_template_preview_docx():
        payload = request.get_json() or {}
        template_config = payload.get("template_config") or {}
        report_title = (payload.get("report_title") or "").strip() or "模板预览标题"
        report_markdown = (payload.get("report_markdown") or "").strip() or "这是模板预览正文。\n\n## 二级标题\n\n正文段落内容示例。"

        try:
            buf = render_markdown_to_docx_bytes(
                report_markdown=report_markdown,
                template_config=template_config,
                report_title=report_title,
                plot_images={},
                plot_images_meta={},
                selected_dimensions=[]
            )
            return send_file(
                BytesIO(buf),
                as_attachment=True,
                download_name="template_preview.docx",
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        except Exception as e:
            logger.exception("[EXPORT_TEMPLATE_PREVIEW_DOCX] failed: %s", e)
            return jsonify({"message": str(e)}), 500

    @app.route("/api/export/template/preview-html", methods=["POST"])
    def export_template_preview_html():
        payload = request.get_json() or {}
        template_config = payload.get("template_config") or {}
        report_title = (payload.get("report_title") or "").strip() or "模板预览标题"
        report_markdown = (payload.get("report_markdown") or "").strip() or "这是模板预览正文。"
        try:
            html_str = _build_preview_html(report_title, report_markdown, template_config)
            return jsonify({"html": html_str})
        except Exception as e:
            logger.exception("[EXPORT_TEMPLATE_PREVIEW_HTML] failed: %s", e)
            return jsonify({"message": str(e)}), 500

    @app.route("/api/export/report", methods=["POST"])
    def export_report():
        payload = request.get_json() or {}
        report_markdown = (payload.get("report_markdown") or "").strip()
        if not report_markdown:
            return jsonify({"message": "report_markdown 不能为空"}), 400

        template_id = payload.get("template_id")
        template_config = payload.get("template_config")
        report_title = (payload.get("report_title") or "").strip() or "Chinook 数据分析报告"
        plot_images = payload.get("plot_images") or {}
        plot_images_meta = payload.get("plot_images_meta") or {}
        selected_dimensions = payload.get("selected_dimensions") or []

        try:
            if template_config and isinstance(template_config, dict):
                cfg = template_config
            elif template_id:
                cfg = load_template_config(template_id)
            else:
                cfg = load_template_config("cn_management_a4")

            report_markdown = inject_placeholders_by_sections(
                report_markdown,
                plot_images=plot_images,
                plot_images_meta=plot_images_meta,
                selected_dimensions=selected_dimensions
            )

            buf = render_markdown_to_docx_bytes(
                report_markdown=report_markdown,
                template_config=cfg,
                report_title=report_title,
                plot_images=plot_images,
                plot_images_meta=plot_images_meta,
                selected_dimensions=selected_dimensions
            )
            filename = build_export_filename(report_title, cfg.get("id", "report"))

            return send_file(
                BytesIO(buf),
                as_attachment=True,
                download_name=filename,
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        except Exception as e:
            logger.exception("[EXPORT_REPORT] failed: %s", e)
            return jsonify({"message": str(e)}), 500
