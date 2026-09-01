from __future__ import annotations

import argparse
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from app_core import AutomationEngine, CaseDefinition, CaseLoader, CaseResult


STATUS_TEXT = {
    "waiting": "等待执行",
    "running": "执行中",
    "passed": "通过",
    "failed": "失败",
    "stopped": "已停止",
    "skipped": "已跳过",
}


def connection_display(status: dict[str, bool]) -> tuple[str, str]:
    if status.get("game"):
        return "● 游戏已连接：九霄仙府", "Connection.Green.TLabel"
    if status.get("wechat_main") or status.get("wechat_panel"):
        return "● 已找到微信，游戏未打开", "Connection.Yellow.TLabel"
    return "● 未找到微信", "Connection.Red.TLabel"


class AutomationApp:
    def __init__(self, root: tk.Tk, connect_on_start: bool = True):
        self.root = root
        self.root.title("九霄仙府自动化测试")
        self.root.geometry("980x700")
        self.root.minsize(820, 560)

        self.events: queue.Queue[tuple] = queue.Queue()
        self.loader = CaseLoader()
        self.engine = AutomationEngine(log=self._thread_log)
        self.cases: list[CaseDefinition] = []
        self.case_by_id: dict[str, CaseDefinition] = {}
        self.selected: dict[str, bool] = {}
        self.running = False
        self.status_polling = False

        self.connection_text = tk.StringVar(value="正在初始化……")
        self.summary_text = tk.StringVar(value="请选择用例后开始执行")
        self._build_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_events)
        self.root.after(2000, self._scheduled_connection_poll)
        if connect_on_start:
            self._reload_async(initial=True)

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 10))
        style.configure(
            "Connection.Neutral.TLabel",
            font=("Microsoft YaHei UI", 10, "bold"),
            foreground="#666666",
        )
        style.configure(
            "Connection.Red.TLabel",
            font=("Microsoft YaHei UI", 10, "bold"),
            foreground="#c42b1c",
        )
        style.configure(
            "Connection.Yellow.TLabel",
            font=("Microsoft YaHei UI", 10, "bold"),
            foreground="#c27c0e",
        )
        style.configure(
            "Connection.Green.TLabel",
            font=("Microsoft YaHei UI", 10, "bold"),
            foreground="#107c10",
        )
        style.configure("Treeview", rowheight=30, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="九霄仙府自动化测试", style="Title.TLabel").pack(
            side="left"
        )
        self.connection_label = ttk.Label(
            header,
            textvariable=self.connection_text,
            style="Connection.Neutral.TLabel",
        )
        self.connection_label.pack(side="right", padx=(12, 0))

        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 8))
        self.select_all_button = ttk.Button(
            toolbar, text="全选", command=lambda: self._set_all_selected(True)
        )
        self.select_all_button.pack(side="left")
        self.clear_button = ttk.Button(
            toolbar, text="清空", command=lambda: self._set_all_selected(False)
        )
        self.clear_button.pack(side="left", padx=(6, 0))
        self.refresh_button = ttk.Button(
            toolbar, text="刷新用例", command=self._reload_async
        )
        self.refresh_button.pack(side="left", padx=(6, 0))
        self.detect_button = ttk.Button(
            toolbar, text="检测窗口", command=self._poll_connection_async
        )
        self.detect_button.pack(side="left", padx=(6, 0))
        self.stop_button = ttk.Button(
            toolbar, text="停止", command=self._stop, state="disabled"
        )
        self.stop_button.pack(side="right")
        self.start_button = ttk.Button(
            toolbar, text="开始执行", command=self._start
        )
        self.start_button.pack(side="right", padx=(0, 6))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("selected", "order", "group", "name", "status", "description")
        self.tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "selected": "选择",
            "order": "顺序",
            "group": "分组",
            "name": "用例名称",
            "status": "状态",
            "description": "说明",
        }
        widths = {
            "selected": 55,
            "order": 55,
            "group": 90,
            "name": 190,
            "status": 85,
            "description": 390,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(
                column,
                width=widths[column],
                minwidth=45,
                anchor="center" if column != "description" else "w",
                stretch=column in {"name", "description"},
            )
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)
        self.tree.tag_configure("running", background="#fff4ce")
        self.tree.tag_configure("passed", background="#dff6dd")
        self.tree.tag_configure("failed", background="#fde7e9")
        self.tree.tag_configure("stopped", background="#eeeeee")
        self.tree.tag_configure("disabled", foreground="#888888")

        ttk.Label(outer, textvariable=self.summary_text).pack(
            fill="x", pady=(8, 4)
        )
        log_frame = ttk.LabelFrame(outer, text="执行日志", padding=6)
        log_frame.pack(fill="both", expand=False)
        self.log_text = tk.Text(
            log_frame,
            height=9,
            wrap="word",
            state="disabled",
            font=("Microsoft YaHei UI", 9),
        )
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _thread_log(self, message: str) -> None:
        self.events.put(("log", message))

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _reload_async(self, initial: bool = False) -> None:
        if self.running:
            messagebox.showinfo("提示", "任务执行期间不能刷新用例。")
            return
        self.refresh_button.configure(state="disabled")
        self.summary_text.set("正在刷新外部用例和 Maa 资源……")

        def worker() -> None:
            try:
                cases = self.loader.load()
                self.engine.reload_resources()
                self.events.put(("reload_ok", cases, initial))
            except Exception as exc:
                self.events.put(("reload_error", str(exc)))

        threading.Thread(target=worker, daemon=True, name="case-reloader").start()

    def _apply_cases(self, cases: list[CaseDefinition], initial: bool) -> None:
        old_selected = dict(self.selected)
        self.cases = cases
        self.case_by_id = {case.id: case for case in cases}
        self.selected = {
            case.id: old_selected.get(case.id, case.default_checked) and case.enabled
            for case in cases
        }
        for row in self.tree.get_children():
            self.tree.delete(row)
        for case in cases:
            self.tree.insert(
                "",
                "end",
                iid=case.id,
                values=(
                    "☑" if self.selected[case.id] else "☐",
                    case.order,
                    case.group,
                    case.name,
                    "等待执行" if case.enabled else "已禁用",
                    case.description,
                ),
                tags=("disabled",) if not case.enabled else (),
            )
        self.refresh_button.configure(state="normal")
        self.summary_text.set(f"已加载 {len(cases)} 个外部用例")
        self._append_log(f"用例刷新完成，共 {len(cases)} 个")
        self._poll_connection_async()
        if initial and not cases:
            messagebox.showwarning("没有用例", "cases 目录中没有可用的 JSON 用例。")

    def _set_all_selected(self, selected: bool) -> None:
        if self.running:
            return
        for case in self.cases:
            if case.enabled:
                self.selected[case.id] = selected
                self._set_row_value(case.id, "selected", "☑" if selected else "☐")

    def _toggle_case(self, case_id: str) -> None:
        if self.running:
            return
        case = self.case_by_id.get(case_id)
        if case is None or not case.enabled:
            return
        self.selected[case_id] = not self.selected.get(case_id, False)
        self._set_row_value(
            case_id, "selected", "☑" if self.selected[case_id] else "☐"
        )

    def _on_tree_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        case_id = self.tree.identify_row(event.y)
        if case_id:
            self.root.after_idle(lambda: self._toggle_case(case_id))

    def _on_tree_space(self, _event) -> str:
        selection = self.tree.selection()
        if selection:
            self._toggle_case(selection[0])
        return "break"

    def _set_row_value(self, case_id: str, column: str, value: str) -> None:
        if self.tree.exists(case_id):
            self.tree.set(case_id, column, value)

    def _set_case_status(self, case_id: str, status: str) -> None:
        self._set_row_value(case_id, "status", STATUS_TEXT.get(status, status))
        self.tree.item(case_id, tags=(status,) if status in STATUS_TEXT else ())
        self.tree.see(case_id)

    def _start(self) -> None:
        if self.running:
            return
        selected_cases = [case for case in self.cases if self.selected.get(case.id)]
        if not selected_cases:
            messagebox.showinfo("没有选择用例", "请至少勾选一个自动化用例。")
            return

        self.running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.refresh_button.configure(state="disabled")
        self.select_all_button.configure(state="disabled")
        self.clear_button.configure(state="disabled")
        for case in selected_cases:
            self._set_case_status(case.id, "waiting")
        self.summary_text.set(f"准备按顺序执行 {len(selected_cases)} 个用例……")
        self._append_log("=" * 18 + " 开始执行 " + "=" * 18)

        def on_start(case: CaseDefinition) -> None:
            self.events.put(("case_start", case))

        def on_end(case: CaseDefinition, result: CaseResult) -> None:
            self.events.put(("case_end", case, result))

        def worker() -> None:
            results = self.engine.execute_cases(selected_cases, on_start, on_end)
            self.events.put(("run_done", results, len(selected_cases)))

        threading.Thread(target=worker, daemon=True, name="case-runner").start()

    def _stop(self) -> None:
        if not self.running:
            return
        self.stop_button.configure(state="disabled")
        self.summary_text.set("正在停止当前任务……")
        self._append_log("用户请求停止执行")
        threading.Thread(target=self.engine.request_stop, daemon=True).start()

    def _poll_connection_async(self) -> None:
        if self.status_polling or self.running:
            return
        self.status_polling = True

        def worker() -> None:
            try:
                self.events.put(("connection", self.engine.connection_status()))
            except Exception as exc:
                self.events.put(("connection_error", str(exc)))

        threading.Thread(target=worker, daemon=True, name="window-detector").start()

    def _scheduled_connection_poll(self) -> None:
        self._poll_connection_async()
        self.root.after(2000, self._scheduled_connection_poll)

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_log(event[1])
                elif kind == "reload_ok":
                    self._apply_cases(event[1], event[2])
                elif kind == "reload_error":
                    self.refresh_button.configure(state="normal")
                    self.summary_text.set("刷新用例失败")
                    self._append_log(f"刷新失败：{event[1]}")
                    messagebox.showerror("刷新失败", event[1])
                elif kind == "connection":
                    self.status_polling = False
                    text, style = connection_display(event[1])
                    self.connection_text.set(text)
                    self.connection_label.configure(style=style)
                elif kind == "connection_error":
                    self.status_polling = False
                    self.connection_text.set("● 窗口检测失败")
                    self.connection_label.configure(style="Connection.Red.TLabel")
                    self._append_log(f"窗口检测失败：{event[1]}")
                elif kind == "case_start":
                    case = event[1]
                    self._set_case_status(case.id, "running")
                    self.summary_text.set(f"正在执行：{case.name}")
                    self._append_log(f"开始：{case.name}")
                elif kind == "case_end":
                    case, result = event[1], event[2]
                    self._set_case_status(case.id, result.status)
                    self._append_log(
                        f"{STATUS_TEXT.get(result.status, result.status)}：{case.name}；"
                        f"{result.message}；耗时 {result.elapsed:.2f}s"
                    )
                elif kind == "run_done":
                    results, selected_count = event[1], event[2]
                    self.running = False
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.refresh_button.configure(state="normal")
                    self.select_all_button.configure(state="normal")
                    self.clear_button.configure(state="normal")
                    passed = sum(result.status == "passed" for _case, result in results)
                    failed = sum(result.status == "failed" for _case, result in results)
                    stopped = sum(result.status == "stopped" for _case, result in results)
                    self.summary_text.set(
                        f"执行结束：通过 {passed}，失败 {failed}，停止 {stopped}，"
                        f"未执行 {selected_count - len(results)}"
                    )
                    self._append_log("执行结束")
                    self._poll_connection_async()
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _on_close(self) -> None:
        if self.running:
            self.engine.request_stop()
        self.root.destroy()


def smoke_test() -> int:
    cases = CaseLoader().load()
    root = tk.Tk()
    root.withdraw()
    app = AutomationApp(root, connect_on_start=False)
    app._apply_cases(cases, initial=False)
    root.update_idletasks()
    root.destroy()
    print(f"GUI smoke test passed: {len(cases)} cases")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="九霄仙府自动化测试前台")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if args.smoke_test:
        return smoke_test()
    root = tk.Tk()
    AutomationApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
