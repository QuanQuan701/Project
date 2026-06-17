import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import csv
import re

from app_data import (
    APP_VERSION,
    AUTO_CARD_FIELD_LIMIT,
    FIXED_REGISTERS,
    FIXED_REG_SOURCE,
    FIXED_REG_SOURCE_MSG,
    FIXED_REGISTER_GROUPS,
    ISP_FUNCTION_FIELDS,
    ISP_FUNCTION_MODULES,
    ISP_FUNCTION_MSG,
    MODULE_FIELD_CARDS,
    PAD_MUX_ADDR,
    PAD_MUX_MAC_OPTIONS,
    PRIORITY_ISP_MODULES,
    list_serial_ports,
    parse_int,
    parse_int_flexible,
)
from protocol import FpgaProtocol, ISP_BATCH_CONFIG


BATCH_CSV_FORMAT_HINT = (
    "批量读写改为仅支持 CSV 文件。\n"
    "写入 CSV：至少包含 addr 和 data 两列，例如：0x4001B400,0x00000003\n"
    "读取 CSV：至少包含 addr 一列，可附带 name 备注列。\n"
    "支持表头 addr/address/地址，支持十六进制与十进制，尾部 U/L 后缀也可识别。"
)
class FpgaGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"FPGA UART 控制台 {APP_VERSION}")
        self.geometry("1200x780")
        self.minsize(1020, 650)
        self.resizable(True, True)

        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="115200")
        self.timeout_var = tk.StringVar(value="1")
        self.response_timeout_var = tk.StringVar(value="5")

        self.addr_var = tk.StringVar(value="0x0100")
        self.data_var = tk.StringVar(value="0x00000000")
        self.module_filter_var = tk.StringVar(value="全部")
        self.eye_target_var = tk.StringVar(value="L")
        self.func_eye_var = tk.StringVar(value="L")
        self.func_desc_var = tk.StringVar(value="请选择目标眼别，然后使用各模块卡片按功能配置")
        self.func_meta_var = tk.StringVar(value=ISP_FUNCTION_MSG)
        self.serial_status_var = tk.StringVar(value="状态：未连接")
        self.firmware_version_var = tk.StringVar(value="固件版本：未知")
        self.app_version_var = tk.StringVar(value=f"PC版本：{APP_VERSION}")
        self.pad_mux_if_var = tk.StringVar(value="DVP")
        self.pad_mux_mac_var = tk.IntVar(value=PAD_MUX_MAC_OPTIONS[0][0])
        self.pad_mux_ui_ready = False
        self.pad_mux_syncing = False
        self.pad_mux_poll_ms = 1500
        self.bit_info_var = tk.StringVar(value="请输入地址后点击“读取寄存器”，即可查看 16 进制值和每一位状态")
        self.preview_lock = False
        self.fpga = None
        self.serial_button_text = tk.StringVar(value="打开串口")

        self.reg_value_vars = {}
        self.reg_entry_widgets = {}
        self.func_card_vars = {}
        self.func_card_items = {}
        self.func_modules_order = self._get_function_modules_for_cards()
        self.module_scene_presets = self._build_module_scene_presets()
        self.fixed_row_items = []
        self.reg_rows = []
        self.fixed_canvas = None
        self.imported_fixed_addrs = set()
        self.bit_editor_state = {
            "addr": None,
            "orig": 0,
            "msb": 31,
            "lsb": 0,
            "values": {},
            "buttons": {},
        }

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close_app)
        self.data_var.trace_add("write", self._on_data_input_preview)
        self._refresh_ports()
        self._log(f"固定寄存器来源: {'ISP.csv' if FIXED_REG_SOURCE == 'csv' else '内置回退表'}；{FIXED_REG_SOURCE_MSG}")

    def _build_ui(self):
        padding = {"padx": 10, "pady": 6}

        # 顶部容器放置主界面可滚动内容（这样底部输出区可以固定）
        top_container = ttk.Frame(self)
        top_container.pack(fill="both", expand=True)

        self.root_canvas = tk.Canvas(top_container, highlightthickness=0)
        self.root_scrollbar = ttk.Scrollbar(top_container, orient="vertical", command=self.root_canvas.yview)
        self.root_canvas.configure(yscrollcommand=self.root_scrollbar.set)
        self.root_canvas.pack(side="left", fill="both", expand=True)
        self.root_scrollbar.pack(side="right", fill="y")

        self.root_content = ttk.Frame(self.root_canvas)
        self.root_canvas_window = self.root_canvas.create_window((0, 0), window=self.root_content, anchor="nw")
        self.root_content.bind("<Configure>", self._on_root_content_configure)
        self.root_canvas.bind("<Configure>", self._on_root_canvas_configure)
        self.bind_all("<MouseWheel>", self._on_root_mousewheel)
        self.bind_all("<Button-4>", self._on_root_mousewheel)
        self.bind_all("<Button-5>", self._on_root_mousewheel)

        # 顶部串口参数（全局）
        conn = ttk.LabelFrame(self.root_content, text="串口设置")
        conn.pack(fill="x", **padding)

        status_bar = ttk.Frame(conn)
        status_bar.grid(row=0, column=6, rowspan=2, sticky="e", padx=(16, 10), pady=6)
        ttk.Label(status_bar, textvariable=self.app_version_var, foreground="#4F4F4F").pack(anchor="e")
        ttk.Label(status_bar, textvariable=self.serial_status_var, foreground="#0B5CAD").pack(anchor="e")
        ttk.Label(status_bar, textvariable=self.firmware_version_var, foreground="#0B5CAD").pack(anchor="e", pady=(4, 0))

        ttk.Label(conn, text="端口:").grid(row=0, column=0, sticky="w", **padding)
        self.port_combo = ttk.Combobox(conn, textvariable=self.port_var, width=14, state="readonly")
        self.port_combo.grid(row=0, column=1, sticky="w", **padding)

        port_btns = ttk.Frame(conn)
        port_btns.grid(row=0, column=2, sticky="w", padx=(0, 10), pady=6)
        ttk.Button(port_btns, text="刷新", width=5, command=self._refresh_ports).pack(side="left")
        ttk.Button(port_btns, textvariable=self.serial_button_text, width=8, command=self._toggle_serial_connection).pack(
            side="left", padx=(6, 0)
        )

        ttk.Label(conn, text="波特率:").grid(row=0, column=3, sticky="w", **padding)
        ttk.Entry(conn, textvariable=self.baud_var, width=10).grid(row=0, column=4, sticky="w", **padding)

        ttk.Label(conn, text="超时(s):").grid(row=1, column=0, sticky="w", **padding)
        ttk.Entry(conn, textvariable=self.timeout_var, width=10).grid(row=1, column=1, sticky="w", **padding)

        ttk.Label(conn, text="响应超时(s):").grid(row=1, column=3, sticky="w", **padding)
        ttk.Entry(conn, textvariable=self.response_timeout_var, width=10).grid(row=1, column=4, sticky="w", **padding)

        # 两个菜单（Tab） + 结果区：使用上下可调分栏，避免小窗口看不到底部结果
        self.main_pane = ttk.Panedwindow(self.root_content, orient="vertical")
        self.main_pane.pack(fill="both", expand=True, **padding)

        self.notebook = ttk.Notebook(self.main_pane)

        self.tab_manual = ttk.Frame(self.notebook)
        self.tab_function = ttk.Frame(self.notebook)
        self.tab_fixed = ttk.Frame(self.notebook)
        self.tab_mode = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_manual, text="寄存器编辑 / 批量输入")
        self.notebook.add(self.tab_function, text="ISP功能配置")
        self.notebook.add(self.tab_fixed, text="固定寄存器读写")
        self.notebook.add(self.tab_mode, text="模式选择")

        self._build_manual_tab(self.tab_manual)
        self._build_function_tab(self.tab_function)
        self._build_fixed_tab(self.tab_fixed)
        self._build_mode_tab(self.tab_mode)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)

        self.main_pane.add(self.notebook, weight=4)

        # 将结果区固定放在窗口底部（不随上方滚动区域滚动）
        self.bottom_frame = ttk.LabelFrame(self, text="结果")
        self.bottom_frame.pack(side="bottom", fill="x")

        self.result_text = tk.Text(self.bottom_frame, height=9, wrap="word")
        self.result_scroll = ttk.Scrollbar(self.bottom_frame, orient="vertical", command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=self.result_scroll.set)
        self.result_text.pack(side="left", fill="both", expand=True, padx=10, pady=8)
        self.result_scroll.pack(side="right", fill="y", padx=(0, 8), pady=8)

    def _on_root_content_configure(self, _event=None):
        if hasattr(self, "root_canvas"):
            self.root_canvas.configure(scrollregion=self.root_canvas.bbox("all"))

    def _on_root_canvas_configure(self, event):
        if hasattr(self, "root_canvas") and hasattr(self, "root_canvas_window"):
            self.root_canvas.itemconfigure(self.root_canvas_window, width=event.width)

    def _is_descendant_of(self, widget, ancestor):
        if widget is None or ancestor is None:
            return False

        cur = widget
        while cur is not None:
            if cur == ancestor:
                return True
            try:
                parent_name = cur.winfo_parent()
                if not parent_name:
                    break
                cur = self.nametowidget(parent_name)
            except Exception:
                break
        return False

    def _on_root_mousewheel(self, event):
        if not hasattr(self, "root_canvas"):
            return

        # 文本框保持其原生滚动行为，不抢事件
        if isinstance(event.widget, tk.Text):
            return

        # 下拉框（含弹出列表）不参与外层滚动，避免展开菜单与界面滚动错位
        widget_class = ""
        widget_path = ""
        try:
            widget_class = event.widget.winfo_class()
            widget_path = str(event.widget)
        except Exception:
            pass
        if isinstance(event.widget, ttk.Combobox) or widget_class in {"TCombobox", "Combobox"} or "popdown" in widget_path:
            return "break"

        # 固定寄存器区域使用其自己的滚动逻辑
        if hasattr(self, "fixed_canvas") and self._is_descendant_of(event.widget, self.fixed_canvas):
            return

        bbox = self.root_canvas.bbox("all")
        if not bbox:
            return

        content_height = bbox[3] - bbox[1]
        canvas_height = self.root_canvas.winfo_height()
        if content_height <= canvas_height:
            return

        # Windows / macOS: MouseWheel(delta), Linux: Button-4/5
        if hasattr(event, "delta") and event.delta:
            step = -int(event.delta / 120)
            if step == 0:
                step = -1 if event.delta > 0 else 1
        elif getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            return

        self.root_canvas.yview_scroll(step, "units")
        return "break"

    def _build_manual_tab(self, parent):
        padding = {"padx": 10, "pady": 6}

        cmd_frame = ttk.LabelFrame(parent, text="寄存器编辑")
        cmd_frame.pack(fill="x", **padding)

        ttk.Label(cmd_frame, text="地址 (ADDR):").grid(row=0, column=0, sticky="w", **padding)
        addr_entry = ttk.Entry(cmd_frame, textvariable=self.addr_var, width=18)
        addr_entry.grid(row=0, column=1, sticky="w", **padding)

        ttk.Label(cmd_frame, text="数据 (HEX):").grid(row=0, column=2, sticky="w", **padding)
        self.data_entry = ttk.Entry(cmd_frame, textvariable=self.data_var, width=18)
        self.data_entry.grid(row=0, column=3, sticky="w", **padding)

        ttk.Button(cmd_frame, text="读取寄存器", command=self._manual_read_register).grid(row=0, column=4, sticky="e", **padding)
        ttk.Button(cmd_frame, text="写入寄存器", command=self._manual_write_register).grid(row=0, column=5, sticky="e", **padding)

        ttk.Label(
            cmd_frame,
            text="说明：读取后会同时显示 16 进制值与每一位；点击位值会立即写回寄存器。",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=6, sticky="w", padx=10, pady=(0, 6))

        addr_entry.bind("<Return>", lambda _e: self._manual_read_register())
        self.data_entry.bind("<Return>", lambda _e: self._manual_write_register())

        ttk.Label(parent, textvariable=self.bit_info_var, foreground="#333333").pack(anchor="w", padx=14, pady=(0, 6))

        bit_frame = ttk.LabelFrame(parent, text="位值（4bit/8bit 分组，点击 0/1 立即写回）")
        bit_frame.pack(fill="none", anchor="w", padx=12, pady=(0, 10))

        self.bit_canvas = tk.Canvas(bit_frame, width=820, height=170, highlightthickness=0)
        bit_scroll = ttk.Scrollbar(bit_frame, orient="vertical", command=self.bit_canvas.yview)
        self.bit_inner = ttk.Frame(self.bit_canvas)
        self.bit_canvas.configure(yscrollcommand=bit_scroll.set)
        self.bit_canvas.create_window((0, 0), window=self.bit_inner, anchor="nw")
        self.bit_inner.bind("<Configure>", lambda _e: self.bit_canvas.configure(scrollregion=self.bit_canvas.bbox("all")))

        self.bit_canvas.pack(side="left", fill="none", expand=False, padx=(8, 0), pady=8)
        bit_scroll.pack(side="right", fill="y", padx=(0, 8), pady=8)

        ttk.Button(cmd_frame, text="ISP 批量配置", command=self._apply_isp_batch).grid(row=2, column=5, sticky="e", **padding)

        batch_frame = ttk.LabelFrame(parent, text="CSV 批量读写")
        batch_frame.pack(fill="x", **padding)

        ttk.Label(batch_frame, text=BATCH_CSV_FORMAT_HINT, justify="left").pack(anchor="w", padx=10, pady=(8, 8))

        batch_btns = ttk.Frame(batch_frame)
        batch_btns.pack(anchor="e", padx=10, pady=(0, 8))
        ttk.Button(batch_btns, text="CSV 批量写入", command=self._import_manual_csv_batch).pack(side="left")
        ttk.Button(batch_btns, text="CSV 批量读取并导出结果", command=self._import_manual_csv_read).pack(side="left", padx=(8, 0))

    def _build_module_scene_presets(self):
        modules = self._get_function_modules_for_cards()
        presets = {"L": {}, "R": {}}
        for eye in ["L", "R"]:
            for module in modules:
                presets[eye][module] = []

        for addr, name, value in ISP_BATCH_CONFIG:
            module, eye = self._classify_addr_to_module_eye(addr)
            if not module or not eye:
                continue
            presets[eye][module].append((addr, name, value))

        for eye in ["L", "R"]:
            for module in modules:
                presets[eye][module].sort(key=lambda x: x[0])
        return presets

    def _get_function_modules_for_cards(self):
        all_modules = sorted(ISP_FUNCTION_MODULES.keys())
        if not all_modules:
            return list(PRIORITY_ISP_MODULES)

        ordered = [m for m in PRIORITY_ISP_MODULES if m in all_modules]
        ordered.extend([m for m in all_modules if m not in ordered])
        return ordered

    def _get_module_card_fields(self, module):
        configured = MODULE_FIELD_CARDS.get(module, [])
        module_items = ISP_FUNCTION_MODULES.get(module, [])

        def _exists(field_name):
            return any(it.get("field_name") == field_name for it in module_items)

        if configured:
            filtered = [f for f in configured if _exists(f)]
            if filtered:
                return filtered

        rw_items = [it for it in module_items if "W" in str(it.get("access", ""))]
        ro_items = [it for it in module_items if "W" not in str(it.get("access", ""))]

        picked = []
        seen = set()
        for item in rw_items + ro_items:
            name = item.get("field_name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            picked.append(name)
            if len(picked) >= AUTO_CARD_FIELD_LIMIT:
                break
        return picked

    def _classify_addr_to_module_eye(self, addr):
        base_eye_map = {
            0x4001B000: "L",
            0x4001D000: "R",
        }
        for base, eye in base_eye_map.items():
            offset = addr - base
            if offset < 0:
                continue
            if 0x000 <= offset <= 0x003:
                return "ISP_CTRL", eye
            if 0x004 <= offset <= 0x014:
                return "isp_inform", eye
            if 0x120 <= offset <= 0x14C:
                return "REC", eye
            if 0x174 <= offset <= 0x198:
                return "isp_outform", eye
            if 0x400 <= offset <= 0x414:
                return "NLM", eye
        return None, None

    def _build_function_tab(self, parent):
        padding = {"padx": 10, "pady": 6}
        self.func_modules_order = self._get_function_modules_for_cards()

        top = ttk.LabelFrame(parent, text="ISP专用模式面板（模块化卡片 + 一键应用场景）")
        top.pack(fill="x", **padding)

        ttk.Label(top, text="目标眼别:").grid(row=0, column=0, sticky="w", **padding)
        func_eye = ttk.Combobox(top, textvariable=self.func_eye_var, values=["L", "R"], width=5, state="readonly")
        func_eye.grid(row=0, column=1, sticky="w", **padding)
        func_eye.bind("<<ComboboxSelected>>", self._on_function_eye_changed)

        ttk.Button(top, text="应用当前眼别全部模块场景", command=self._apply_all_module_scenes).grid(
            row=0, column=2, sticky="w", padx=(0, 10), pady=6
        )
        ttk.Button(top, text="读取全部模块关键字段", command=self._refresh_all_module_cards).grid(
            row=0, column=3, sticky="w", padx=(0, 10), pady=6
        )

        ttk.Label(top, textvariable=self.func_meta_var, foreground="#444444", wraplength=980, justify="left").grid(
            row=1, column=0, columnspan=4, sticky="w", padx=10, pady=(2, 4)
        )
        ttk.Label(top, textvariable=self.func_desc_var, foreground="#666666", wraplength=980, justify="left").grid(
            row=2, column=0, columnspan=4, sticky="w", padx=10, pady=(0, 8)
        )

        cards = ttk.Frame(parent)
        cards.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        self.func_card_vars = {}
        self.func_card_items = {}
        for idx, module in enumerate(self.func_modules_order):
            card = ttk.LabelFrame(cards, text=f"{module} 模块")
            card.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=6, pady=6)
            cards.grid_columnconfigure(idx % 2, weight=1)
            cards.grid_rowconfigure(idx // 2, weight=1)
            self._build_module_card(card, module)

        self.func_desc_var.set(
            f"当前共 {len(self.func_modules_order)} 个模块卡片（含原5个重点模块 + 其余自动扩展模块）。"
        )

        if not ISP_FUNCTION_MODULES:
            self.func_desc_var.set(f"功能配置不可用：{ISP_FUNCTION_MSG}")

    def _build_module_card(self, parent, module):
        controls = self._get_module_card_fields(module)
        self.func_card_vars[module] = {}
        self.func_card_items[module] = {}

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Button(btn_row, text="一键应用场景", command=lambda m=module: self._apply_module_scene_preset(m)).pack(side="left")
        ttk.Button(btn_row, text="读取关键字段", command=lambda m=module: self._refresh_module_card(m)).pack(side="left", padx=(6, 0))
        ttk.Button(btn_row, text="应用本卡设置", command=lambda m=module: self._apply_module_card_values(m)).pack(side="left", padx=(6, 0))

        row_host = ttk.Frame(parent)
        row_host.pack(fill="x", padx=8, pady=(2, 8))

        if not controls:
            ttk.Label(row_host, text="该模块暂无可展示字段", foreground="#777777").grid(row=0, column=0, sticky="w", pady=2)
            return

        for row_idx, field_name in enumerate(controls):
            item = self._find_module_field_item(module, field_name)
            self.func_card_items[module][field_name] = item

            ttk.Label(row_host, text=f"{field_name}:").grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=3)

            value_var = tk.StringVar(value="")
            self.func_card_vars[module][field_name] = value_var

            if item and item.get("options"):
                options = [f"{v}: {name}" for v, name in item["options"]]
                editor = ttk.Combobox(row_host, textvariable=value_var, values=options, width=28, state="readonly")
                if options:
                    value_var.set(options[0])
            else:
                editor = ttk.Entry(row_host, textvariable=value_var, width=30)
                value_var.set("0")

            editor.grid(row=row_idx, column=1, sticky="w", padx=(0, 6), pady=3)
            ttk.Button(
                row_host,
                text="读",
                width=4,
                command=lambda m=module, f=field_name: self._read_single_card_field(m, f),
            ).grid(row=row_idx, column=2, sticky="w", padx=(0, 4), pady=3)
            ttk.Button(
                row_host,
                text="写",
                width=4,
                command=lambda m=module, f=field_name: self._apply_single_card_field(m, f),
            ).grid(row=row_idx, column=3, sticky="w", pady=3)

    def _resolve_func_item_addr(self, item):
        if item.get("is_lr"):
            base = item.get("base_l") if self.func_eye_var.get() == "L" else item.get("base_r")
            return int(base) + int(item.get("offset", 0))
        return int(item.get("addr", 0))

    def _find_module_field_item(self, module, field_name):
        for item in ISP_FUNCTION_MODULES.get(module, []):
            if item.get("field_name") == field_name:
                return item
        return None

    def _on_function_eye_changed(self, _event=None):
        eye = self.func_eye_var.get()
        self.func_desc_var.set(f"当前目标眼别: {eye}。可直接使用各模块卡片“读/写/一键应用场景”。")

    def _parse_card_field_value(self, item, text):
        if item is None:
            raise ValueError("字段未在 ISP.csv 中找到")
        if text is None:
            raise ValueError("请输入字段值")

        raw = str(text).strip()
        if not raw:
            raise ValueError("请输入字段值")

        m = re.match(r"^\s*(\d+)\s*:", raw)
        if m:
            value = int(m.group(1), 10)
        else:
            value = parse_int_flexible(raw)

        max_value = (1 << item["width"]) - 1
        if value < 0 or value > max_value:
            raise ValueError(f"字段值超范围: 0 ~ {max_value}")
        return value

    def _func_decode_field(self, reg_value, item):
        mask = (1 << item["width"]) - 1
        return (reg_value >> item["lsb"]) & mask

    def _read_single_card_field(self, module, field_name):
        try:
            item = self.func_card_items.get(module, {}).get(field_name)
            if not item:
                raise ValueError(f"字段不存在: {module}.{field_name}")

            addr = self._resolve_func_item_addr(item)
            reg_val, result = self._read_register_value(addr)
            field_val = self._func_decode_field(reg_val, item)

            target_var = self.func_card_vars.get(module, {}).get(field_name)
            if target_var is not None:
                option_label = next((name for v, name in item.get("options", []) if v == field_val), "")
                target_var.set(f"{field_val}: {option_label}" if option_label else str(field_val))

            self.func_meta_var.set(
                f"{module}.{field_name} @0x{addr:08X} [{item['msb']}:{item['lsb']}] = {field_val} (目标: {self.func_eye_var.get()})"
            )
            self.func_desc_var.set(item.get("description") or "（无描述）")
            self._log(
                f"CARD READ {module}.{field_name} @0x{addr:08X} [{item['msb']}:{item['lsb']}] = {field_val} "
                f"(RAW=0x{reg_val:08X}) -> {self._format_result_for_log(result)}"
            )
        except Exception as exc:
            messagebox.showerror("读取字段失败", str(exc))

    def _apply_single_card_field(self, module, field_name):
        try:
            item = self.func_card_items.get(module, {}).get(field_name)
            if not item:
                raise ValueError(f"字段不存在: {module}.{field_name}")
            if "W" not in item.get("access", ""):
                raise ValueError("该字段为只读，不支持写入")

            value_var = self.func_card_vars.get(module, {}).get(field_name)
            new_field_val = self._parse_card_field_value(item, value_var.get() if value_var else "")

            addr = self._resolve_func_item_addr(item)
            old_reg_val, _ = self._read_register_value(addr)
            field_mask = ((1 << item["width"]) - 1) << item["lsb"]
            new_reg_val = (old_reg_val & ~field_mask) | ((new_field_val << item["lsb"]) & field_mask)

            result = self._write_register_value(addr, new_reg_val)
            self.func_meta_var.set(
                f"{module}.{field_name} 已写入: {new_field_val}，RAW 0x{old_reg_val:08X} -> 0x{new_reg_val:08X}"
            )
            self.func_desc_var.set(item.get("description") or "（无描述）")
            self._log(
                f"CARD WRITE {module}.{field_name} @0x{addr:08X} [{item['msb']}:{item['lsb']}]={new_field_val}, "
                f"RAW: 0x{old_reg_val:08X} -> 0x{new_reg_val:08X} -> {self._format_result_for_log(result)}"
            )
        except Exception as exc:
            messagebox.showerror("写入字段失败", str(exc))

    def _refresh_module_card(self, module):
        for field_name in self._get_module_card_fields(module):
            self._read_single_card_field(module, field_name)

    def _refresh_all_module_cards(self):
        for module in self.func_modules_order:
            self._refresh_module_card(module)

    def _apply_module_card_values(self, module):
        for field_name in self._get_module_card_fields(module):
            item = self.func_card_items.get(module, {}).get(field_name)
            if item and "W" in item.get("access", ""):
                self._apply_single_card_field(module, field_name)

    def _apply_module_scene_preset(self, module):
        try:
            eye = self.func_eye_var.get()
            rows = self.module_scene_presets.get(eye, {}).get(module, [])
            if not rows:
                raise ValueError(f"未找到 {module} 的 {eye} 眼场景参数")

            if not messagebox.askyesno("确认", f"确定一键应用 {module} ({eye} 眼) 场景参数，共 {len(rows)} 项吗？"):
                return

            for addr, name, value in rows:
                result = self._write_register_value(addr, value)
                self._log(f"SCENE WRITE {module}({eye}) {name} @0x{addr:08X} = 0x{value:08X} -> {self._format_result_for_log(result)}")

            self.func_meta_var.set(f"{module}({eye}) 场景参数应用完成，共 {len(rows)} 项")
            self.func_desc_var.set("可点击“读取关键字段”确认当前生效值")
        except Exception as exc:
            messagebox.showerror("应用场景失败", str(exc))

    def _apply_all_module_scenes(self):
        eye = self.func_eye_var.get()
        total = sum(len(self.module_scene_presets.get(eye, {}).get(module, [])) for module in self.func_modules_order)
        if total <= 0:
            messagebox.showwarning("提示", f"当前未找到 {eye} 眼可用场景参数")
            return

        if not messagebox.askyesno("确认", f"确定应用 {eye} 眼全部模块场景参数吗？总计 {total} 项"):
            return

        for module in self.func_modules_order:
            rows = self.module_scene_presets.get(eye, {}).get(module, [])
            for addr, name, value in rows:
                result = self._write_register_value(addr, value)
                self._log(f"SCENE WRITE {module}({eye}) {name} @0x{addr:08X} = 0x{value:08X} -> {self._format_result_for_log(result)}")

        self.func_meta_var.set(f"{eye} 眼全部模块场景参数应用完成，共 {total} 项")
        self.func_desc_var.set("可点击“读取全部模块关键字段”做一次回读确认")

    def _build_fixed_tab(self, parent):
        padding = {"padx": 8, "pady": 4}

        top_btn = ttk.Frame(parent)
        top_btn.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Button(top_btn, text="全部读取", command=self._fixed_read_all).pack(side="left")
        ttk.Button(top_btn, text="全部写入", command=self._fixed_write_all).pack(side="left", padx=(8, 0))
        ttk.Button(top_btn, text="重置输入", command=self._reset_fixed_inputs).pack(side="left", padx=(8, 0))
        ttk.Button(top_btn, text="导入CSV", command=self._import_fixed_csv).pack(side="left", padx=(8, 0))
        ttk.Button(top_btn, text="导出CSV", command=self._export_fixed_csv).pack(side="left", padx=(8, 0))

        ttk.Label(top_btn, text="目标: ").pack(side="left", padx=(14, 2))
        eye_target = ttk.Combobox(
            top_btn,
            textvariable=self.eye_target_var,
            values=["L", "R"],
            width=4,
            state="readonly",
        )
        eye_target.pack(side="left")
        eye_target.bind("<<ComboboxSelected>>", self._on_eye_target_changed)

        ttk.Label(top_btn, text="模块:").pack(side="right", padx=(0, 4))
        module_filter = ttk.Combobox(
            top_btn,
            textvariable=self.module_filter_var,
            values=["全部"] + sorted(FIXED_REGISTER_GROUPS.keys()),
            width=18,
            state="readonly",
        )
        module_filter.pack(side="right")
        module_filter.bind("<<ComboboxSelected>>", self._apply_module_filter)
        module_filter.bind("<MouseWheel>", lambda _e: "break")
        module_filter.bind("<Button-4>", lambda _e: "break")
        module_filter.bind("<Button-5>", lambda _e: "break")

        # 可滚动区域
        canvas = tk.Canvas(parent, highlightthickness=0)
        self.fixed_canvas = canvas
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        self.fixed_inner = ttk.Frame(canvas)

        self.fixed_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.fixed_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 8))
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=(0, 8))

        # 固定寄存器页滚轮支持（Windows / Linux）：仅绑定在固定寄存器页控件，避免全局联动
        self._bind_fixed_mousewheel_target(canvas)
        self._bind_fixed_mousewheel_target(self.fixed_inner)

        headers = ["模块", "寄存器名", "地址", "位宽", "值", "操作"]
        for col, h in enumerate(headers):
            header_label = ttk.Label(self.fixed_inner, text=h, font=("Segoe UI", 9, "bold"))
            header_label.grid(row=0, column=col, sticky="w", **padding)
            self._bind_fixed_mousewheel_target(header_label)

        self.fixed_row_items = []
        for i, item in enumerate(FIXED_REGISTERS, start=1):
            row_id = i - 1
            self.fixed_row_items.append(item)

            module = item["module"]
            name = item["name"]
            bits = item["bits"]
            addr_text = self._format_item_addr(item)

            module_label = ttk.Label(self.fixed_inner, text=module, width=12)
            module_label.grid(row=i, column=0, sticky="w", **padding)
            name_label = ttk.Label(self.fixed_inner, text=name, width=26)
            name_label.grid(row=i, column=1, sticky="w", **padding)
            addr_label = ttk.Label(self.fixed_inner, text=addr_text, width=14)
            addr_label.grid(row=i, column=2, sticky="w", **padding)
            bits_label = ttk.Label(self.fixed_inner, text=bits, width=8)
            bits_label.grid(row=i, column=3, sticky="w", **padding)

            v = tk.StringVar(value="")
            self.reg_value_vars[row_id] = v
            entry = tk.Entry(self.fixed_inner, textvariable=v, width=14)
            entry.grid(row=i, column=4, sticky="w", **padding)
            self.reg_entry_widgets[row_id] = entry
            v.trace_add("write", lambda *_args, rid=row_id: self._validate_reg_value(rid))

            action_frame = ttk.Frame(self.fixed_inner)
            action_frame.grid(row=i, column=5, sticky="w", **padding)
            read_btn = ttk.Button(action_frame, text="读", width=4, command=lambda rid=row_id: self._fixed_read_one(rid))
            read_btn.pack(side="left")
            write_btn = ttk.Button(action_frame, text="写", width=4, command=lambda rid=row_id: self._fixed_write_one(rid))
            write_btn.pack(side="left", padx=(4, 0))

            self._bind_fixed_mousewheel_target(module_label)
            self._bind_fixed_mousewheel_target(name_label)
            self._bind_fixed_mousewheel_target(addr_label)
            self._bind_fixed_mousewheel_target(bits_label)
            self._bind_fixed_mousewheel_target(entry)
            self._bind_fixed_mousewheel_target(action_frame)
            self._bind_fixed_mousewheel_target(read_btn)
            self._bind_fixed_mousewheel_target(write_btn)

            self.reg_rows.append(
                {
                    "row_id": row_id,
                    "addr_label": addr_label,
                    "module": module,
                    "name": name,
                    "widgets": [module_label, name_label, addr_label, bits_label, entry, action_frame],
                }
            )
            self._validate_reg_value(row_id)

        self._apply_module_filter()

    def _build_mode_tab(self, parent):
        pad_mux_frame = ttk.LabelFrame(parent, text="PAD_MUX(0x4001C030)")
        pad_mux_frame.pack(fill="x", padx=12, pady=12)

        ttk.Button(pad_mux_frame, text="读取当前模式", command=self._sync_pad_mux_from_hw).grid(
            row=0, column=2, sticky="e", padx=8, pady=8
        )

        ttk.Label(pad_mux_frame, text="输入选择:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        if_frame = ttk.Frame(pad_mux_frame)
        if_frame.grid(row=0, column=1, sticky="w", padx=8, pady=8)
        ttk.Radiobutton(
            if_frame,
            text="DVP (0)",
            variable=self.pad_mux_if_var,
            value="DVP",
            command=self._on_pad_mux_selection_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            if_frame,
            text="MIPI (1)",
            variable=self.pad_mux_if_var,
            value="MIPI",
            command=self._on_pad_mux_selection_changed,
        ).pack(side="left", padx=(12, 0))

        mode_frame = ttk.LabelFrame(parent, text="Ethernet输出数据选择（PAD_MUX[3:0]）")
        mode_frame.pack(fill="x", padx=12, pady=(0, 8))

        for idx, (val, name) in enumerate(PAD_MUX_MAC_OPTIONS):
            r = idx // 2
            c = idx % 2
            ttk.Radiobutton(
                mode_frame,
                text=f"{val}: {name}",
                variable=self.pad_mux_mac_var,
                value=val,
                command=self._on_pad_mux_selection_changed,
            ).grid(row=r, column=c, sticky="w", padx=10, pady=4)

        tip = (
            "说明：勾选后会立即读取 PAD_MUX，然后仅修改 bit31 与 bit[3:0] 并写回，"
            "不会影响其它位。"
        )
        ttk.Label(parent, text=tip, foreground="#555555", wraplength=900, justify="left").pack(
            fill="x", padx=14, pady=(0, 8)
        )

        self.pad_mux_ui_ready = True

    def _on_notebook_tab_changed(self, _event=None):
        try:
            selected = self.notebook.select()
        except Exception:
            return

        if selected == str(self.tab_mode):
            self._sync_pad_mux_from_hw()
            self._schedule_pad_mux_poll()

    def _schedule_pad_mux_poll(self):
        self.after(self.pad_mux_poll_ms, self._poll_pad_mux_when_mode_tab_active)

    def _poll_pad_mux_when_mode_tab_active(self):
        try:
            if self.notebook.select() == str(self.tab_mode):
                self._sync_pad_mux_from_hw(silent=True)
                self._schedule_pad_mux_poll()
        except Exception:
            return

    def _sync_pad_mux_from_hw(self, silent=False):
        if not self.pad_mux_ui_ready or self.pad_mux_syncing:
            return

        try:
            self.pad_mux_syncing = True
            value, _result = self._read_register_value(PAD_MUX_ADDR)
            if_mode = "MIPI" if ((value >> 31) & 0x1) else "DVP"
            mac_sel = value & 0xF

            self.pad_mux_if_var.set(if_mode)
            self.pad_mux_mac_var.set(mac_sel)

            if not silent:
                self._log(f"PAD_MUX 同步: RAW=0x{value:08X}, IF={if_mode}, MAC_SEL={mac_sel}")
        except Exception as exc:
            if not silent:
                messagebox.showerror("读取 PAD_MUX 失败", str(exc))
        finally:
            self.pad_mux_syncing = False

    def _bind_fixed_mousewheel_target(self, widget):
        widget.bind("<MouseWheel>", self._on_fixed_mousewheel)
        widget.bind("<Button-4>", self._on_fixed_mousewheel)
        widget.bind("<Button-5>", self._on_fixed_mousewheel)

    def _on_fixed_mousewheel(self, event):
        if not self.fixed_canvas:
            return
        if not hasattr(self, "notebook"):
            return
        if self.notebook.select() != str(self.tab_fixed):
            return

        # Windows / macOS: MouseWheel(delta), Linux: Button-4/5
        if hasattr(event, "delta") and event.delta:
            step = -int(event.delta / 120)
            if step == 0:
                step = -1 if event.delta > 0 else 1
        elif getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            return

        self.fixed_canvas.yview_scroll(step, "units")
        return "break"

    def _refresh_ports(self):
        ports = list_serial_ports()
        self.port_combo["values"] = ports
        if ports:
            if self.port_var.get() not in ports:
                self.port_var.set(ports[0])
        else:
            self.port_var.set("")

    def _get_serial_params(self):
        port = self.port_var.get().strip()
        if not port:
            raise ValueError("请选择串口端口")
        baud = int(self.baud_var.get())
        timeout = float(self.timeout_var.get())
        response_timeout = float(self.response_timeout_var.get())
        return port, baud, timeout, response_timeout

    def _toggle_serial_connection(self):
        if self.fpga is None:
            self._open_serial_connection()
        else:
            self._close_serial_connection(show_log=True)

    def _open_serial_connection(self):
        try:
            port, baud, timeout, response_timeout = self._get_serial_params()
            fpga = FpgaProtocol(port, baud, timeout)
            fpga.response_timeout = response_timeout

            self.fpga = fpga
            self.serial_button_text.set("关闭串口")
            self.serial_status_var.set(f"状态：已连接（{port}）")
            self.firmware_version_var.set("固件版本：查询中...")
            self._log(f"串口已打开: {port} @ {baud}")

            startup_text = fpga.read_pending_text(initial_wait=0.6, idle_gap=0.2)
            self._log_serial_messages(startup_text)

            try:
                major, minor, patch, result = fpga.query_firmware_version()
                self.firmware_version_var.set(f"固件版本：v{major}.{minor}.{patch}")
                self._log(f"固件版本: v{major}.{minor}.{patch} -> {self._format_result_for_log(result)}")
            except Exception as exc:
                self.firmware_version_var.set("固件版本：查询失败")
                self._log(f"固件版本查询失败: {exc}")
        except Exception as exc:
            if self.fpga is not None:
                try:
                    self.fpga.close()
                except Exception:
                    pass
            self.fpga = None
            self.serial_button_text.set("打开串口")
            self.serial_status_var.set("状态：未连接")
            self.firmware_version_var.set("固件版本：未知")
            messagebox.showerror("打开串口失败", str(exc))

    def _close_serial_connection(self, show_log=False):
        if self.fpga is None:
            return

        try:
            self.fpga.close()
        finally:
            self.fpga = None
            self.serial_button_text.set("打开串口")
            self.serial_status_var.set("状态：未连接")
            self.firmware_version_var.set("固件版本：未知")
            if show_log:
                self._log("串口已关闭")

    def _on_close_app(self):
        self._close_serial_connection(show_log=False)
        self.destroy()

    def _require_fpga_connection(self):
        if self.fpga is None:
            raise ValueError("请先点击“打开串口”连接设备")
        return self.fpga

    def _log_serial_messages(self, raw_text):
        if not raw_text:
            return

        version_pattern = re.compile(r"FW_VERSION\s*:\s*([0-9]+(?:\.[0-9]+){1,2})", re.IGNORECASE)
        for line in raw_text.splitlines():
            text = line.strip()
            if not text:
                continue

            matched = version_pattern.search(text)
            if matched:
                self.firmware_version_var.set(f"固件版本：v{matched.group(1)}")
                self._log(f"启动版本信息: v{matched.group(1)}")
            else:
                self._log(f"串口消息: {text}")

    def _log(self, text):
        self.result_text.insert("end", text + "\n")
        self.result_text.see("end")

    def _format_result_for_log(self, result):
        if isinstance(result, dict):
            formatted = {}
            for key, value in result.items():
                if isinstance(value, int) and str(key).lower() == "data":
                    formatted[key] = f"0x{value:08X}"
                else:
                    formatted[key] = value
            return formatted
        return result

    def _resolve_item_addr(self, item):
        if item.get("is_lr"):
            base = item.get("base_l") if self.eye_target_var.get() == "L" else item.get("base_r")
            return int(base) + int(item.get("offset", 0))
        return int(item.get("addr", 0))

    def _format_item_addr(self, item):
        addr = self._resolve_item_addr(item)
        suffix = f" ({self.eye_target_var.get()})" if item.get("is_lr") else ""
        return f"0x{addr:08X}{suffix}"

    def _get_fixed_reg_name(self, row_id):
        item = self.fixed_row_items[row_id]
        return item.get("name", f"row_{row_id}")

    def _on_eye_target_changed(self, _event=None):
        for row in self.reg_rows:
            rid = row.get("row_id")
            if rid is None:
                continue
            item = self.fixed_row_items[rid]
            row["addr_label"].configure(text=self._format_item_addr(item))

    def _bit_set_button_visual(self, bit):
        btn = self.bit_editor_state["buttons"].get(bit)
        if not btn:
            return
        val = self.bit_editor_state["values"].get(bit, 0)
        btn.configure(text=str(val))

    def _compose_bit_state_word(self):
        word = 0
        msb = self.bit_editor_state["msb"]
        lsb = self.bit_editor_state["lsb"]
        for bit in range(msb, lsb - 1, -1):
            if self.bit_editor_state["values"].get(bit, 0):
                word |= (1 << bit)
        return word

    def _load_register_editor_value(self, addr, data_word):
        self.bit_editor_state["addr"] = addr
        self.bit_editor_state["orig"] = data_word
        self.bit_editor_state["msb"] = 31
        self.bit_editor_state["lsb"] = 0
        self.bit_editor_state["values"] = {bit: ((data_word >> bit) & 0x1) for bit in range(31, -1, -1)}

        self.addr_var.set(f"0x{addr:08X}")
        self.preview_lock = True
        self.data_var.set(f"0x{data_word:08X}")
        self.preview_lock = False
        self.bit_info_var.set(f"当前值: 0x{data_word:08X}    区间=[31:0]    点击位值可直接写回")
        self._bit_render_values()

    def _on_data_input_preview(self, *_args):
        if self.preview_lock:
            return

        text = self.data_var.get().strip()
        if not text:
            return

        try:
            value = parse_int_flexible(text)
            if not (0 <= value <= 0xFFFFFFFF):
                raise ValueError("数据超出 32-bit 范围")
        except Exception:
            return

        self.bit_editor_state["msb"] = 31
        self.bit_editor_state["lsb"] = 0
        self.bit_editor_state["values"] = {bit: ((value >> bit) & 0x1) for bit in range(31, -1, -1)}
        self._bit_render_values()
        self.bit_info_var.set(f"预览值: 0x{value:08X}    区间=[31:0]    （尚未写入寄存器）")

    def _bit_toggle_value(self, bit):
        addr = self.bit_editor_state.get("addr")
        if addr is None:
            messagebox.showwarning("按位编辑", "请先读取寄存器")
            return

        old_values = dict(self.bit_editor_state["values"])
        old_word = self._compose_bit_state_word()
        self.bit_editor_state["values"][bit] = 0 if self.bit_editor_state["values"].get(bit, 0) else 1
        new_word = self._compose_bit_state_word()

        try:
            result = self._write_register_value(addr, new_word)
            self.bit_editor_state["orig"] = new_word
            self.preview_lock = True
            self.data_var.set(f"0x{new_word:08X}")
            self.preview_lock = False
            self.bit_info_var.set(f"当前值: 0x{new_word:08X}    区间=[31:0]    点击位值可直接写回")
            self._bit_set_button_visual(bit)
            self._log(
                f"按位翻转写回 0x{addr:08X}: BIT[{bit}] -> {self.bit_editor_state['values'][bit]}, "
                f"OLD=0x{old_word:08X}, NEW=0x{new_word:08X} -> {self._format_result_for_log(result)}"
            )
        except Exception as exc:
            self.bit_editor_state["values"] = old_values
            self._bit_set_button_visual(bit)
            messagebox.showerror("写回失败", str(exc))

    def _bit_render_values(self):
        for w in self.bit_inner.winfo_children():
            w.destroy()

        msb = self.bit_editor_state["msb"]
        lsb = self.bit_editor_state["lsb"]
        self.bit_editor_state["buttons"] = {}

        bits_per_row = 16
        index = 0
        for bit in range(msb, lsb - 1, -1):
            row = index // bits_per_row
            col = index % bits_per_row
            cell = ttk.Frame(self.bit_inner)
            left_gap = 2
            if col > 0 and col % 4 == 0:
                left_gap = 8
            if col > 0 and col % 8 == 0:
                left_gap = 14
            cell.grid(row=row, column=col, padx=(left_gap, 2), pady=2)

            ttk.Label(cell, text=f"{bit:02d}", font=("Segoe UI", 8)).pack()
            btn = tk.Button(cell, text="0", width=2, command=lambda b=bit: self._bit_toggle_value(b))
            btn.pack(pady=(2, 0))
            self.bit_editor_state["buttons"][bit] = btn
            self._bit_set_button_visual(bit)
            index += 1

    def _manual_read_register(self):
        try:
            addr = parse_int_flexible(self.addr_var.get())
            data_word, result = self._read_register_value(addr)
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            return

        self._load_register_editor_value(addr, data_word)
        self._log(f"READ 0x{addr:08X} -> {self._format_result_for_log(result)}")

    def _manual_write_register(self):
        try:
            addr = parse_int_flexible(self.addr_var.get())
            value = parse_int_flexible(self.data_var.get())
            if not (0 <= value <= 0xFFFFFFFF):
                raise ValueError("数据超出 32-bit 范围")
            result = self._write_register_value(addr, value)
        except Exception as exc:
            messagebox.showerror("写入失败", str(exc))
            return

        self._load_register_editor_value(addr, value)
        self._log(f"WRITE 0x{addr:08X} = 0x{value:08X} -> {self._format_result_for_log(result)}")

    def _extract_data_value(self, result):
        if not isinstance(result, dict):
            raise ValueError(f"返回异常: {result}")

        raw = result.get("data", 0)
        if isinstance(raw, str):
            return int(raw, 0)
        return int(raw)

    def _read_register_value(self, addr):
        fpga = self._require_fpga_connection()
        result = fpga.send_command(cmd=0x52, addr=addr, data=0)
        return self._extract_data_value(result), result

    def _write_register_value(self, addr, value):
        fpga = self._require_fpga_connection()
        result = fpga.send_command(cmd=0x57, addr=addr, data=value)
        return result

    def _on_pad_mux_selection_changed(self):
        if not self.pad_mux_ui_ready or self.pad_mux_syncing:
            return
        self._apply_pad_mux_config()

    def _apply_pad_mux_config(self):
        try:
            current, _ = self._read_register_value(PAD_MUX_ADDR)

            new_val = current
            # PAD_MUX[31]: 0 DVP, 1 MIPI
            if self.pad_mux_if_var.get() == "MIPI":
                new_val |= (1 << 31)
            else:
                new_val &= ~(1 << 31)

            # mac_out_select[3:0] = PAD_MUX[3:0]
            mac_sel = int(self.pad_mux_mac_var.get())
            if not (0 <= mac_sel <= 0xF):
                raise ValueError("mac_out_select 范围应为 0~15")
            new_val = (new_val & ~0xF) | (mac_sel & 0xF)

            if new_val == current:
                self._log(f"PAD_MUX 无需修改: 0x{current:08X} -> 0x{new_val:08X}")
                return

            write_result = self._write_register_value(PAD_MUX_ADDR, new_val)
            self._log(
                f"PAD_MUX 更新: OLD=0x{current:08X}, NEW=0x{new_val:08X}, "
                f"IF={self.pad_mux_if_var.get()}, MAC_SEL={mac_sel} -> {self._format_result_for_log(write_result)}"
            )
            self._sync_pad_mux_from_hw(silent=True)
        except Exception as exc:
            messagebox.showerror("应用 PAD_MUX 失败", str(exc))

    def _apply_module_filter(self, _event=None):
        mode = self.module_filter_var.get()
        for row in self.reg_rows:
            show = True if mode == "全部" else (row.get("module") == mode)

            for w in row["widgets"]:
                if show:
                    w.grid()
                else:
                    w.grid_remove()

        self.fixed_inner.update_idletasks()

    def _validate_reg_value(self, addr):
        widget = self.reg_entry_widgets.get(addr)
        var = self.reg_value_vars.get(addr)
        if not widget or var is None:
            return

        try:
            text = var.get().strip()
            if text == "":
                widget.configure(fg="black")
                return

            value = parse_int(text)
            if not (0 <= value <= 0xFFFFFFFF):
                raise ValueError("超出32位")
            widget.configure(fg="black")
        except Exception:
            widget.configure(fg="red")

    def _apply_isp_batch(self):
        try:
            fpga = self._require_fpga_connection()
        except Exception as exc:
            messagebox.showerror("错误", str(exc))
            return

        if not messagebox.askyesno("确认", "确定要执行 ISP 批量配置吗？"):
            return

        self._log("开始 ISP 批量配置...")
        self.update_idletasks()

        failures = []
        try:
            for idx, (addr, name, value) in enumerate(ISP_BATCH_CONFIG, start=1):
                result = fpga.send_command(cmd=0x57, addr=addr, data=value)
                if not isinstance(result, dict):
                    failures.append((addr, name, value, result))
                self.update_idletasks()
        except Exception as exc:
            messagebox.showerror("批量配置失败", str(exc))
            return

        if failures:
            self._log("ISP 批量配置完成（仅显示失败项）:")
            for addr, name, value, result in failures:
                self._log(f"{name} @0x{addr:08X} = 0x{value:08X} -> {self._format_result_for_log(result)}")
        else:
            self._log("ISP 批量配置全部成功。")
        self._log("")

    def _parse_manual_csv_row(self, row, require_data=True):
        parts = [str(p).strip() for p in row if str(p).strip()]
        if not parts:
            return None

        first = parts[0].strip().lower()
        if first.startswith("#") or first.startswith("//"):
            return None
        if first in {"addr", "address", "地址"}:
            return None

        addr = parse_int_flexible(parts[0])
        if not (0 <= addr <= 0xFFFFFFFF):
            raise ValueError("地址超出 32-bit 范围")

        if require_data:
            if len(parts) < 2:
                raise ValueError("至少需要地址和数据两列")
            data = parse_int_flexible(parts[-1])
            if not (0 <= data <= 0xFFFFFFFF):
                raise ValueError("数据超出 32-bit 范围")
            return addr, data

        name = parts[1] if len(parts) >= 2 else ""
        return addr, name

    def _import_manual_csv_batch(self):
        file_path = filedialog.askopenfilename(
            title="导入CSV并批量写入（手动页）",
            filetypes=[("CSV 文件", "*.csv"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not file_path:
            return

        try:
            fpga = self._require_fpga_connection()
        except Exception as exc:
            messagebox.showerror("错误", str(exc))
            return

        entries = []
        errors = []
        try:
            with open(file_path, "r", newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                for idx, row in enumerate(reader, start=1):
                    try:
                        parsed = self._parse_manual_csv_row(row, require_data=True)
                        if parsed is None:
                            continue
                        entries.append(parsed)
                    except Exception as exc:
                        errors.append(f"第{idx}行: {exc} | 原文: {row}")
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))
            return

        if errors and not entries:
            show_errors = "\n".join(errors[:8])
            more = f"\n... 还有 {len(errors) - 8} 条错误" if len(errors) > 8 else ""
            messagebox.showerror("CSV 格式错误", show_errors + more)
            return

        if errors and entries:
            show_errors = "\n".join(errors[:6])
            more = f"\n... 还有 {len(errors) - 6} 条错误" if len(errors) > 6 else ""
            if not messagebox.askyesno("部分行解析失败", f"有 {len(errors)} 行无效：\n{show_errors}{more}\n\n仍要写入 {len(entries)} 项吗？"):
                return

        if not entries:
            messagebox.showwarning("提示", "未识别到可写入的数据")
            return

        if not messagebox.askyesno("确认", f"共识别 {len(entries)} 项地址/数据，确定开始批量写入吗？"):
            return

        self._log(f"开始手动页 CSV 批量写入（共 {len(entries)} 项）: {file_path}")
        self.update_idletasks()

        failures = []
        try:
            for addr, data in entries:
                result = fpga.send_command(cmd=0x57, addr=addr, data=data)
                if not isinstance(result, dict):
                    failures.append((addr, data, result))
                self.update_idletasks()
        except Exception as exc:
            messagebox.showerror("批量写入失败", str(exc))
            return

        if failures:
            self._log("手动页 CSV 批量写入完成（仅显示失败项）:")
            for addr, data, result in failures:
                self._log(f"WRITE @0x{addr:08X} DATA=0x{data:08X} -> {self._format_result_for_log(result)}")
        else:
            self._log("手动页 CSV 批量写入全部成功。")
        self._log("")

    def _import_manual_csv_read(self):
        input_path = filedialog.askopenfilename(
            title="导入CSV并批量读取（手动页）",
            filetypes=[("CSV 文件", "*.csv"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not input_path:
            return

        output_path = filedialog.asksaveasfilename(
            title="保存批量读取结果",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        )
        if not output_path:
            return

        try:
            fpga = self._require_fpga_connection()
        except Exception as exc:
            messagebox.showerror("错误", str(exc))
            return

        entries = []
        errors = []
        try:
            with open(input_path, "r", newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                for idx, row in enumerate(reader, start=1):
                    try:
                        parsed = self._parse_manual_csv_row(row, require_data=False)
                        if parsed is None:
                            continue
                        entries.append(parsed)
                    except Exception as exc:
                        errors.append(f"第{idx}行: {exc} | 原文: {row}")
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))
            return

        if errors and not entries:
            show_errors = "\n".join(errors[:8])
            more = f"\n... 还有 {len(errors) - 8} 条错误" if len(errors) > 8 else ""
            messagebox.showerror("CSV 格式错误", show_errors + more)
            return

        if errors and entries:
            show_errors = "\n".join(errors[:6])
            more = f"\n... 还有 {len(errors) - 6} 条错误" if len(errors) > 6 else ""
            if not messagebox.askyesno("部分行解析失败", f"有 {len(errors)} 行无效：\n{show_errors}{more}\n\n仍要读取 {len(entries)} 项吗？"):
                return

        if not entries:
            messagebox.showwarning("提示", "未识别到可读取的地址")
            return

        if not messagebox.askyesno("确认", f"共识别 {len(entries)} 项地址，确定开始批量读取吗？"):
            return

        self._log(f"开始手动页 CSV 批量读取（共 {len(entries)} 项）: {input_path}")
        self.update_idletasks()

        results = []
        failures = []
        try:
            for addr, name in entries:
                result = fpga.send_command(cmd=0x52, addr=addr, data=0)
                if isinstance(result, dict):
                    value = self._extract_data_value(result)
                    results.append((addr, name, value))
                else:
                    failures.append((addr, name, result))
                self.update_idletasks()
        except Exception as exc:
            messagebox.showerror("批量读取失败", str(exc))
            return

        try:
            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["addr", "name", "data"])
                for addr, name, value in results:
                    writer.writerow([f"0x{addr:08X}", name, f"0x{value:08X}"])
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return

        if failures:
            self._log("手动页 CSV 批量读取完成（仅显示失败项）:")
            for addr, name, result in failures:
                tag = name if name else f"0x{addr:08X}"
                self._log(f"READ {tag} @0x{addr:08X} -> {self._format_result_for_log(result)}")
        else:
            self._log("手动页 CSV 批量读取全部成功。")
        self._log(f"批量读取结果已导出: {output_path}")
        self._log("")

    # ---------------- 固定寄存器菜单 ----------------

    def _fixed_read_one(self, row_id):
        try:
            item = self.fixed_row_items[row_id]
            addr = self._resolve_item_addr(item)
            reg_name = self._get_fixed_reg_name(row_id)
            value, result = self._read_register_value(addr)
            self.reg_value_vars[row_id].set(f"0x{value:08X}")
            self._log(f"READ {reg_name} (0x{addr:08X}) -> {self._format_result_for_log(result)}")
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))

    def _fixed_write_one(self, row_id):
        try:
            item = self.fixed_row_items[row_id]
            addr = self._resolve_item_addr(item)
            reg_name = self._get_fixed_reg_name(row_id)
            text = self.reg_value_vars[row_id].get().strip()
            if not text:
                raise ValueError(f"{reg_name} 未输入数据")

            value = parse_int(text)
            if not (0 <= value <= 0xFFFFFFFF):
                raise ValueError("数据超出 32-bit 范围")
            result = self._write_register_value(addr, value)
            self._log(f"WRITE {reg_name} (0x{addr:08X}) = 0x{value:08X} -> {self._format_result_for_log(result)}")
        except Exception as exc:
            messagebox.showerror("写入失败", str(exc))

    def _fixed_read_all(self):
        if not messagebox.askyesno("确认", "确定读取全部固定寄存器吗？"):
            return
        for rid in range(len(self.fixed_row_items)):
            self._fixed_read_one(rid)
            self.update_idletasks()

    def _fixed_write_all(self):
        targets = []
        invalid_items = []
        for rid, item in enumerate(self.fixed_row_items):
            addr = self._resolve_item_addr(item)
            name = item.get("name", f"row_{rid}")
            text = self.reg_value_vars[rid].get().strip()
            if not text:
                continue

            try:
                value = parse_int(text)
                if not (0 <= value <= 0xFFFFFFFF):
                    raise ValueError("超出32位")
                targets.append((rid, addr, name))
            except Exception:
                invalid_items.append((addr, name, text))

        if invalid_items:
            detail = "\n".join([f"{name} (0x{addr:08X}) = {text}" for addr, name, text in invalid_items[:8]])
            more = f"\n... 还有 {len(invalid_items) - 8} 项" if len(invalid_items) > 8 else ""
            messagebox.showerror("输入格式错误", f"以下寄存器值格式无效，请修正后再批量写入：\n{detail}{more}")
            return

        if not targets:
            messagebox.showwarning("提示", "当前没有可写入项。请先在固定寄存器输入框填写数据。")
            return

        confirm_text = f"检测到 {len(targets)} 个有输入值的寄存器。\n确定仅写入这些寄存器吗？"

        if not messagebox.askyesno("确认", confirm_text):
            return

        for rid, _addr, _name in targets:
            self._fixed_write_one(rid)
            self.update_idletasks()

    def _reset_fixed_inputs(self):
        if not messagebox.askyesno("确认", "确定要清空所有固定寄存器输入框吗？"):
            return

        for rid in range(len(self.fixed_row_items)):
            self.reg_value_vars[rid].set("")
        self.imported_fixed_addrs.clear()
        self._log("固定寄存器输入已全部清空。")

    def _export_fixed_csv(self):
        file_path = filedialog.asksaveasfilename(
            title="导出固定寄存器为CSV",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["module", "addr", "name", "bits", "value", "eye_target"])
                for rid, item in enumerate(self.fixed_row_items):
                    addr = self._resolve_item_addr(item)
                    writer.writerow([
                        item.get("module", ""),
                        f"0x{addr:08X}",
                        item.get("name", ""),
                        item.get("bits", "31:0"),
                        self.reg_value_vars[rid].get().strip(),
                        self.eye_target_var.get() if item.get("is_lr") else "",
                    ])
            messagebox.showinfo("成功", f"导出完成: {file_path}")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    def _import_fixed_csv(self):
        file_path = filedialog.askopenfilename(
            title="导入固定寄存器CSV",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        )
        if not file_path:
            return

        loaded = 0
        skipped = 0
        imported_addrs = set()
        try:
            with open(file_path, "r", newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    first = row[0].strip().lower()
                    if first in {"addr", "address"} or first.startswith("#"):
                        continue

                    try:
                        addr = parse_int(row[0])
                        value = parse_int(row[-1])
                    except Exception:
                        skipped += 1
                        continue

                    matched = False
                    for rid, item in enumerate(self.fixed_row_items):
                        if self._resolve_item_addr(item) == addr:
                            self.reg_value_vars[rid].set(f"0x{value:08X}")
                            imported_addrs.add(addr)
                            loaded += 1
                            matched = True
                            break
                    if not matched:
                        skipped += 1

            self.imported_fixed_addrs = imported_addrs
            messagebox.showinfo("导入完成", f"成功加载 {loaded} 项，跳过 {skipped} 项")
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))


if __name__ == "__main__":
    app = FpgaGui()
    app.mainloop()
