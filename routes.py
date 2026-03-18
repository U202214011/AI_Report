from flask import request, jsonify, render_template, Response
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
    generate_pie_chart
)
from llm_service import stream_glm_report

# ---- 可手动修改的配置区 ----
METRIC_LABELS = {
    "sales_amount": "销售额",
    "order_count": "订单数",
    "avg_order_value": "客单价"
}

SHOW_BAR_IN_TREND = True
SHOW_PIE_IN_STAT = True

def register_routes(app):

    @app.route("/")
    def index():
        return render_template("index.html")

    # 仅返回 prompt 文本
    @app.route("/api/prompt", methods=["POST"])
    def generate_prompt():
        payload = request.get_json() or {}
        try:
            normalized = normalize_request(payload)
            prompt_bundle = build_prompt_bundle(normalized, plots=[])
            return jsonify({
                "prompt": prompt_bundle.get("prompt")
            })
        except Exception as e:
            return jsonify({"message": str(e)}), 500

    # 新增：调用智谱平台模型并流式输出文本报告
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
                return [
                    {"period": item["x"], "dimension": "总量", "value": item["y"]}
                    for item in series
                ]

            # --------- 统计型报告（柱状图 + 饼图） ---------
            if report_type == "statistical":
                # ---- 总量：按时间粒度画柱状图 ----
                if "total" in dims:
                    sql, params = build_period_trend(metric, gran, since, until)
                    rows = run_query(sql, params)
                    bar_rows = build_total_rows(rows)
                    if bar_rows:
                        plots.append({
                            "title": f"总量 {gran} 柱状图",
                            "image": generate_grouped_bar_chart(
                                bar_rows,
                                granularity=gran,
                                period_key="period",
                                dim_key="dimension",
                                categories=["总量"],
                                periods=periods_for_chart,
                                y_label=metric_label,
                                x_label="时间"
                            )
                        })
                    data.extend(rows)

                # ---- 维度柱状图（TopN + 其他）----
                for dim in [d for d in dims if d != "total"]:
                    # 取全量数据（避免 LIMIT TopN）
                    agg_payload = {
                        "reportType": "statistical",
                        "dimensions": [dim],
                        "metric": metric,
                        "since": since,
                        "until": until,
                        "topN": None,  # 关键：不要在 SQL 里 LIMIT
                        "filters": {}
                    }
                    rows = run_aggregation(agg_payload)

                    if rows:
                        top_categories = select_top_categories(rows, dim, topN)

                        top_rows = [r for r in rows if r.get(dim) in top_categories]
                        other_value = sum(
                            float(r.get("value") or 0)
                            for r in rows
                            if r.get(dim) not in top_categories
                        )

                        if other_value > 0:
                            top_rows.append({dim: "其他", "value": other_value})
                            top_categories = top_categories + ["其他"]

                        bar_rows = [
                            {"period": "总计", dim: r.get(dim), "value": r.get("value")}
                            for r in top_rows
                        ]
                        plots.append({
                            "title": f"{dim} 统计柱状图 Top{topN} + 其他",
                            "image": generate_grouped_bar_chart(
                                bar_rows,
                                granularity=gran,
                                period_key="period",
                                dim_key=dim,
                                categories=top_categories,
                                periods=["总计"],
                                y_label=metric_label,
                                x_label=None
                            )
                        })
                    data.extend(rows)

                # ---- 维度饼图（TopN + 其他）----
                if SHOW_PIE_IN_STAT:
                    for dim in [d for d in dims if d != "total"]:
                        pie_payload = {
                            "reportType": "statistical",
                            "dimensions": [dim],
                            "metric": metric,
                            "since": since,
                            "until": until,
                            "topN": None,  # 关键：不要在 SQL 里 LIMIT
                            "filters": {}
                        }
                        rows = run_aggregation(pie_payload)

                        if rows:
                            top_categories = select_top_categories(rows, dim, topN)
                            top_rows = [r for r in rows if r.get(dim) in top_categories]

                            other_value = sum(
                                float(r.get("value") or 0)
                                for r in rows
                                if r.get(dim) not in top_categories
                            )
                            if other_value > 0:
                                top_rows.append({dim: "其他", "value": other_value})

                            labels = [str(r.get(dim)) for r in top_rows]
                            values = [float(r.get("value") or 0) for r in top_rows]

                            plots.append({
                                "title": f"{dim} 饼图 Top{topN} + 其他",
                                "image": generate_pie_chart(labels, values)
                            })

            # --------- 趋势型报告（折线图 + 柱状图） ---------
            else:
                # 总量趋势折线
                if "total" in dims:
                    sql, params = build_period_trend(metric, gran, since, until)
                    rows = run_query(sql, params)
                    series = [{
                        "label": "总量",
                        "data": build_total_series(rows, granularity=gran, periods=periods_for_chart)
                    }]
                    if series[0]["data"]:
                        plots.append({
                            "title": f"总量 {gran} 趋势",
                            "image": generate_line_chart(series, gran, y_label=metric_label)
                        })
                    data.extend(rows)

                    # 总量柱状图
                    if SHOW_BAR_IN_TREND:
                        bar_rows = build_total_rows(rows)
                        if bar_rows:
                            plots.append({
                                "title": f"总量 {gran} 柱状图",
                                "image": generate_grouped_bar_chart(
                                    bar_rows,
                                    granularity=gran,
                                    period_key="period",
                                    dim_key="dimension",
                                    categories=["总量"],
                                    periods=periods_for_chart,
                                    y_label=metric_label
                                )
                            })

                # 维度趋势折线（TopN）
                for dim in [d for d in dims if d != "total"]:
                    sql, params = build_dimension_trend(metric, gran, dim, since, until)
                    rows = run_query(sql, params)
                    top_categories = select_top_categories(rows, dim, topN)
                    if top_categories:
                        rows = [r for r in rows if r.get(dim) in top_categories]

                    series = build_series_by_dimension(rows, dim, granularity=gran, periods=periods_for_chart)
                    if series:
                        plots.append({
                            "title": f"{dim} {gran} 趋势 Top{topN}",
                            "image": generate_line_chart(series, gran, y_label=metric_label)
                        })

                    if SHOW_BAR_IN_TREND and rows:
                        plots.append({
                            "title": f"{dim} {gran} 柱状图 Top{topN}",
                            "image": generate_grouped_bar_chart(
                                rows,
                                granularity=gran,
                                period_key="period",
                                dim_key=dim,
                                categories=top_categories,
                                periods=periods_for_chart,
                                y_label=metric_label
                            )
                        })
                    data.extend(rows)

            prompt_bundle = build_prompt_bundle(normalized, plots=plots)

            raw_output = {
                "summary": {
                    "metric": metric,
                    "reportType": report_type
                },
                "plots": plots,
                "tables": [],
                "data": data,
                "prompt": prompt_bundle.get("prompt"),
                "promptData": prompt_bundle.get("promptData"),
                "frontendSchema": prompt_bundle.get("frontendSchema")
            }

            return jsonify(adapt_report_output(raw_output))

        except Exception as e:
            return jsonify(adapt_report_output({"message": str(e)})), 500