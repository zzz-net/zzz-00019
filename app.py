import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from typing import List, Optional
from models import (
    Device, Borrower, BorrowRecord, Accessory,
    DeviceStatus, RecordStatus, UserRole, User, _now_str
)
from business import EquipmentManager, BusinessError


STATUS_COLORS = {
    DeviceStatus.AVAILABLE: "#27ae60",
    DeviceStatus.BORROWED: "#e67e22",
    DeviceStatus.FROZEN: "#c0392b",
    DeviceStatus.INSPECTING: "#2980b9",
    RecordStatus.BORROWED: "#e67e22",
    RecordStatus.INSPECTING: "#2980b9",
    RecordStatus.RETURNED: "#27ae60",
    RecordStatus.FROZEN: "#c0392b",
}


class AccessoryCheckFrame(ttk.LabelFrame):
    def __init__(self, master, accessories: List[Accessory],
                 title: str = "配件核对", read_only: bool = False):
        super().__init__(master, text=title, padding=8)
        self.vars = []
        self._accessories = []
        self._read_only = read_only
        self._build(accessories)

    def _build(self, accessories: List[Accessory]):
        for i, acc in enumerate(accessories):
            acc_copy = Accessory(
                name=acc.name, required=acc.required, present=acc.present
            )
            self._accessories.append(acc_copy)
            var = tk.BooleanVar(value=acc.present)
            self.vars.append(var)
            label_text = f"{acc.name}"
            if acc.required:
                label_text += " 【必备】"
            state = "disabled" if self._read_only else "normal"
            cb = ttk.Checkbutton(self, text=label_text,
                                 variable=var, state=state)
            cb.grid(row=i, column=0, sticky="w", pady=2)

    def get_accessories(self) -> List[Accessory]:
        result = []
        for acc, var in zip(self._accessories, self.vars):
            result.append(Accessory(
                name=acc.name, required=acc.required, present=var.get()
            ))
        return result

    def get_missing_required(self) -> List[str]:
        missing = []
        for acc, var in zip(self._accessories, self.vars):
            if acc.required and not var.get():
                missing.append(acc.name)
        return missing


