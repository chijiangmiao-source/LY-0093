import flet as ft
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
from database import (
    init_db, get_all_records, create_record, update_record, delete_record,
    get_record_by_id, get_records_by_hall, get_all_halls, get_reason_statistics,
    get_time_slot_statistics, get_daily_deviation_trend, get_review_alerts,
    calculate_deviation, get_records_with_filters, update_handling_info,
    get_hall_completion_rate, get_reason_handling_time, get_incomplete_records,
    get_handling_trend, get_handling_statistics
)


DEVIATION_REASONS = [
    "设备故障", "影片拷贝问题", "观众入场延迟", "前一场超时",
    "广告播放延误", "技术调试", "人员调度问题", "其他"
]


def format_datetime(dt_str):
    if not dt_str:
        return "-"
    try:
        return datetime.fromisoformat(dt_str).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return dt_str


def main(page: ft.Page):
    page.title = "影院排片执行偏差记录器"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window.width = 1200
    page.window.height = 800
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO

    init_db()

    current_view = "list"
    editing_record_id = None
    selected_hall = None
    closure_editing_record_id = None

    def switch_view(view, record_id=None, hall=None, closure_edit_id=None):
        nonlocal current_view, editing_record_id, selected_hall, closure_editing_record_id
        current_view = view
        editing_record_id = record_id
        selected_hall = hall
        closure_editing_record_id = closure_edit_id
        render_page()

    def show_snackbar(message, color=ft.colors.BLUE):
        page.snack_bar = ft.SnackBar(
            ft.Text(message),
            bgcolor=color,
            duration=3000
        )
        page.snack_bar.open = True
        page.update()

    def build_app_bar():
        return ft.AppBar(
            title=ft.Text("影院排片执行偏差记录器", size=20, weight=ft.FontWeight.BOLD),
            bgcolor=ft.colors.BLUE_700,
            color=ft.colors.WHITE,
            actions=[
                ft.IconButton(
                    icon=ft.icons.LIST,
                    tooltip="记录列表",
                    on_click=lambda e: switch_view("list"),
                    icon_color=ft.colors.WHITE
                ),
                ft.IconButton(
                    icon=ft.icons.MEETING_ROOM,
                    tooltip="影厅查看",
                    on_click=lambda e: switch_view("hall_view"),
                    icon_color=ft.colors.WHITE
                ),
                ft.IconButton(
                    icon=ft.icons.ANALYTICS,
                    tooltip="统计分析",
                    on_click=lambda e: switch_view("stats"),
                    icon_color=ft.colors.WHITE
                ),
                ft.IconButton(
                    icon=ft.icons.WARNING_AMBER,
                    tooltip="复查提醒",
                    on_click=lambda e: switch_view("alerts"),
                    icon_color=ft.colors.WHITE
                ),
                ft.IconButton(
                    icon=ft.icons.LOOP,
                    tooltip="闭环管理",
                    on_click=lambda e: switch_view("closure_management"),
                    icon_color=ft.colors.WHITE
                ),
                ft.IconButton(
                    icon=ft.icons.DASHBOARD,
                    tooltip="闭环统计",
                    on_click=lambda e: switch_view("closure_stats"),
                    icon_color=ft.colors.WHITE
                ),
            ]
        )

    def build_record_list_view():
        records = get_all_records()
        review_alerts = get_review_alerts()
        alert_count = len(review_alerts)

        columns = [
            ft.DataColumn(ft.Text("操作", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("记录编号", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("影片名称", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("影厅", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("计划开场", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("实际开场", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("偏差(分钟)", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("偏差原因", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("影响下一场", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("复查提醒", weight=ft.FontWeight.BOLD)),
        ]

        rows = []
        for rec in records:
            deviation_color = ft.colors.RED if abs(rec["deviation_minutes"]) > 15 else (
                ft.colors.ORANGE if rec["deviation_minutes"] != 0 else ft.colors.GREEN
            )
            is_serious_advance = rec["deviation_minutes"] <= -15
            deviation_content = ft.Column(
                [
                    ft.Text(str(rec["deviation_minutes"]), color=deviation_color, weight=ft.FontWeight.BOLD),
                ] + (
                    [ft.Container(
                        content=ft.Text("严重偏差", size=10, color=ft.colors.WHITE, weight=ft.FontWeight.BOLD),
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                        bgcolor=ft.colors.RED,
                        border_radius=4,
                    )] if is_serious_advance else []
                ),
                spacing=3,
                tight=True
            )
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(
                            ft.Row([
                                ft.IconButton(
                                    ft.icons.EDIT,
                                    icon_size=20,
                                    tooltip="编辑",
                                    on_click=lambda e, rid=rec["id"]: switch_view("form", record_id=rid)
                                ),
                                ft.IconButton(
                                    ft.icons.DELETE,
                                    icon_size=20,
                                    tooltip="删除",
                                    icon_color=ft.colors.RED,
                                    on_click=lambda e, rid=rec["id"]: handle_delete(rid)
                                ),
                            ])
                        ),
                        ft.DataCell(ft.Text(rec["record_no"])),
                        ft.DataCell(ft.Text(rec["movie_name"])),
                        ft.DataCell(ft.Text(rec["hall_no"])),
                        ft.DataCell(ft.Text(format_datetime(rec["planned_start"]))),
                        ft.DataCell(ft.Text(format_datetime(rec["actual_start"]))),
                        ft.DataCell(deviation_content),
                        ft.DataCell(ft.Text(rec["deviation_reason"] or "-")),
                        ft.DataCell(ft.Text("是" if rec["affects_next"] else "否")),
                        ft.DataCell(
                            ft.Row([
                                ft.Icon(ft.icons.WARNING_AMBER, color=ft.colors.ORANGE, size=18) if rec["review_alert"] else ft.Text("-"),
                            ])
                        ),
                    ]
                )
            )

        content = ft.Column([
            ft.Row([
                ft.Text("排片记录列表", size=24, weight=ft.FontWeight.BOLD),
                ft.Container(width=20),
                ft.Text(f"共 {len(records)} 条记录", size=14, color=ft.colors.GREY_700),
                ft.Container(expand=True),
                ft.Badge(
                    content=ft.IconButton(
                        ft.icons.WARNING_AMBER,
                        icon_color=ft.colors.ORANGE,
                        on_click=lambda e: switch_view("alerts")
                    ),
                    text=str(alert_count) if alert_count > 0 else None,
                    bgcolor=ft.colors.RED,
                ) if alert_count > 0 else ft.Container(),
                ft.Container(width=10),
                ft.ElevatedButton(
                    "新增记录",
                    icon=ft.icons.ADD,
                    bgcolor=ft.colors.BLUE_700,
                    color=ft.colors.WHITE,
                    on_click=lambda e: switch_view("form")
                ),
            ], alignment=ft.MainAxisAlignment.START),
            ft.Divider(),
            ft.Container(
                content=ft.DataTable(
                    columns=columns,
                    rows=rows,
                    horizontal_lines=ft.BorderSide(1, ft.colors.GREY_300),
                    vertical_lines=ft.BorderSide(1, ft.colors.GREY_300),
                    heading_row_color=ft.colors.BLUE_50,
                    show_bottom_border=True,
                    sort_column_index=4,
                    sort_ascending=False,
                ),
                expand=True
            )
        ], expand=True, spacing=15)

        return content

    movie_name_field = ft.TextField(label="影片名称", width=400)
    hall_no_field = ft.TextField(label="影厅编号", width=200)
    planned_start_field = ft.TextField(label="计划开场时间 (YYYY-MM-DD HH:MM)", width=300)
    actual_start_field = ft.TextField(label="实际开场时间 (YYYY-MM-DD HH:MM)", width=300)
    deviation_minutes_field = ft.TextField(label="偏差分钟数 (自动计算)", width=200, read_only=True, value="0")
    deviation_reason_dropdown = ft.Dropdown(
        label="偏差原因",
        width=300,
        options=[ft.dropdown.Option(r) for r in DEVIATION_REASONS]
    )
    deviation_reason_other = ft.TextField(label="其他原因说明", width=300, visible=False)
    affects_next_checkbox = ft.Checkbox(label="是否影响下一场", value=False)
    affected_record_no_field = ft.TextField(label="受影响场次编号", width=300, disabled=True)
    adjustment_suggestion_field = ft.TextField(label="调整建议", width=600, multiline=True, min_lines=3)
    record_no_display = ft.Text("")

    def on_deviation_reason_change(e):
        deviation_reason_other.visible = (deviation_reason_dropdown.value == "其他")
        page.update()

    def on_affects_next_change(e):
        affected_record_no_field.disabled = not affects_next_checkbox.value
        if not affects_next_checkbox.value:
            affected_record_no_field.value = ""
        page.update()

    def on_time_change(e):
        try:
            planned = planned_start_field.value.strip()
            actual = actual_start_field.value.strip()
            if planned and actual:
                planned_dt = datetime.strptime(planned, "%Y-%m-%d %H:%M").isoformat()
                actual_dt = datetime.strptime(actual, "%Y-%m-%d %H:%M").isoformat()
                dev = calculate_deviation(planned_dt, actual_dt)
                deviation_minutes_field.value = str(dev)
                if dev <= -15:
                    adjustment_suggestion_field.border_color = ft.colors.RED
                    adjustment_suggestion_field.label = "调整建议 (提前15分钟以上，必填)"
                else:
                    adjustment_suggestion_field.border_color = None
                    adjustment_suggestion_field.label = "调整建议"
            else:
                deviation_minutes_field.value = "0"
                adjustment_suggestion_field.border_color = None
                adjustment_suggestion_field.label = "调整建议"
        except (ValueError, TypeError):
            deviation_minutes_field.value = "输入格式错误"
        page.update()

    deviation_reason_dropdown.on_change = on_deviation_reason_change
    affects_next_checkbox.on_change = on_affects_next_change
    planned_start_field.on_change = on_time_change
    actual_start_field.on_change = on_time_change

    def handle_delete(record_id):
        def confirm_delete(e):
            success, msg = delete_record(record_id)
            show_snackbar(msg, ft.colors.GREEN if success else ft.colors.RED)
            dialog.open = False
            page.update()
            if success:
                render_page()

        dialog = ft.AlertDialog(
            title=ft.Text("确认删除"),
            content=ft.Text("确定要删除这条记录吗？此操作不可撤销。"),
            actions=[
                ft.TextButton("取消", on_click=lambda e: setattr(dialog, 'open', False) or page.update()),
                ft.TextButton("删除", on_click=confirm_delete, style=ft.ButtonStyle(color=ft.colors.RED)),
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        page.dialog = dialog
        dialog.open = True
        page.update()

    def handle_form_submit(e):
        try:
            planned = planned_start_field.value.strip()
            actual = actual_start_field.value.strip() if actual_start_field.value.strip() else None
            if planned:
                planned_dt = datetime.strptime(planned, "%Y-%m-%d %H:%M").isoformat()
            else:
                raise ValueError("请输入计划开场时间")
            actual_dt = None
            if actual:
                actual_dt = datetime.strptime(actual, "%Y-%m-%d %H:%M").isoformat()
        except ValueError as ex:
            show_snackbar(f"时间格式错误: {str(ex)}", ft.colors.RED)
            return

        reason = deviation_reason_dropdown.value or ""
        if reason == "其他" and deviation_reason_other.value.strip():
            reason = f"其他: {deviation_reason_other.value.strip()}"

        data = {
            "movie_name": movie_name_field.value.strip(),
            "hall_no": hall_no_field.value.strip(),
            "planned_start": planned_dt,
            "actual_start": actual_dt,
            "deviation_reason": reason,
            "affects_next": affects_next_checkbox.value,
            "affected_record_no": affected_record_no_field.value.strip() if affects_next_checkbox.value else "",
            "adjustment_suggestion": adjustment_suggestion_field.value.strip(),
        }

        if editing_record_id:
            success, msg, _ = update_record(editing_record_id, data)
        else:
            success, msg, _ = create_record(data)

        show_snackbar(msg, ft.colors.GREEN if success else ft.colors.RED)
        if success:
            switch_view("list")

    def build_form_view():
        nonlocal editing_record_id
        is_edit = editing_record_id is not None

        movie_name_field.value = ""
        hall_no_field.value = ""
        planned_start_field.value = ""
        actual_start_field.value = ""
        deviation_minutes_field.value = "0"
        deviation_reason_dropdown.value = None
        deviation_reason_other.value = ""
        deviation_reason_other.visible = False
        affects_next_checkbox.value = False
        affected_record_no_field.value = ""
        affected_record_no_field.disabled = True
        adjustment_suggestion_field.value = ""
        adjustment_suggestion_field.border_color = None
        adjustment_suggestion_field.label = "调整建议"
        record_no_display.value = ""

        if is_edit:
            rec = get_record_by_id(editing_record_id)
            if rec:
                record_no_display.value = f"记录编号: {rec['record_no']}"
                movie_name_field.value = rec["movie_name"]
                hall_no_field.value = rec["hall_no"]
                planned_start_field.value = format_datetime(rec["planned_start"])
                actual_start_field.value = format_datetime(rec["actual_start"]) if rec["actual_start"] else ""
                deviation_minutes_field.value = str(rec["deviation_minutes"])
                reason = rec["deviation_reason"] or ""
                if reason.startswith("其他:"):
                    deviation_reason_dropdown.value = "其他"
                    deviation_reason_other.value = reason[3:].strip()
                    deviation_reason_other.visible = True
                elif reason:
                    deviation_reason_dropdown.value = reason
                affects_next_checkbox.value = bool(rec["affects_next"])
                affected_record_no_field.disabled = not bool(rec["affects_next"])
                affected_record_no_field.value = rec["affected_record_no"] or ""
                adjustment_suggestion_field.value = rec["adjustment_suggestion"] or ""
                if rec["deviation_minutes"] <= -15:
                    adjustment_suggestion_field.border_color = ft.colors.RED
                    adjustment_suggestion_field.label = "调整建议 (提前15分钟以上，必填)"

        content = ft.Column([
            ft.Row([
                ft.Text("编辑记录" if is_edit else "新增记录", size=24, weight=ft.FontWeight.BOLD),
                ft.Container(width=30),
                record_no_display,
                ft.Container(expand=True),
                ft.OutlinedButton("返回列表", icon=ft.icons.ARROW_BACK, on_click=lambda e: switch_view("list")),
            ], alignment=ft.MainAxisAlignment.START),
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.Row([movie_name_field, hall_no_field], spacing=30),
                    ft.Row([planned_start_field, actual_start_field, deviation_minutes_field], spacing=30),
                    ft.Row([deviation_reason_dropdown, deviation_reason_other], spacing=30),
                    ft.Row([affects_next_checkbox, affected_record_no_field], spacing=30),
                    ft.Row([adjustment_suggestion_field], spacing=30),
                    ft.Divider(),
                    ft.Row([
                        ft.ElevatedButton(
                            "保存",
                            icon=ft.icons.SAVE,
                            bgcolor=ft.colors.BLUE_700,
                            color=ft.colors.WHITE,
                            on_click=handle_form_submit
                        ),
                        ft.OutlinedButton(
                            "取消",
                            on_click=lambda e: switch_view("list")
                        ),
                    ], spacing=20, alignment=ft.MainAxisAlignment.CENTER),
                ], spacing=20, scroll=ft.ScrollMode.AUTO),
                padding=20,
                bgcolor=ft.colors.GREY_50,
                border_radius=10,
                expand=True,
            )
        ], expand=True, spacing=15, scroll=ft.ScrollMode.AUTO)

        return content

    def build_hall_view():
        nonlocal selected_hall
        halls = get_all_halls()

        hall_dropdown = ft.Dropdown(
            label="选择影厅",
            width=250,
            value=selected_hall or (halls[0] if halls else None),
            options=[ft.dropdown.Option(h) for h in halls]
        )

        records_view = ft.Column([])

        def load_hall_records(e=None):
            nonlocal selected_hall
            selected_hall = hall_dropdown.value
            if not selected_hall:
                records_view.controls = [ft.Text("请选择影厅", size=16, color=ft.colors.GREY_700)]
                page.update()
                return

            records = get_records_by_hall(selected_hall)
            if not records:
                records_view.controls = [ft.Text("该影厅暂无记录", size=16, color=ft.colors.GREY_700)]
                page.update()
                return

            total_delay = sum(1 for r in records if r["deviation_minutes"] > 0)
            total_advance = sum(1 for r in records if r["deviation_minutes"] < 0)
            avg_deviation = sum(abs(r["deviation_minutes"]) for r in records) / len(records) if records else 0
            serious_count = sum(1 for r in records if abs(r["deviation_minutes"]) > 15)

            columns = [
                ft.DataColumn(ft.Text("记录编号", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("影片名称", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("计划开场", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("实际开场", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("偏差(分钟)", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("偏差原因", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("调整建议", weight=ft.FontWeight.BOLD)),
            ]

            rows = []
            for rec in records:
                deviation_color = ft.colors.RED if abs(rec["deviation_minutes"]) > 15 else (
                    ft.colors.ORANGE if rec["deviation_minutes"] != 0 else ft.colors.GREEN
                )
                rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(rec["record_no"])),
                            ft.DataCell(ft.Text(rec["movie_name"])),
                            ft.DataCell(ft.Text(format_datetime(rec["planned_start"]))),
                            ft.DataCell(ft.Text(format_datetime(rec["actual_start"]))),
                            ft.DataCell(ft.Text(str(rec["deviation_minutes"]), color=deviation_color, weight=ft.FontWeight.BOLD)),
                            ft.DataCell(ft.Text(rec["deviation_reason"] or "-")),
                            ft.DataCell(ft.Text(rec["adjustment_suggestion"] or "-")),
                        ]
                    )
                )

            records_view.controls = [
                ft.Row([
                    ft.Container(
                        content=ft.Column([
                            ft.Text("总场次", size=12, color=ft.colors.GREY_600),
                            ft.Text(str(len(records)), size=28, weight=ft.FontWeight.BOLD, color=ft.colors.BLUE_700),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=20,
                        bgcolor=ft.colors.BLUE_50,
                        border_radius=10,
                        width=150,
                    ),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("延迟场次", size=12, color=ft.colors.GREY_600),
                            ft.Text(str(total_delay), size=28, weight=ft.FontWeight.BOLD, color=ft.colors.ORANGE),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=20,
                        bgcolor=ft.colors.ORANGE_50,
                        border_radius=10,
                        width=150,
                    ),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("严重偏差", size=12, color=ft.colors.GREY_600),
                            ft.Text(str(serious_count), size=28, weight=ft.FontWeight.BOLD, color=ft.colors.RED),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=20,
                        bgcolor=ft.colors.RED_50,
                        border_radius=10,
                        width=150,
                    ),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("平均偏差(分钟)", size=12, color=ft.colors.GREY_600),
                            ft.Text(f"{avg_deviation:.1f}", size=28, weight=ft.FontWeight.BOLD, color=ft.colors.GREEN),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=20,
                        bgcolor=ft.colors.GREEN_50,
                        border_radius=10,
                        width=180,
                    ),
                ], spacing=20),
                ft.Divider(),
                ft.Container(
                    content=ft.DataTable(
                        columns=columns,
                        rows=rows,
                        horizontal_lines=ft.BorderSide(1, ft.colors.GREY_300),
                        heading_row_color=ft.colors.BLUE_50,
                        show_bottom_border=True,
                    ),
                    expand=True
                )
            ]
            page.update()

        hall_dropdown.on_change = load_hall_records
        if selected_hall or halls:
            load_hall_records()

        content = ft.Column([
            ft.Row([
                ft.Text("影厅维度查看", size=24, weight=ft.FontWeight.BOLD),
                ft.Container(width=40),
                hall_dropdown,
                ft.Container(expand=True),
                ft.OutlinedButton("返回列表", icon=ft.icons.ARROW_BACK, on_click=lambda e: switch_view("list")),
            ], alignment=ft.MainAxisAlignment.START),
            ft.Divider(),
            records_view
        ], expand=True, spacing=15, scroll=ft.ScrollMode.AUTO)

        return content

    def build_stats_view():
        reason_stats = get_reason_statistics()
        time_slot_stats = get_time_slot_statistics()
        daily_trend = get_daily_deviation_trend()

        charts_row = ft.Row([], spacing=20, scroll=ft.ScrollMode.AUTO)

        if reason_stats:
            df_reason = pd.DataFrame(reason_stats)
            fig_reason = px.bar(
                df_reason,
                x="deviation_reason",
                y="count",
                title="偏差原因分布",
                color="count",
                color_continuous_scale="Blues",
                text_auto=True
            )
            fig_reason.update_layout(
                xaxis_title="偏差原因",
                yaxis_title="出现次数",
                title_font_size=16,
                height=350,
                width=500
            )
            charts_row.controls.append(
                ft.Container(
                    content=ft.Plot(
                        data=fig_reason.data,
                        layout=fig_reason.layout,
                        expand=True
                    ),
                    padding=10,
                    bgcolor=ft.colors.WHITE,
                    border_radius=10,
                    border=ft.border.all(1, ft.colors.GREY_300),
                    width=520,
                    height=380,
                )
            )

        if time_slot_stats:
            df_time = pd.DataFrame(time_slot_stats)
            fig_time = px.bar(
                df_time,
                x="time_slot",
                y=["count", "delayed_count"],
                title="时段对比分析",
                barmode="group",
                color_discrete_sequence=["#1976D2", "#FF9800"],
                text_auto=True
            )
            fig_time.update_layout(
                xaxis_title="时段",
                yaxis_title="场次数量",
                title_font_size=16,
                legend_title="",
                height=350,
                width=500
            )
            charts_row.controls.append(
                ft.Container(
                    content=ft.Plot(
                        data=fig_time.data,
                        layout=fig_time.layout,
                        expand=True
                    ),
                    padding=10,
                    bgcolor=ft.colors.WHITE,
                    border_radius=10,
                    border=ft.border.all(1, ft.colors.GREY_300),
                    width=520,
                    height=380,
                )
            )

        trend_chart = ft.Container()
        if daily_trend:
            df_trend = pd.DataFrame(daily_trend)
            df_trend = df_trend.sort_values("date")
            fig_trend = px.line(
                df_trend,
                x="date",
                y="avg_deviation",
                title="近30天平均偏差趋势",
                markers=True,
                color_discrete_sequence=["#E53935"]
            )
            fig_trend.update_layout(
                xaxis_title="日期",
                yaxis_title="平均偏差(分钟)",
                title_font_size=16,
                height=350,
            )
            trend_chart = ft.Container(
                content=ft.Plot(
                    data=fig_trend.data,
                    layout=fig_trend.layout,
                    expand=True
                ),
                padding=10,
                bgcolor=ft.colors.WHITE,
                border_radius=10,
                border=ft.border.all(1, ft.colors.GREY_300),
                height=380,
            )

        summary_cards = ft.Row([], spacing=20)
        all_records = get_all_records()
        if all_records:
            total = len(all_records)
            delayed = sum(1 for r in all_records if r["deviation_minutes"] > 0)
            serious = sum(1 for r in all_records if abs(r["deviation_minutes"]) > 15)
            avg_dev = sum(abs(r["deviation_minutes"]) for r in all_records) / total

            summary_cards.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.Text("总记录数", size=12, color=ft.colors.GREY_600),
                        ft.Text(str(total), size=28, weight=ft.FontWeight.BOLD, color=ft.colors.BLUE_700),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=20,
                    bgcolor=ft.colors.BLUE_50,
                    border_radius=10,
                    width=160,
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Text("延迟场次", size=12, color=ft.colors.GREY_600),
                        ft.Text(f"{delayed} ({delayed/total*100:.1f}%)", size=28, weight=ft.FontWeight.BOLD, color=ft.colors.ORANGE),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=20,
                    bgcolor=ft.colors.ORANGE_50,
                    border_radius=10,
                    width=180,
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Text("严重偏差", size=12, color=ft.colors.GREY_600),
                        ft.Text(f"{serious} ({serious/total*100:.1f}%)", size=28, weight=ft.FontWeight.BOLD, color=ft.colors.RED),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=20,
                    bgcolor=ft.colors.RED_50,
                    border_radius=10,
                    width=180,
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Text("平均偏差(分钟)", size=12, color=ft.colors.GREY_600),
                        ft.Text(f"{avg_dev:.1f}", size=28, weight=ft.FontWeight.BOLD, color=ft.colors.GREEN),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=20,
                    bgcolor=ft.colors.GREEN_50,
                    border_radius=10,
                    width=180,
                ),
            ]

        reason_table = ft.Container()
        if reason_stats:
            reason_columns = [
                ft.DataColumn(ft.Text("偏差原因", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("次数", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("平均偏差(分钟)", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("严重偏差次数", weight=ft.FontWeight.BOLD)),
            ]
            reason_rows = [
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(r["deviation_reason"])),
                        ft.DataCell(ft.Text(str(r["count"]))),
                        ft.DataCell(ft.Text(f"{r['avg_deviation']:.1f}")),
                        ft.DataCell(ft.Text(str(r["serious_count"]))),
                    ]
                ) for r in reason_stats
            ]
            reason_table = ft.Container(
                content=ft.DataTable(
                    columns=reason_columns,
                    rows=reason_rows,
                    heading_row_color=ft.colors.BLUE_50,
                    show_bottom_border=True,
                ),
                bgcolor=ft.colors.WHITE,
                border_radius=10,
                border=ft.border.all(1, ft.colors.GREY_300),
                padding=10,
            )

        time_table = ft.Container()
        if time_slot_stats:
            time_columns = [
                ft.DataColumn(ft.Text("时段", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("总场次", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("延迟场次", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("平均偏差(分钟)", weight=ft.FontWeight.BOLD)),
            ]
            time_rows = [
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(t["time_slot"])),
                        ft.DataCell(ft.Text(str(t["count"]))),
                        ft.DataCell(ft.Text(str(t["delayed_count"]))),
                        ft.DataCell(ft.Text(f"{t['avg_deviation']:.1f}")),
                    ]
                ) for t in time_slot_stats
            ]
            time_table = ft.Container(
                content=ft.DataTable(
                    columns=time_columns,
                    rows=time_rows,
                    heading_row_color=ft.colors.BLUE_50,
                    show_bottom_border=True,
                ),
                bgcolor=ft.colors.WHITE,
                border_radius=10,
                border=ft.border.all(1, ft.colors.GREY_300),
                padding=10,
            )

        content = ft.Column([
            ft.Row([
                ft.Text("统计分析", size=24, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.OutlinedButton("返回列表", icon=ft.icons.ARROW_BACK, on_click=lambda e: switch_view("list")),
            ], alignment=ft.MainAxisAlignment.START),
            ft.Divider(),
            summary_cards,
            ft.Divider(),
            ft.Text("图表展示", size=18, weight=ft.FontWeight.BOLD),
            ft.Divider(height=5),
            charts_row,
            ft.Divider(),
            trend_chart,
            ft.Divider(),
            ft.Text("详细数据", size=18, weight=ft.FontWeight.BOLD),
            ft.Divider(height=5),
            ft.Row([reason_table, time_table], spacing=20, scroll=ft.ScrollMode.AUTO),
        ], expand=True, spacing=15, scroll=ft.ScrollMode.AUTO)

        return content

    def build_alerts_view():
        alerts = get_review_alerts()

        columns = [
            ft.DataColumn(ft.Text("记录编号", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("影片名称", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("影厅", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("计划开场", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("偏差(分钟)", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("偏差原因", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("操作", weight=ft.FontWeight.BOLD)),
        ]

        rows = []
        for rec in alerts:
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(rec["record_no"])),
                        ft.DataCell(ft.Text(rec["movie_name"])),
                        ft.DataCell(ft.Text(rec["hall_no"])),
                        ft.DataCell(ft.Text(format_datetime(rec["planned_start"]))),
                        ft.DataCell(ft.Text(str(rec["deviation_minutes"]), color=ft.colors.RED, weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(rec["deviation_reason"] or "-")),
                        ft.DataCell(
                            ft.ElevatedButton(
                                "查看/处理",
                                icon=ft.icons.VISIBILITY,
                                on_click=lambda e, rid=rec["id"]: switch_view("form", record_id=rid)
                            )
                        ),
                    ]
                )
            )

        content = ft.Column([
            ft.Row([
                ft.Icon(ft.icons.WARNING_AMBER, color=ft.colors.ORANGE, size=30),
                ft.Text("设备/流程复查提醒", size=24, weight=ft.FontWeight.BOLD, color=ft.colors.ORANGE_700),
                ft.Container(expand=True),
                ft.OutlinedButton("返回列表", icon=ft.icons.ARROW_BACK, on_click=lambda e: switch_view("list")),
            ], alignment=ft.MainAxisAlignment.START),
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.Text(
                        "以下影厅连续两天出现开场延迟，建议进行设备或流程复查：",
                        size=14,
                        color=ft.colors.GREY_700
                    ),
                ], spacing=5),
                padding=15,
                bgcolor=ft.colors.ORANGE_50,
                border_radius=10,
                border=ft.border.all(2, ft.colors.ORANGE_200),
            ),
            ft.Divider(),
            ft.Container(
                content=ft.DataTable(
                    columns=columns,
                    rows=rows,
                    horizontal_lines=ft.BorderSide(1, ft.colors.GREY_300),
                    heading_row_color=ft.colors.ORANGE_50,
                    show_bottom_border=True,
                ) if rows else ft.Text("暂无复查提醒", size=16, color=ft.colors.GREY_700),
                expand=True
            )
        ], expand=True, spacing=15, scroll=ft.ScrollMode.AUTO)

        return content

    def build_closure_management_view():
        nonlocal closure_editing_record_id
        halls = get_all_halls()
        handling_statuses = ["全部", "待处理", "处理中", "已完成"]
        
        filter_start_date = ft.TextField(label="开始日期 (YYYY-MM-DD)", width=200)
        filter_end_date = ft.TextField(label="结束日期 (YYYY-MM-DD)", width=200)
        filter_hall = ft.Dropdown(
            label="选择影厅",
            width=180,
            value="全部",
            options=[ft.dropdown.Option("全部")] + [ft.dropdown.Option(h) for h in halls]
        )
        filter_movie = ft.TextField(label="影片名称", width=200)
        filter_status = ft.Dropdown(
            label="处理状态",
            width=150,
            value="全部",
            options=[ft.dropdown.Option(s) for s in handling_statuses]
        )
        
        records_view = ft.Column([])
        
        def get_status_color(status):
            if status == "已完成":
                return ft.colors.GREEN
            elif status == "处理中":
                return ft.colors.ORANGE
            else:
                return ft.colors.RED
        
        def load_filtered_records(e=None):
            start_date = filter_start_date.value.strip() if filter_start_date.value.strip() else None
            end_date = filter_end_date.value.strip() if filter_end_date.value.strip() else None
            hall = filter_hall.value if filter_hall.value and filter_hall.value != "全部" else None
            movie = filter_movie.value.strip() if filter_movie.value.strip() else None
            status = filter_status.value if filter_status.value and filter_status.value != "全部" else None
            
            records = get_records_with_filters(start_date, end_date, hall, movie, status)
            
            if not records:
                records_view.controls = [ft.Text("暂无符合条件的记录", size=16, color=ft.colors.GREY_700)]
                page.update()
                return
            
            columns = [
                ft.DataColumn(ft.Text("操作", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("记录编号", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("影片名称", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("影厅", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("计划开场", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("偏差(分钟)", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("偏差原因", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("处理状态", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("责任人", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("处理完成时间", weight=ft.FontWeight.BOLD)),
            ]
            
            rows = []
            for rec in records:
                deviation_color = ft.colors.RED if abs(rec["deviation_minutes"]) > 15 else (
                    ft.colors.ORANGE if rec["deviation_minutes"] != 0 else ft.colors.GREEN
                )
                status = rec.get("handling_status") or "待处理"
                status_color = get_status_color(status)
                
                rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(
                                ft.Row([
                                    ft.IconButton(
                                        ft.icons.EDIT,
                                        icon_size=20,
                                        tooltip="处理记录",
                                        on_click=lambda e, rid=rec["id"]: open_closure_edit_dialog(rid)
                                    ),
                                ])
                            ),
                            ft.DataCell(ft.Text(rec["record_no"])),
                            ft.DataCell(ft.Text(rec["movie_name"])),
                            ft.DataCell(ft.Text(rec["hall_no"])),
                            ft.DataCell(ft.Text(format_datetime(rec["planned_start"]))),
                            ft.DataCell(ft.Text(str(rec["deviation_minutes"]), color=deviation_color, weight=ft.FontWeight.BOLD)),
                            ft.DataCell(ft.Text(rec["deviation_reason"] or "-")),
                            ft.DataCell(
                                ft.Container(
                                    content=ft.Text(status, color=ft.colors.WHITE, size=12, weight=ft.FontWeight.BOLD),
                                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                    bgcolor=status_color,
                                    border_radius=4,
                                )
                            ),
                            ft.DataCell(ft.Text(rec.get("responsible_person") or "-")),
                            ft.DataCell(ft.Text(format_datetime(rec.get("completion_time")) or "-")),
                        ]
                    )
                )
            
            records_view.controls = [
                ft.Container(
                    content=ft.DataTable(
                        columns=columns,
                        rows=rows,
                        horizontal_lines=ft.BorderSide(1, ft.colors.GREY_300),
                        vertical_lines=ft.BorderSide(1, ft.colors.GREY_300),
                        heading_row_color=ft.colors.BLUE_50,
                        show_bottom_border=True,
                        sort_column_index=4,
                        sort_ascending=False,
                    ),
                    expand=True
                )
            ]
            page.update()
        
        def open_closure_edit_dialog(record_id):
            rec = get_record_by_id(record_id)
            if not rec:
                return
            
            status = rec.get("handling_status") or "待处理"
            person = rec.get("responsible_person") or ""
            completion = rec.get("completion_time") or ""
            conclusion = rec.get("review_conclusion") or ""
            
            status_dropdown = ft.Dropdown(
                label="处理状态",
                width=300,
                value=status,
                options=[ft.dropdown.Option(s) for s in ["待处理", "处理中", "已完成"]]
            )
            person_field = ft.TextField(label="责任人", width=300, value=person)
            completion_field = ft.TextField(
                label="处理完成时间 (YYYY-MM-DD HH:MM)",
                width=300,
                value=format_datetime(completion) if completion else "",
                disabled=(status != "已完成")
            )
            conclusion_field = ft.TextField(
                label="复盘结论",
                width=600,
                multiline=True,
                min_lines=4,
                value=conclusion
            )
            
            def on_status_change(e):
                if status_dropdown.value == "已完成":
                    completion_field.disabled = False
                    if not completion_field.value.strip():
                        completion_field.value = datetime.now().strftime("%Y-%m-%d %H:%M")
                else:
                    completion_field.disabled = True
                    completion_field.value = ""
                page.update()
            
            status_dropdown.on_change = on_status_change
            
            def handle_save(e):
                new_status = status_dropdown.value or "待处理"
                new_person = person_field.value.strip()
                new_completion = completion_field.value.strip()
                new_conclusion = conclusion_field.value.strip()
                
                if new_status == "已完成" and not new_conclusion:
                    show_snackbar("状态为已完成时，复盘结论不能为空", ft.colors.RED)
                    return
                
                if new_status != "已完成":
                    new_completion = ""
                    completion_dt = None
                else:
                    try:
                        if new_completion:
                            completion_dt = datetime.strptime(new_completion, "%Y-%m-%d %H:%M").isoformat()
                        else:
                            completion_dt = datetime.now().isoformat()
                    except ValueError:
                        show_snackbar("处理完成时间格式错误", ft.colors.RED)
                        return
                
                success, msg = update_handling_info(
                    record_id, new_status, new_person, completion_dt, new_conclusion
                )
                show_snackbar(msg, ft.colors.GREEN if success else ft.colors.RED)
                if success:
                    dialog.open = False
                    page.update()
                    load_filtered_records()
            
            dialog = ft.AlertDialog(
                title=ft.Row([
                    ft.Text("偏差处理闭环管理", size=20, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    ft.Text(f"记录编号: {rec['record_no']}", size=14, color=ft.colors.GREY_600),
                ]),
                content=ft.Column([
                    ft.Row([
                        ft.Container(
                            content=ft.Column([
                                ft.Text("影片名称", size=12, color=ft.colors.GREY_600),
                                ft.Text(rec["movie_name"], size=16, weight=ft.FontWeight.BOLD),
                            ]),
                            padding=10,
                            bgcolor=ft.colors.BLUE_50,
                            border_radius=8,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Column([
                                ft.Text("影厅", size=12, color=ft.colors.GREY_600),
                                ft.Text(rec["hall_no"], size=16, weight=ft.FontWeight.BOLD),
                            ]),
                            padding=10,
                            bgcolor=ft.colors.BLUE_50,
                            border_radius=8,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Column([
                                ft.Text("偏差(分钟)", size=12, color=ft.colors.GREY_600),
                                ft.Text(str(rec["deviation_minutes"]), size=16, weight=ft.FontWeight.BOLD,
                                       color=ft.colors.RED if abs(rec["deviation_minutes"]) > 15 else ft.colors.ORANGE),
                            ]),
                            padding=10,
                            bgcolor=ft.colors.BLUE_50,
                            border_radius=8,
                            expand=True,
                        ),
                    ], spacing=10),
                    ft.Divider(),
                    ft.Text("偏差原因", size=12, color=ft.colors.GREY_600),
                    ft.Text(rec["deviation_reason"] or "未填写", size=14),
                    ft.Divider(),
                    ft.Row([status_dropdown, person_field], spacing=20),
                    ft.Row([completion_field], spacing=20),
                    ft.Row([conclusion_field], spacing=20),
                ], spacing=15, scroll=ft.ScrollMode.AUTO),
                actions=[
                    ft.TextButton("取消", on_click=lambda e: setattr(dialog, 'open', False) or page.update()),
                    ft.ElevatedButton("保存", on_click=handle_save, bgcolor=ft.colors.BLUE_700, color=ft.colors.WHITE),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.dialog = dialog
            dialog.open = True
            page.update()
        
        def reset_filters(e):
            filter_start_date.value = ""
            filter_end_date.value = ""
            filter_hall.value = "全部"
            filter_movie.value = ""
            filter_status.value = "全部"
            load_filtered_records()
        
        search_btn = ft.ElevatedButton(
            "查询",
            icon=ft.icons.SEARCH,
            bgcolor=ft.colors.BLUE_700,
            color=ft.colors.WHITE,
            on_click=load_filtered_records
        )
        reset_btn = ft.OutlinedButton(
            "重置",
            icon=ft.icons.REFRESH,
            on_click=reset_filters
        )
        
        load_filtered_records()
        
        if closure_editing_record_id:
            page.update()
            open_closure_edit_dialog(closure_editing_record_id)
            closure_editing_record_id = None
        
        content = ft.Column([
            ft.Row([
                ft.Icon(ft.icons.LOOP, color=ft.colors.BLUE_700, size=30),
                ft.Text("偏差处理闭环管理", size=24, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.OutlinedButton("返回列表", icon=ft.icons.ARROW_BACK, on_click=lambda e: switch_view("list")),
            ], alignment=ft.MainAxisAlignment.START),
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        filter_start_date,
                        filter_end_date,
                        filter_hall,
                        filter_movie,
                        filter_status,
                    ], spacing=15, wrap=True),
                    ft.Row([search_btn, reset_btn], spacing=15),
                ], spacing=10),
                padding=20,
                bgcolor=ft.colors.GREY_50,
                border_radius=10,
            ),
            ft.Divider(),
            records_view,
        ], expand=True, spacing=15, scroll=ft.ScrollMode.AUTO)
        
        return content

    def build_closure_stats_view():
        handling_stats = get_handling_statistics()
        hall_completion = get_hall_completion_rate()
        reason_handling = get_reason_handling_time()
        incomplete_records = get_incomplete_records()
        handling_trend = get_handling_trend()
        
        summary_cards = ft.Row([
            ft.Container(
                content=ft.Column([
                    ft.Text("总记录数", size=12, color=ft.colors.GREY_600),
                    ft.Text(str(handling_stats["total"]), size=28, weight=ft.FontWeight.BOLD, color=ft.colors.BLUE_700),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
                bgcolor=ft.colors.BLUE_50,
                border_radius=10,
                width=150,
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("待处理", size=12, color=ft.colors.GREY_600),
                    ft.Text(str(handling_stats["pending"]), size=28, weight=ft.FontWeight.BOLD, color=ft.colors.RED),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
                bgcolor=ft.colors.RED_50,
                border_radius=10,
                width=150,
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("处理中", size=12, color=ft.colors.GREY_600),
                    ft.Text(str(handling_stats["processing"]), size=28, weight=ft.FontWeight.BOLD, color=ft.colors.ORANGE),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
                bgcolor=ft.colors.ORANGE_50,
                border_radius=10,
                width=150,
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("已完成", size=12, color=ft.colors.GREY_600),
                    ft.Text(str(handling_stats["completed"]), size=28, weight=ft.FontWeight.BOLD, color=ft.colors.GREEN),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
                bgcolor=ft.colors.GREEN_50,
                border_radius=10,
                width=150,
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("完成率", size=12, color=ft.colors.GREY_600),
                    ft.Text(f"{handling_stats['completion_rate']:.1f}%", size=28, weight=ft.FontWeight.BOLD, color=ft.colors.PURPLE),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
                bgcolor=ft.colors.PURPLE_50,
                border_radius=10,
                width=150,
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("平均处理耗时(分钟)", size=12, color=ft.colors.GREY_600),
                    ft.Text(f"{handling_stats['avg_handling_time']:.0f}", size=28, weight=ft.FontWeight.BOLD, color=ft.colors.TEAL),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
                bgcolor=ft.colors.TEAL_50,
                border_radius=10,
                width=180,
            ),
        ], spacing=15, scroll=ft.ScrollMode.AUTO)
        
        hall_chart = ft.Container()
        if hall_completion:
            df_hall = pd.DataFrame(hall_completion)
            fig_hall = px.bar(
                df_hall,
                x="hall_no",
                y="completion_rate",
                title="各影厅偏差处理完成率",
                text_auto='.2f',
                color="completion_rate",
                color_continuous_scale="Greens",
            )
            fig_hall.update_layout(
                xaxis_title="影厅",
                yaxis_title="完成率(%)",
                yaxis_range=[0, 100],
                title_font_size=16,
                height=350,
                width=500,
            )
            hall_chart = ft.Container(
                content=ft.Plot(
                    data=fig_hall.data,
                    layout=fig_hall.layout,
                    expand=True
                ),
                padding=10,
                bgcolor=ft.colors.WHITE,
                border_radius=10,
                border=ft.border.all(1, ft.colors.GREY_300),
                width=520,
                height=380,
            )
        
        reason_chart = ft.Container()
        if reason_handling:
            df_reason = pd.DataFrame(reason_handling)
            df_reason = df_reason[df_reason["avg_handling_minutes"].notna()]
            if not df_reason.empty:
                fig_reason = px.bar(
                    df_reason,
                    x="deviation_reason",
                    y="avg_handling_minutes",
                    title="不同原因的处理耗时对比(分钟)",
                    text_auto='.0f',
                    color="avg_handling_minutes",
                    color_continuous_scale="Oranges",
                )
                fig_reason.update_layout(
                    xaxis_title="偏差原因",
                    yaxis_title="平均处理耗时(分钟)",
                    title_font_size=16,
                    height=350,
                    width=500,
                )
                reason_chart = ft.Container(
                    content=ft.Plot(
                        data=fig_reason.data,
                        layout=fig_reason.layout,
                        expand=True
                    ),
                    padding=10,
                    bgcolor=ft.colors.WHITE,
                    border_radius=10,
                    border=ft.border.all(1, ft.colors.GREY_300),
                    width=520,
                    height=380,
                )
        
        trend_chart = ft.Container()
        if handling_trend:
            df_trend = pd.DataFrame(handling_trend)
            df_trend = df_trend.sort_values("date")
            fig_trend = px.line(
                df_trend,
                x="date",
                y=["completed_count", "processing_count", "pending_count"],
                title="处理趋势(近30天)",
                markers=True,
                color_discrete_sequence=["#4CAF50", "#FF9800", "#F44336"],
            )
            fig_trend.update_layout(
                xaxis_title="日期",
                yaxis_title="记录数",
                title_font_size=16,
                legend_title="状态",
                height=350,
            )
            trend_chart = ft.Container(
                content=ft.Plot(
                    data=fig_trend.data,
                    layout=fig_trend.layout,
                    expand=True
                ),
                padding=10,
                bgcolor=ft.colors.WHITE,
                border_radius=10,
                border=ft.border.all(1, ft.colors.GREY_300),
                height=380,
            )
        
        incomplete_table = ft.Container()
        if incomplete_records:
            inc_columns = [
                ft.DataColumn(ft.Text("记录编号", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("影片名称", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("影厅", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("计划开场", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("偏差(分钟)", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("偏差原因", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("处理状态", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("责任人", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("操作", weight=ft.FontWeight.BOLD)),
            ]
            
            def get_status_color(status):
                if status == "处理中":
                    return ft.colors.ORANGE
                else:
                    return ft.colors.RED
            
            inc_rows = []
            for rec in incomplete_records:
                status = rec.get("handling_status") or "待处理"
                status_color = get_status_color(status)
                inc_rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(rec["record_no"])),
                            ft.DataCell(ft.Text(rec["movie_name"])),
                            ft.DataCell(ft.Text(rec["hall_no"])),
                            ft.DataCell(ft.Text(format_datetime(rec["planned_start"]))),
                            ft.DataCell(ft.Text(str(rec["deviation_minutes"]), color=ft.colors.RED, weight=ft.FontWeight.BOLD)),
                            ft.DataCell(ft.Text(rec["deviation_reason"] or "-")),
                            ft.DataCell(
                                ft.Container(
                                    content=ft.Text(status, color=ft.colors.WHITE, size=12, weight=ft.FontWeight.BOLD),
                                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                    bgcolor=status_color,
                                    border_radius=4,
                                )
                            ),
                            ft.DataCell(ft.Text(rec.get("responsible_person") or "-")),
                            ft.DataCell(
                                ft.ElevatedButton(
                                    "立即处理",
                                    icon=ft.icons.PLAY_ARROW,
                                    on_click=lambda e, rid=rec["id"]: switch_view("closure_management", closure_edit_id=rid)
                                )
                            ),
                        ]
                    )
                )
            
            incomplete_table = ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.icons.WARNING_AMBER, color=ft.colors.RED, size=20),
                        ft.Text(f"未完成记录列表 ({len(incomplete_records)} 条)", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.RED),
                    ]),
                    ft.Container(
                        content=ft.DataTable(
                            columns=inc_columns,
                            rows=inc_rows,
                            horizontal_lines=ft.BorderSide(1, ft.colors.GREY_300),
                            heading_row_color=ft.colors.RED_50,
                            show_bottom_border=True,
                        ),
                        expand=True,
                    ),
                ], spacing=10),
                padding=15,
                bgcolor=ft.colors.WHITE,
                border_radius=10,
                border=ft.border.all(2, ft.colors.RED_200),
            )
        
        content = ft.Column([
            ft.Row([
                ft.Icon(ft.icons.BAR_CHART, color=ft.colors.PURPLE_700, size=30),
                ft.Text("闭环统计分析", size=24, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.OutlinedButton("返回列表", icon=ft.icons.ARROW_BACK, on_click=lambda e: switch_view("list")),
            ], alignment=ft.MainAxisAlignment.START),
            ft.Divider(),
            summary_cards,
            ft.Divider(),
            ft.Text("图表展示", size=18, weight=ft.FontWeight.BOLD),
            ft.Divider(height=5),
            ft.Row([hall_chart, reason_chart], spacing=20, scroll=ft.ScrollMode.AUTO),
            ft.Divider(),
            trend_chart,
            ft.Divider(),
            incomplete_table,
        ], expand=True, spacing=15, scroll=ft.ScrollMode.AUTO)
        
        return content

    def render_page():
        page.clean()
        page.appbar = build_app_bar()

        if current_view == "list":
            page.add(build_record_list_view())
        elif current_view == "form":
            page.add(build_form_view())
        elif current_view == "hall_view":
            page.add(build_hall_view())
        elif current_view == "stats":
            page.add(build_stats_view())
        elif current_view == "alerts":
            page.add(build_alerts_view())
        elif current_view == "closure_management":
            page.add(build_closure_management_view())
        elif current_view == "closure_stats":
            page.add(build_closure_stats_view())

        page.update()

    render_page()


if __name__ == "__main__":
    ft.app(target=main)