class DeviceDialog(tk.Toplevel):
    def __init__(self, master, device: Optional[Device] = None):
        super().__init__(master)
        self.title("设备编辑" if device else "新增设备")
        self.geometry("520x480")
        self.resizable(False, False)
        self.device = device
        self.result = None
        self._build()
        self.grab_set()
        self.transient(master)

    def _build(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="设备名称:").grid(row=0, column=0, sticky="e", pady=4)
        self.name_var = tk.StringVar(value=self.device.name if self.device else "")
        ttk.Entry(main, textvariable=self.name_var, width=40).grid(
            row=0, column=1, pady=4, sticky="w")

        ttk.Label(main, text="类别:").grid(row=1, column=0, sticky="e", pady=4)
        self.category_var = tk.StringVar(value=self.device.category if self.device else "")
        ttk.Combobox(main, textvariable=self.category_var, width=37,
                     values=["投影仪", "录音笔", "摄像头", "笔记本电脑", "其他"]
                     ).grid(row=1, column=1, pady=4, sticky="w")

        ttk.Label(main, text="型号:").grid(row=2, column=0, sticky="e", pady=4)
        self.model_var = tk.StringVar(value=self.device.model if self.device else "")
        ttk.Entry(main, textvariable=self.model_var, width=40).grid(
            row=2, column=1, pady=4, sticky="w")

        ttk.Label(main, text="序列号:").grid(row=3, column=0, sticky="e", pady=4)
        self.serial_var = tk.StringVar(value=self.device.serial_no if self.device else "")
        ttk.Entry(main, textvariable=self.serial_var, width=40).grid(
            row=3, column=1, pady=4, sticky="w")

        ttk.Label(main, text="备注:").grid(row=4, column=0, sticky="ne", pady=4)
        self.remark_text = tk.Text(main, width=38, height=4)
        self.remark_text.grid(row=4, column=1, pady=4, sticky="w")
        if self.device and self.device.remark:
            self.remark_text.insert("1.0", self.device.remark)

        ttk.Label(main, text="配件清单:").grid(row=5, column=0, sticky="nw", pady=4)
        acc_frame = ttk.Frame(main)
        acc_frame.grid(row=5, column=1, pady=4, sticky="w")
        self.acc_list_frame = ttk.Frame(acc_frame)
        self.acc_list_frame.pack(fill="x")
        self._accessories = []
        if self.device:
            for a in self.device.accessories:
                self._accessories.append(Accessory(
                    name=a.name, required=a.required, present=a.present
                ))
        self._refresh_acc_list()

        btn_add_acc = ttk.Button(acc_frame, text="添加配件", command=self._add_accessory)
        btn_add_acc.pack(anchor="w", pady=(4, 0))

        btns = ttk.Frame(main)
        btns.grid(row=6, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btns, text="确定", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

    def _refresh_acc_list(self):
        for w in self.acc_list_frame.winfo_children():
            w.destroy()
        for i, acc in enumerate(self._accessories):
            row = ttk.Frame(self.acc_list_frame)
            row.pack(fill="x", pady=1)
            text = f"{acc.name}"
            if acc.required:
                text += " 【必备】"
            ttk.Label(row, text=text, width=35).pack(side="left")
            ttk.Button(row, text="编辑", width=6,
                       command=lambda idx=i: self._edit_accessory(idx)).pack(side="left", padx=2)
            ttk.Button(row, text="删除", width=6,
                       command=lambda idx=i: self._del_accessory(idx)).pack(side="left", padx=2)

    def _add_accessory(self):
        name = simpledialog.askstring("配件名称", "请输入配件名称:", parent=self)
        if not name:
            return
        required = messagebox.askyesno("是否必备", f"【{name}】是否为必备配件?", parent=self)
        self._accessories.append(Accessory(name=name.strip(), required=required, present=True))
        self._refresh_acc_list()

    def _edit_accessory(self, idx):
        acc = self._accessories[idx]
        name = simpledialog.askstring("修改配件", "配件名称:",
                                      initialvalue=acc.name, parent=self)
        if not name:
            return
        required = messagebox.askyesno("是否必备", f"【{name}】是否为必备配件?", parent=self)
        self._accessories[idx] = Accessory(name=name.strip(), required=required, present=True)
        self._refresh_acc_list()

    def _del_accessory(self, idx):
        if messagebox.askyesno("确认", "确定删除该配件?", parent=self):
            del self._accessories[idx]
            self._refresh_acc_list()

    def _ok(self):
        if not self.name_var.get().strip():
            messagebox.showerror("错误", "设备名称不能为空", parent=self)
            return
        self.result = {
            "name": self.name_var.get().strip(),
            "category": self.category_var.get().strip(),
            "model": self.model_var.get().strip(),
            "serial_no": self.serial_var.get().strip(),
            "accessories": list(self._accessories),
            "remark": self.remark_text.get("1.0", "end").strip(),
        }
        self.destroy()


class BorrowerDialog(tk.Toplevel):
    def __init__(self, master, borrower: Optional[Borrower] = None):
        super().__init__(master)
        self.title("借用人编辑" if borrower else "新增借用人")
        self.geometry("400x220")
        self.resizable(False, False)
        self.borrower = borrower
        self.result = None
        self._build()
        self.grab_set()
        self.transient(master)

    def _build(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="姓名:").grid(row=0, column=0, sticky="e", pady=6)
        self.name_var = tk.StringVar(value=self.borrower.name if self.borrower else "")
        ttk.Entry(main, textvariable=self.name_var, width=30).grid(
            row=0, column=1, pady=6)

        ttk.Label(main, text="部门:").grid(row=1, column=0, sticky="e", pady=6)
        self.dept_var = tk.StringVar(value=self.borrower.department if self.borrower else "")
        ttk.Entry(main, textvariable=self.dept_var, width=30).grid(
            row=1, column=1, pady=6)

        ttk.Label(main, text="联系电话:").grid(row=2, column=0, sticky="e", pady=6)
        self.phone_var = tk.StringVar(value=self.borrower.phone if self.borrower else "")
        ttk.Entry(main, textvariable=self.phone_var, width=30).grid(
            row=2, column=1, pady=6)

        btns = ttk.Frame(main)
        btns.grid(row=3, column=0, columnspan=2, pady=(16, 0))
        ttk.Button(btns, text="确定", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

    def _ok(self):
        if not self.name_var.get().strip():
            messagebox.showerror("错误", "姓名不能为空", parent=self)
            return
        self.result = {
            "name": self.name_var.get().strip(),
            "department": self.dept_var.get().strip(),
            "phone": self.phone_var.get().strip(),
        }
        self.destroy()


class BorrowDialog(tk.Toplevel):
    def __init__(self, master, manager: EquipmentManager, device: Device):
        super().__init__(master)
        self.title(f"借出登记 - {device.name}")
        self.geometry("560x520")
        self.resizable(False, False)
        self.manager = manager
        self.device = device
        self.result = None
        self._build()
        self.grab_set()
        self.transient(master)

    def _build(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        info_frame = ttk.LabelFrame(main, text="设备信息", padding=8)
        info_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(info_frame, text=f"名称: {self.device.name}").grid(row=0, column=0, sticky="w")
        ttk.Label(info_frame, text=f"类别: {self.device.category}").grid(row=0, column=1, sticky="w", padx=20)
        ttk.Label(info_frame, text=f"型号: {self.device.model}").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, text=f"序列号: {self.device.serial_no}").grid(row=1, column=1, sticky="w", padx=20, pady=2)

        ttk.Label(main, text="借用人:").pack(anchor="w")
        self.borrower_var = tk.StringVar()
        borrower_values = [f"{b.name} ({b.department})" for b in self.manager.borrowers]
        borrower_combo = ttk.Combobox(main, textvariable=self.borrower_var,
                                      values=borrower_values, state="readonly", width=50)
        borrower_combo.pack(fill="x", pady=(2, 8))
        if self.manager.borrowers:
            borrower_combo.current(0)

        ttk.Label(main, text="预计归还时间 (YYYY-MM-DD HH:MM):").pack(anchor="w")
        self.exp_time_var = tk.StringVar()
        ttk.Entry(main, textvariable=self.exp_time_var, width=55).pack(fill="x", pady=(2, 8))

        self.acc_frame = AccessoryCheckFrame(main, self.device.accessories,
                                             title="借出配件核对（勾选实际存在的配件）")
        self.acc_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(main, text="备注:").pack(anchor="w")
        self.remark_text = tk.Text(main, width=55, height=4)
        self.remark_text.pack(fill="x", pady=(2, 8))

        btns = ttk.Frame(main)
        btns.pack(pady=(4, 0))
        ttk.Button(btns, text="确认借出", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

    def _ok(self):
        if not self.borrower_var.get():
            messagebox.showerror("错误", "请选择借用人", parent=self)
            return
        borrower_name = self.borrower_var.get().split(" (")[0]
        borrower = next((b for b in self.manager.borrowers
                         if b.name == borrower_name), None)
        if not borrower:
            messagebox.showerror("错误", "未找到借用人信息", parent=self)
            return

        missing = self.acc_frame.get_missing_required()
        if missing:
            if not messagebox.askyesno(
                "配件缺失",
                f"缺少必备配件：{', '.join(missing)}\n\n"
                f"是否仍然借出？（不建议）",
                parent=self
            ):
                return

        try:
            record = self.manager.borrow_device(
                device_id=self.device.id,
                borrower_id=borrower.id,
                expected_return_time=self.exp_time_var.get().strip(),
                accessories=self.acc_frame.get_accessories(),
                remark=self.remark_text.get("1.0", "end").strip()
            )
            self.result = record
            messagebox.showinfo("成功", f"借出登记成功！\n记录ID: {record.id}", parent=self)
            self.destroy()
        except BusinessError as e:
            messagebox.showerror("借出失败", str(e), parent=self)


class ReturnDialog(tk.Toplevel):
    def __init__(self, master, manager: EquipmentManager, record: BorrowRecord):
        super().__init__(master)
        self.title(f"归还申请 - {record.device_name}")
        self.geometry("540x460")
        self.resizable(False, False)
        self.manager = manager
        self.record = record
        self.result = None
        self._build()
        self.grab_set()
        self.transient(master)

    def _build(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        info_frame = ttk.LabelFrame(main, text="借用信息", padding=8)
        info_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(info_frame, text=f"设备: {self.record.device_name}").grid(row=0, column=0, sticky="w")
        ttk.Label(info_frame, text=f"借用人: {self.record.borrower_name}").grid(row=0, column=1, sticky="w", padx=20)
        ttk.Label(info_frame, text=f"部门: {self.record.borrower_department}").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, text=f"借出时间: {self.record.borrow_time}").grid(row=1, column=1, sticky="w", padx=20, pady=2)

        ttk.Label(main, text="【借出时配件核对】:").pack(anchor="w")
        AccessoryCheckFrame(main, self.record.accessories_check_out,
                            title="借出时配件状态", read_only=True
                            ).pack(fill="x", pady=(2, 8))

        self.acc_frame = AccessoryCheckFrame(
            main, self.record.accessories_check_out,
            title="归还时配件核对（勾选当前实际存在的配件）"
        )
        self.acc_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(main, text="备注:").pack(anchor="w")
        self.remark_text = tk.Text(main, width=55, height=3)
        self.remark_text.pack(fill="x", pady=(2, 8))

        btns = ttk.Frame(main)
        btns.pack(pady=(4, 0))
        ttk.Button(btns, text="提交归还（待验收）", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

    def _ok(self):
        try:
            record = self.manager.submit_return(
                record_id=self.record.id,
                accessories=self.acc_frame.get_accessories(),
                remark=self.remark_text.get("1.0", "end").strip()
            )
            self.result = record
            messagebox.showinfo(
                "成功",
                "归还申请已提交，等待验收人验收。\n"
                "如缺少必备配件，验收时将进入异常冻结。",
                parent=self
            )
            self.destroy()
        except BusinessError as e:
            messagebox.showerror("提交失败", str(e), parent=self)


class InspectDialog(tk.Toplevel):
    def __init__(self, master, manager: EquipmentManager, record: BorrowRecord):
        super().__init__(master)
        self.title(f"归还验收 - {record.device_name}")
        self.geometry("560x580")
        self.resizable(False, False)
        self.manager = manager
        self.record = record
        self.result = None
        self._build()
        self.grab_set()
        self.transient(master)

    def _build(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        info_frame = ttk.LabelFrame(main, text="借用信息", padding=8)
        info_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(info_frame, text=f"设备: {self.record.device_name}").grid(row=0, column=0, sticky="w")
        ttk.Label(info_frame, text=f"借用人: {self.record.borrower_name}").grid(row=0, column=1, sticky="w", padx=20)
        ttk.Label(info_frame, text=f"借出时间: {self.record.borrow_time}").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, text=f"归还提交人: {self.record.check_in_operator or '未记录'}").grid(
            row=1, column=1, sticky="w", padx=20, pady=2)

        ttk.Label(main, text="【借出时配件】:").pack(anchor="w")
        AccessoryCheckFrame(main, self.record.accessories_check_out,
                            title="借出时配件状态", read_only=True
                            ).pack(fill="x", pady=(2, 6))

        self.acc_frame = AccessoryCheckFrame(
            main,
            self.record.accessories_check_in if self.record.accessories_check_in
            else self.record.accessories_check_out,
            title="验收配件核对（勾选实际归还的配件）"
        )
        self.acc_frame.pack(fill="x", pady=(0, 6))

        tip = ttk.Label(main, text="提示：若勾选缺失必备配件，记录将进入【异常冻结】状态，\n"
                                   "仅管理员或验收人可关闭冻结记录。",
                        foreground="#c0392b")
        tip.pack(anchor="w", pady=(0, 6))

        ttk.Label(main, text="验收备注:").pack(anchor="w")
        self.remark_text = tk.Text(main, width=55, height=4)
        self.remark_text.pack(fill="x", pady=(2, 8))

        btns = ttk.Frame(main)
        btns.pack(pady=(4, 0))
        ttk.Button(btns, text="完成验收", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="强制通过（忽略缺配件）", command=self._force_ok).pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

    def _do_inspect(self, force: bool):
        try:
            record, frozen = self.manager.inspect_return(
                record_id=self.record.id,
                accessories=self.acc_frame.get_accessories(),
                inspect_remark=self.remark_text.get("1.0", "end").strip(),
                force_accept=force
            )
            self.result = record
            if frozen:
                messagebox.showwarning(
                    "验收完成 - 异常冻结",
                    "验收发现缺少必备配件，记录已进入【异常冻结】状态。\n"
                    "设备也同时被冻结，请联系管理员后续处理。",
                    parent=self
                )
            else:
                msg = "验收通过，设备已归还。"
                missing = self.acc_frame.get_missing_required()
                if missing and force:
                    msg += f"\n（已强制接收，缺少：{', '.join(missing)}）"
                messagebox.showinfo("验收完成", msg, parent=self)
            self.destroy()
        except BusinessError as e:
            messagebox.showerror("验收失败", str(e), parent=self)

    def _ok(self):
        self._do_inspect(False)

    def _force_ok(self):
        if messagebox.askyesno("确认强制通过",
                               "确定要忽略缺失的必备配件并强制通过验收吗？",
                               parent=self):
            self._do_inspect(True)


class HistoryDialog(tk.Toplevel):
    def __init__(self, master, record: BorrowRecord):
        super().__init__(master)
        self.title(f"状态历史 - {record.device_name}")
        self.geometry("680x480")
        self.minsize(560, 360)
        self._build(record)
        self.grab_set()
        self.transient(master)

    def _build(self, record: BorrowRecord):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        info_frame = ttk.LabelFrame(main, text="记录概要", padding=8)
        info_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(info_frame, text=f"记录ID: {record.id}").grid(row=0, column=0, sticky="w")
        ttk.Label(info_frame, text=f"当前状态: {record.status}").grid(row=0, column=1, sticky="w", padx=20)
        ttk.Label(info_frame, text=f"设备: {record.device_name}").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, text=f"借用人: {record.borrower_name} ({record.borrower_department})").grid(
            row=1, column=1, sticky="w", padx=20, pady=2)
        ttk.Label(info_frame, text=f"借出时间: {record.borrow_time}").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, text=f"实际归还: {record.actual_return_time or '未归还'}").grid(
            row=2, column=1, sticky="w", padx=20, pady=2)
        if record.remark:
            ttk.Label(info_frame, text=f"备注: {record.remark[:80]}").grid(
                row=3, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Label(main, text="状态变更历史:").pack(anchor="w")
        tree_frame = ttk.Frame(main)
        tree_frame.pack(fill="both", expand=True)
        cols = ("time", "from", "to", "operator", "role", "remark")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=10)
        tree.heading("time", text="时间")
        tree.heading("from", text="原状态")
        tree.heading("to", text="新状态")
        tree.heading("operator", text="操作人")
        tree.heading("role", text="角色")
        tree.heading("remark", text="说明")
        tree.column("time", width=150, anchor="w")
        tree.column("from", width=100, anchor="center")
        tree.column("to", width=100, anchor="center")
        tree.column("operator", width=90, anchor="w")
        tree.column("role", width=80, anchor="center")
        tree.column("remark", width=200, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for h in reversed(record.history):
            tree.insert("", "end", values=(
                h.timestamp, h.from_status, h.to_status,
                h.operator, h.operator_role, h.remark
            ))

        ttk.Button(main, text="关闭", command=self.destroy).pack(pady=(8, 0))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.manager = EquipmentManager()
        self._selected_device_id: Optional[str] = None
        self._selected_record_id: Optional[str] = None
        self._build_ui()
        self._refresh_all()

    def _build_ui(self):
        self.root.title("本地设备借用归还验收管理系统")
        self.root.geometry("1200x760")
        self.root.minsize(960, 640)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        top_bar = ttk.Frame(self.root, padding=8)
        top_bar.pack(fill="x")

        ttk.Label(top_bar, text="当前用户:").pack(side="left")
        self.user_var = tk.StringVar()
        self.user_combo = ttk.Combobox(top_bar, textvariable=self.user_var,
                                       state="readonly", width=30)
        self.user_combo.pack(side="left", padx=(4, 16))
        self.user_combo.bind("<<ComboboxSelected>>", self._on_user_changed)

        self.role_label = ttk.Label(top_bar, text="", foreground="#2980b9")
        self.role_label.pack(side="left")

        ttk.Separator(top_bar, orient="vertical").pack(side="left", fill="y", padx=12)

        ttk.Label(top_bar, text="导出目录:").pack(side="left")
        self.export_dir_var = tk.StringVar()
        ttk.Entry(top_bar, textvariable=self.export_dir_var,
                  width=40, state="readonly").pack(side="left", padx=4)
        ttk.Button(top_bar, text="设置...", command=self._set_export_dir).pack(side="left", padx=4)
        self.export_status_label = ttk.Label(top_bar, text="")
        self.export_status_label.pack(side="left", padx=8)

        main_paned = ttk.Panedwindow(self.root, orient="horizontal")
        main_paned.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        left_frame = ttk.Frame(main_paned)
        right_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=1)
        main_paned.add(right_frame, weight=2)

        self._build_devices_panel(left_frame)
        self._build_records_panel(right_frame)

        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(self.root, textvariable=self.status_var,
                               anchor="w", padding=(8, 4))
        status_bar.pack(fill="x", side="bottom")

    def _build_devices_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="设备管理", padding=6)
        frame.pack(fill="both", expand=True)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(0, 4))
        self.btn_add_device = ttk.Button(btns, text="新增设备", command=self._add_device)
        self.btn_add_device.pack(side="left", padx=2)
        self.btn_edit_device = ttk.Button(btns, text="编辑设备", command=self._edit_device)
        self.btn_edit_device.pack(side="left", padx=2)
        self.btn_del_device = ttk.Button(btns, text="删除设备", command=self._delete_device)
        self.btn_del_device.pack(side="left", padx=2)
        self.btn_freeze_device = ttk.Button(btns, text="冻结", command=self._freeze_device)
        self.btn_freeze_device.pack(side="left", padx=2)
        self.btn_unfreeze_device = ttk.Button(btns, text="解冻", command=self._unfreeze_device)
        self.btn_unfreeze_device.pack(side="left", padx=2)
        self.btn_export_devices = ttk.Button(btns, text="导出", command=self._export_devices)
        self.btn_export_devices.pack(side="right", padx=2)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)
        cols = ("name", "category", "status", "model", "serial")
        self.device_tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        self.device_tree.heading("name", text="名称")
        self.device_tree.heading("category", text="类别")
        self.device_tree.heading("status", text="状态")
        self.device_tree.heading("model", text="型号")
        self.device_tree.heading("serial", text="序列号")
        self.device_tree.column("name", width=180, anchor="w")
        self.device_tree.column("category", width=80, anchor="center")
        self.device_tree.column("status", width=80, anchor="center")
        self.device_tree.column("model", width=110, anchor="w")
        self.device_tree.column("serial", width=120, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=vsb.set)
        self.device_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.device_tree.bind("<<TreeviewSelect>>", self._on_device_selected)

        self.device_tree.tag_configure(DeviceStatus.AVAILABLE,
                                       foreground=STATUS_COLORS[DeviceStatus.AVAILABLE])
        self.device_tree.tag_configure(DeviceStatus.BORROWED,
                                       foreground=STATUS_COLORS[DeviceStatus.BORROWED])
        self.device_tree.tag_configure(DeviceStatus.FROZEN,
                                       foreground=STATUS_COLORS[DeviceStatus.FROZEN])
        self.device_tree.tag_configure(DeviceStatus.INSPECTING,
                                       foreground=STATUS_COLORS[DeviceStatus.INSPECTING])

        self.device_detail = tk.Text(frame, height=7, state="disabled", wrap="word")
        self.device_detail.pack(fill="x", pady=(6, 0))

        borrower_frame = ttk.LabelFrame(parent, text="借用人管理", padding=6)
        borrower_frame.pack(fill="x", pady=(8, 0))
        bbtns = ttk.Frame(borrower_frame)
        bbtns.pack(fill="x", pady=(0, 4))
        self.btn_add_borrower = ttk.Button(bbtns, text="新增借用人", command=self._add_borrower)
        self.btn_add_borrower.pack(side="left", padx=2)

        btree_frame = ttk.Frame(borrower_frame)
        btree_frame.pack(fill="x")
        bcols = ("name", "department", "phone")
        self.borrower_tree = ttk.Treeview(btree_frame, columns=bcols,
                                          show="headings", height=5)
        self.borrower_tree.heading("name", text="姓名")
        self.borrower_tree.heading("department", text="部门")
        self.borrower_tree.heading("phone", text="电话")
        self.borrower_tree.column("name", width=100, anchor="w")
        self.borrower_tree.column("department", width=140, anchor="w")
        self.borrower_tree.column("phone", width=140, anchor="w")
        self.borrower_tree.pack(fill="x")

    def _build_records_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="借用记录", padding=6)
        frame.pack(fill="both", expand=True)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(0, 4))
        self.btn_borrow = ttk.Button(btns, text="借出登记", command=self._borrow_device)
        self.btn_borrow.pack(side="left", padx=2)
        self.btn_return = ttk.Button(btns, text="提交归还", command=self._return_device)
        self.btn_return.pack(side="left", padx=2)
        self.btn_inspect = ttk.Button(btns, text="验收", command=self._inspect_device)
        self.btn_inspect.pack(side="left", padx=2)
        self.btn_close_frozen = ttk.Button(btns, text="关闭冻结", command=self._close_frozen)
        self.btn_close_frozen.pack(side="left", padx=2)
        self.btn_history = ttk.Button(btns, text="查看历史", command=self._view_history)
        self.btn_history.pack(side="left", padx=2)
        self.btn_export_records = ttk.Button(btns, text="导出选中", command=self._export_selected_records)
        self.btn_export_records.pack(side="right", padx=2)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)
        cols = ("id", "device", "borrower", "dept", "borrow_time",
                "exp_return", "status", "operator")
        self.record_tree = ttk.Treeview(tree_frame, columns=cols,
                                        show="headings", selectmode="extended")
        self.record_tree.heading("id", text="记录ID")
        self.record_tree.heading("device", text="设备")
        self.record_tree.heading("borrower", text="借用人")
        self.record_tree.heading("dept", text="部门")
        self.record_tree.heading("borrow_time", text="借出时间")
        self.record_tree.heading("exp_return", text="预计归还")
        self.record_tree.heading("status", text="状态")
        self.record_tree.heading("operator", text="借出操作员")
        self.record_tree.column("id", width=80, anchor="center")
        self.record_tree.column("device", width=200, anchor="w")
        self.record_tree.column("borrower", width=80, anchor="w")
        self.record_tree.column("dept", width=100, anchor="w")
        self.record_tree.column("borrow_time", width=140, anchor="w")
        self.record_tree.column("exp_return", width=140, anchor="w")
        self.record_tree.column("status", width=90, anchor="center")
        self.record_tree.column("operator", width=90, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.record_tree.yview)
        self.record_tree.configure(yscrollcommand=vsb.set)
        self.record_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.record_tree.bind("<<TreeviewSelect>>", self._on_record_selected)

        for s in (RecordStatus.BORROWED, RecordStatus.INSPECTING,
                  RecordStatus.RETURNED, RecordStatus.FROZEN):
            self.record_tree.tag_configure(s, foreground=STATUS_COLORS[s])

    def _refresh_all(self):
        self._refresh_user_combo()
        self._refresh_devices()
        self._refresh_borrowers()
        self._refresh_records()
        self._refresh_export_dir()
        self._apply_permissions()

    def _refresh_user_combo(self):
        values = [f"{u.username} ({u.display_name} - {u.role})" for u in self.manager.users]
        self.user_combo["values"] = values
        if self.manager.current_user:
            u = self.manager.current_user
            idx = next((i for i, v in enumerate(values)
                        if v.startswith(u.username + " ")), -1)
            if idx >= 0:
                self.user_combo.current(idx)
            self.role_label.config(text=f"角色: {u.role}")
        else:
            self.role_label.config(text="")

    def _refresh_devices(self):
        self.device_tree.delete(*self.device_tree.get_children())
        for d in self.manager.devices:
            self.device_tree.insert("", "end", iid=d.id, values=(
                d.name, d.category, d.status, d.model, d.serial_no
            ), tags=(d.status,))
        self._refresh_device_detail()

    def _refresh_borrowers(self):
        self.borrower_tree.delete(*self.borrower_tree.get_children())
        for b in self.manager.borrowers:
            self.borrower_tree.insert("", "end", iid=b.id, values=(
                b.name, b.department, b.phone
            ))

    def _refresh_records(self):
        self.record_tree.delete(*self.record_tree.get_children())
        records = self.manager.get_filtered_records()
        for r in sorted(records, key=lambda x: x.borrow_time, reverse=True):
            self.record_tree.insert("", "end", iid=r.id, values=(
                r.id, r.device_name, r.borrower_name, r.borrower_department,
                r.borrow_time, r.expected_return_time, r.status,
                r.check_out_operator
            ), tags=(r.status,))

    def _refresh_device_detail(self):
        self.device_detail.config(state="normal")
        self.device_detail.delete("1.0", "end")
        device = self.manager.find_device(self._selected_device_id)
        if device:
            lines = [f"设备: {device.name}  ({device.category} / {device.status})",
                     f"型号: {device.model or '-'}    序列号: {device.serial_no or '-'}",
                     f"创建时间: {device.created_at}"]
            if device.accessories:
                acc_strs = []
                for a in device.accessories:
                    flag = "[必备]" if a.required else "[可选]"
                    acc_strs.append(f"{a.name}{flag}")
                lines.append("配件: " + "  |  ".join(acc_strs))
            if device.remark:
                lines.append(f"备注: {device.remark}")
            self.device_detail.insert("1.0", "\n".join(lines))
        self.device_detail.config(state="disabled")

    def _refresh_export_dir(self):
        self.export_dir_var.set(self.manager.config.export_dir)
        if not self.manager.config.export_dir:
            self.export_status_label.config(text="【未设置】", foreground="#c0392b")
        elif self.manager.can_write_to_export_dir():
            self.export_status_label.config(text="【可写】", foreground="#27ae60")
        else:
            self.export_status_label.config(text="【不可写】", foreground="#c0392b")

    def _apply_permissions(self):
        role = self.manager.current_user.role if self.manager.current_user else ""
        perm_map = {
            "add_device": [self.btn_add_device],
            "edit_device": [self.btn_edit_device],
            "delete_device": [self.btn_del_device],
            "add_borrower": [self.btn_add_borrower],
            "borrow_device": [self.btn_borrow],
            "return_device": [self.btn_return],
            "inspect_return": [self.btn_inspect],
            "freeze_device": [self.btn_freeze_device],
            "unfreeze_device": [self.btn_unfreeze_device],
            "close_record": [self.btn_close_frozen],
            "export_data": [self.btn_export_devices, self.btn_export_records],
        }
        for perm, widgets in perm_map.items():
            enabled = self.manager.has_permission(perm)
            for w in widgets:
                w.config(state="normal" if enabled else "disabled")

    def _on_user_changed(self, _event=None):
        value = self.user_var.get()
        if not value:
            return
        username = value.split(" ")[0]
        try:
            self.manager.switch_user(username)
            self._refresh_all()
            u = self.manager.current_user
            self.status_var.set(f"已切换到用户: {u.display_name} ({u.role})")
        except BusinessError as e:
            messagebox.showerror("切换失败", str(e))

    def _on_device_selected(self, _event=None):
        sel = self.device_tree.selection()
        self._selected_device_id = sel[0] if sel else None
        self._refresh_device_detail()

    def _on_record_selected(self, _event=None):
        sel = self.record_tree.selection()
        self._selected_record_id = sel[0] if sel else None

    def _set_export_dir(self):
        initial = self.manager.config.export_dir or os.path.expanduser("~")
        d = filedialog.askdirectory(title="选择导出目录", initialdir=initial)
        if d:
            ok, msg = self.manager.set_export_dir(d)
            if ok:
                messagebox.showinfo("成功", msg)
            else:
                messagebox.showerror("失败", msg)
            self._refresh_export_dir()

    def _check_export_dir(self) -> bool:
        if not self.manager.can_write_to_export_dir():
            messagebox.showerror("导出失败",
                                 f"导出目录不可写：{self.manager.config.export_dir or '未设置'}\n"
                                 f"请先设置一个可写的导出目录。\n"
                                 f"在导出目录可写前，任何导出操作都不会改动选中数据。")
            return False
        return True

    def _add_device(self):
        dlg = DeviceDialog(self.root)
        self.root.wait_window(dlg)
        if dlg.result:
            try:
                self.manager.add_device(**dlg.result)
                self._refresh_devices()
                self.status_var.set("设备已新增")
            except BusinessError as e:
                messagebox.showerror("错误", str(e))

    def _edit_device(self):
        if not self._selected_device_id:
            messagebox.showinfo("提示", "请先选择设备")
            return
        device = self.manager.find_device(self._selected_device_id)
        if not device:
            return
        dlg = DeviceDialog(self.root, device)
        self.root.wait_window(dlg)
        if dlg.result:
            try:
                self.manager.update_device(device.id, **dlg.result)
                self._refresh_devices()
                self.status_var.set("设备已更新")
            except BusinessError as e:
                messagebox.showerror("错误", str(e))

    def _delete_device(self):
        if not self._selected_device_id:
            messagebox.showinfo("提示", "请先选择设备")
            return
        device = self.manager.find_device(self._selected_device_id)
        if not device:
            return
        if not messagebox.askyesno("确认", f"确定删除设备【{device.name}】?"):
            return
        try:
            self.manager.delete_device(device.id)
            self._selected_device_id = None
            self._refresh_devices()
            self.status_var.set("设备已删除")
        except BusinessError as e:
            messagebox.showerror("错误", str(e))

    def _freeze_device(self):
        if not self._selected_device_id:
            messagebox.showinfo("提示", "请先选择设备")
            return
        device = self.manager.find_device(self._selected_device_id)
        if not device:
            return
        reason = simpledialog.askstring("冻结设备", "冻结原因:", parent=self.root)
        try:
            self.manager.freeze_device(device.id, reason or "")
            self._refresh_devices()
            self.status_var.set(f"设备【{device.name}】已冻结")
        except BusinessError as e:
            messagebox.showerror("错误", str(e))

    def _unfreeze_device(self):
        if not self._selected_device_id:
            messagebox.showinfo("提示", "请先选择设备")
            return
        device = self.manager.find_device(self._selected_device_id)
        if not device:
            return
        reason = simpledialog.askstring("解冻设备", "解冻说明:", parent=self.root)
        try:
            self.manager.unfreeze_device(device.id, reason or "")
            self._refresh_devices()
            self.status_var.set(f"设备【{device.name}】已解冻")
        except BusinessError as e:
            messagebox.showerror("错误", str(e))

    def _add_borrower(self):
        dlg = BorrowerDialog(self.root)
        self.root.wait_window(dlg)
        if dlg.result:
            try:
                self.manager.add_borrower(**dlg.result)
                self._refresh_borrowers()
                self.status_var.set("借用人已新增")
            except BusinessError as e:
                messagebox.showerror("错误", str(e))

    def _borrow_device(self):
        if not self._selected_device_id:
            messagebox.showinfo("提示", "请先在左侧选择要借出的设备")
            return
        device = self.manager.find_device(self._selected_device_id)
        if not device:
            return
        if device.status == DeviceStatus.BORROWED:
            messagebox.showerror("错误",
                                 f"设备【{device.name}】已借出，不能再次借出。\n"
                                 f"请先归还后再操作。")
            return
        if device.status == DeviceStatus.FROZEN:
            messagebox.showerror("错误",
                                 f"设备【{device.name}】处于异常冻结状态，不能借出。")
            return
        dlg = BorrowDialog(self.root, self.manager, device)
        self.root.wait_window(dlg)
        if dlg.result:
            self._refresh_devices()
            self._refresh_records()
            self.status_var.set("借出登记完成")

    def _return_device(self):
        if not self._selected_record_id:
            messagebox.showinfo("提示", "请先选择要归还的借用记录")
            return
        record = self.manager.find_record(self._selected_record_id)
        if not record:
            return
        if record.status != RecordStatus.BORROWED:
            messagebox.showerror("错误",
                                 f"当前记录状态为【{record.status}】，无法提交归还。")
            return
        dlg = ReturnDialog(self.root, self.manager, record)
        self.root.wait_window(dlg)
        if dlg.result:
            self._refresh_devices()
            self._refresh_records()
            self.status_var.set("归还已提交，等待验收")

    def _inspect_device(self):
        if not self._selected_record_id:
            messagebox.showinfo("提示", "请先选择要验收的借用记录")
            return
        record = self.manager.find_record(self._selected_record_id)
        if not record:
            return
        if record.status != RecordStatus.INSPECTING:
            messagebox.showerror("错误",
                                 f"当前记录状态为【{record.status}】，无需验收。\n"
                                 f"仅【归还验收中】的记录需要验收。")
            return
        dlg = InspectDialog(self.root, self.manager, record)
        self.root.wait_window(dlg)
        if dlg.result:
            self._refresh_devices()
            self._refresh_records()
            self.status_var.set("验收完成")

    def _close_frozen(self):
        if not self._selected_record_id:
            messagebox.showinfo("提示", "请先选择要关闭的冻结记录")
            return
        record = self.manager.find_record(self._selected_record_id)
        if not record:
            return
        if record.status != RecordStatus.FROZEN:
            messagebox.showerror("错误",
                                 f"当前记录状态为【{record.status}】，只有异常冻结记录可关闭。")
            return
        if (self.manager.current_user and
                self.manager.current_user.role == UserRole.BORROWER):
            messagebox.showerror("错误",
                                 "借用人不能代替验收人关闭冻结记录。\n"
                                 "请联系验收人或管理员处理。")
            return
        if not messagebox.askyesno("确认关闭冻结",
                                   f"确定将记录【{record.id}】标记为已归还并解冻设备吗？\n"
                                   f"设备: {record.device_name}\n"
                                   f"借用人: {record.borrower_name}"):
            return
        remark = simpledialog.askstring("关闭说明", "处理说明:", parent=self.root)
        try:
            self.manager.close_record(record.id, remark or "")
            self._refresh_devices()
            self._refresh_records()
            self.status_var.set("冻结记录已关闭")
        except BusinessError as e:
            messagebox.showerror("错误", str(e))

    def _view_history(self):
        if not self._selected_record_id:
            messagebox.showinfo("提示", "请先选择借用记录")
            return
        record = self.manager.find_record(self._selected_record_id)
        if not record:
            return
        HistoryDialog(self.root, record)

    def _export_devices(self):
        if not self._check_export_dir():
            return
        default_name = f"设备清单_{_now_str().replace(':', '-').replace(' ', '_')}"
        filepath = filedialog.asksaveasfilename(
            title="导出设备清单",
            initialdir=self.manager.config.export_dir,
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV 表格", "*.csv"), ("JSON 数据", "*.json")]
        )
        if not filepath:
            return
        if not filepath.startswith(self.manager.config.export_dir):
            if not messagebox.askyesno("目录不匹配",
                                       f"所选路径不在设置的导出目录下。\n"
                                       f"导出目录: {self.manager.config.export_dir}\n"
                                       f"确定继续导出？"):
                return
        ok, msg = self.manager.export_all_devices(filepath)
        if ok:
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("失败", msg)

    def _export_selected_records(self):
        sel = self.record_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要导出的借用记录（支持多选）")
            return
        if not self._check_export_dir():
            return
        default_name = f"借用记录_{_now_str().replace(':', '-').replace(' ', '_')}"
        filepath = filedialog.asksaveasfilename(
            title="导出选中记录",
            initialdir=self.manager.config.export_dir,
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV 表格", "*.csv"), ("JSON 数据", "*.json")]
        )
        if not filepath:
            return
        if not filepath.startswith(self.manager.config.export_dir):
            if not messagebox.askyesno("目录不匹配",
                                       f"所选路径不在设置的导出目录下。\n"
                                       f"导出目录: {self.manager.config.export_dir}\n"
                                       f"确定继续导出？"):
                return
        ok, msg = self.manager.export_selected_records(list(sel), filepath)
        if ok:
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("失败", msg)


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
