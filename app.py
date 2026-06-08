import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from typing import List, Optional
from datetime import datetime, timedelta
from models import (
    Device, Borrower, BorrowRecord, Accessory,
    DeviceStatus, RecordStatus, UserRole, User, _now_str,
    MaintenanceRecord, InventorySession, InventoryItem,
    InventoryStatus, InventoryItemResult
)
from business import EquipmentManager, BusinessError


STATUS_COLORS = {
    DeviceStatus.AVAILABLE: "#27ae60",
    DeviceStatus.BORROWED: "#e67e22",
    DeviceStatus.FROZEN: "#c0392b",
    DeviceStatus.INSPECTING: "#2980b9",
    DeviceStatus.MAINTENANCE: "#8e44ad",
    RecordStatus.BORROWED: "#e67e22",
    RecordStatus.INSPECTING: "#2980b9",
    RecordStatus.RETURNED: "#27ae60",
    RecordStatus.FROZEN: "#c0392b",
}

MAINTENANCE_STATUS_LABELS = {
    "all": "全部",
    "in_progress": "进行中",
    "cancelled": "已撤销",
}

ALERT_OVERDUE_COLOR = "#c0392b"
ALERT_DUE_SOON_COLOR = "#f39c12"

FILTER_LABELS = {
    "all": "全部",
    "due_soon": "临期",
    "overdue": "逾期",
    "returned": "已归还",
}

INVENTORY_STATUS_LABELS = {
    "all": "全部",
    InventoryStatus.DRAFT: "草稿",
    InventoryStatus.IN_PROGRESS: "进行中",
    InventoryStatus.COMPLETED: "已完成",
}

INVENTORY_RESULT_LABELS = {
    InventoryItemResult.NORMAL: "正常",
    InventoryItemResult.MISSING: "丢失",
    InventoryItemResult.DAMAGED: "损坏",
    InventoryItemResult.LOCATION_WRONG: "位置错误",
    InventoryItemResult.ACCESSORY_MISSING: "配件缺失",
    InventoryItemResult.OTHER: "其他异常",
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

        ttk.Label(main, text="存放点:").grid(row=4, column=0, sticky="e", pady=4)
        self.location_var = tk.StringVar(
            value=self.device.storage_location if self.device else "")
        ttk.Entry(main, textvariable=self.location_var, width=40).grid(
            row=4, column=1, pady=4, sticky="w")

        ttk.Label(main, text="负责人:").grid(row=5, column=0, sticky="e", pady=4)
        self.resp_var = tk.StringVar(
            value=self.device.responsible_person if self.device else "")
        ttk.Entry(main, textvariable=self.resp_var, width=40).grid(
            row=5, column=1, pady=4, sticky="w")

        ttk.Label(main, text="备注:").grid(row=6, column=0, sticky="ne", pady=4)
        self.remark_text = tk.Text(main, width=38, height=3)
        self.remark_text.grid(row=6, column=1, pady=4, sticky="w")
        if self.device and self.device.remark:
            self.remark_text.insert("1.0", self.device.remark)

        ttk.Label(main, text="配件清单:").grid(row=7, column=0, sticky="nw", pady=4)
        acc_frame = ttk.Frame(main)
        acc_frame.grid(row=7, column=1, pady=4, sticky="w")
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
        btns.grid(row=8, column=0, columnspan=2, pady=(12, 0))
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
            "storage_location": self.location_var.get().strip(),
            "responsible_person": self.resp_var.get().strip(),
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


class MaintenanceDialog(tk.Toplevel):
    def __init__(self, master, manager: EquipmentManager, device: Device):
        super().__init__(master)
        self.title(f"送修/保养登记 - {device.name}")
        self.geometry("520x380")
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
        ttk.Label(info_frame, text=f"当前状态: {self.device.status}",
                  foreground=STATUS_COLORS.get(self.device.status, "#000")).grid(
            row=0, column=1, sticky="w", padx=20)
        ttk.Label(info_frame, text=f"型号: {self.device.model or '-'}").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, text=f"序列号: {self.device.serial_no or '-'}").grid(
            row=1, column=1, sticky="w", padx=20, pady=2)

        ttk.Label(main, text="维修/保养原因 *:").pack(anchor="w")
        self.reason_text = tk.Text(main, width=55, height=4)
        self.reason_text.pack(fill="x", pady=(2, 8))

        default_days = self.manager.get_default_maintenance_days()
        default_dt = (datetime.now() + timedelta(days=default_days)).strftime("%Y-%m-%d %H:%M:%S")
        ttk.Label(main, text=f"预计恢复时间 (YYYY-MM-DD HH:MM:SS，默认 {default_days} 天后):").pack(anchor="w")
        self.exp_time_var = tk.StringVar(value=default_dt)
        ttk.Entry(main, textvariable=self.exp_time_var, width=55).pack(fill="x", pady=(2, 8))

        ttk.Label(main, text=f"经办人: {self.manager.current_user.display_name if self.manager.current_user else '-'} "
                             f"({self.manager.current_user.role if self.manager.current_user else ''})").pack(anchor="w")

        btns = ttk.Frame(main)
        btns.pack(pady=(12, 0))
        ttk.Button(btns, text="确认送修", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

    def _ok(self):
        reason = self.reason_text.get("1.0", "end").strip()
        if not reason:
            messagebox.showerror("错误", "请填写维修/保养原因", parent=self)
            return
        try:
            rec, msg = self.manager.send_to_maintenance(
                device_id=self.device.id,
                reason=reason,
                expected_recover_time=self.exp_time_var.get().strip(),
            )
            self.result = rec
            messagebox.showinfo("成功", msg, parent=self)
            self.destroy()
        except BusinessError as e:
            messagebox.showerror("送修失败", str(e), parent=self)


class CancelMaintenanceDialog(tk.Toplevel):
    def __init__(self, master, manager: EquipmentManager, device: Device):
        super().__init__(master)
        self.title(f"撤销维修登记 - {device.name}")
        self.geometry("480x260")
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

        active_m = self.manager.get_active_maintenance_for_device(self.device.id)
        info_frame = ttk.LabelFrame(main, text="当前维修信息", padding=8)
        info_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(info_frame, text=f"设备: {self.device.name}").grid(row=0, column=0, sticky="w")
        ttk.Label(info_frame, text=f"送修前状态: {active_m.from_status if active_m else '-'}").grid(
            row=0, column=1, sticky="w", padx=20)
        if active_m:
            ttk.Label(info_frame, text=f"原因: {active_m.reason[:40]}").grid(row=1, column=0, sticky="w", pady=2, columnspan=2)
            ttk.Label(info_frame, text=f"送修时间: {active_m.start_time}").grid(row=2, column=0, sticky="w", pady=2)
            ttk.Label(info_frame, text=f"经办人: {active_m.operator}").grid(row=2, column=1, sticky="w", padx=20, pady=2)

        can, reason = self.manager.can_cancel_maintenance(self.device.id)
        if not can:
            tip = ttk.Label(main, text=f"⚠ 无法撤销：{reason}", foreground="#c0392b")
            tip.pack(anchor="w", pady=(0, 8))

        ttk.Label(main, text="撤销说明:").pack(anchor="w")
        self.remark_text = tk.Text(main, width=52, height=3)
        self.remark_text.pack(fill="x", pady=(2, 8))

        btns = ttk.Frame(main)
        btns.pack(pady=(8, 0))
        ok_btn = ttk.Button(btns, text="确认撤销", command=self._ok)
        if not can:
            ok_btn.config(state="disabled")
        ok_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

    def _ok(self):
        remark = self.remark_text.get("1.0", "end").strip()
        try:
            rec, msg = self.manager.cancel_last_maintenance(
                device_id=self.device.id,
                remark=remark,
            )
            self.result = rec
            messagebox.showinfo("成功", msg, parent=self)
            self.destroy()
        except BusinessError as e:
            messagebox.showerror("撤销失败", str(e), parent=self)


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


class CreateInventoryDialog(tk.Toplevel):
    def __init__(self, master, manager: EquipmentManager):
        super().__init__(master)
        self.title("新建月度盘点")
        self.geometry("640x560")
        self.resizable(False, False)
        self.manager = manager
        self.result = None
        self._selected_device_ids: List[str] = []
        self._build()
        self.grab_set()
        self.transient(master)
        self._refresh_preview()

    def _build(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="盘点标题 *:").grid(row=0, column=0, sticky="e", pady=6)
        self.title_var = tk.StringVar()
        ttk.Entry(main, textvariable=self.title_var, width=50).grid(
            row=0, column=1, pady=6, sticky="w")

        filter_frame = ttk.LabelFrame(main, text="筛选条件（与手动选择二选一，优先手动选择）", padding=8)
        filter_frame.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 6))

        ttk.Label(filter_frame, text="设备类别:").grid(row=0, column=0, sticky="e", pady=4)
        self.category_var = tk.StringVar()
        categories = self.manager.get_unique_categories()
        ttk.Combobox(filter_frame, textvariable=self.category_var,
                     values=[""] + categories, width=20, state="readonly"
                     ).grid(row=0, column=1, pady=4, sticky="w")

        ttk.Label(filter_frame, text="设备状态:").grid(row=0, column=2, sticky="e", pady=4, padx=(12, 0))
        self.status_var = tk.StringVar(value="全部")
        ttk.Combobox(filter_frame, textvariable=self.status_var, width=12, state="readonly",
                     values=["全部", DeviceStatus.AVAILABLE, DeviceStatus.BORROWED,
                             DeviceStatus.FROZEN, DeviceStatus.INSPECTING, DeviceStatus.MAINTENANCE]
                     ).grid(row=0, column=3, pady=4, sticky="w")

        ttk.Label(filter_frame, text="存放点:").grid(row=1, column=0, sticky="e", pady=4)
        self.location_var = tk.StringVar()
        locations = self.manager.get_unique_storage_locations()
        ttk.Combobox(filter_frame, textvariable=self.location_var,
                     values=[""] + locations, width=20, state="readonly"
                     ).grid(row=1, column=1, pady=4, sticky="w")

        ttk.Label(filter_frame, text="负责人:").grid(row=1, column=2, sticky="e", pady=4, padx=(12, 0))
        self.resp_var = tk.StringVar()
        resps = self.manager.get_unique_responsible_persons()
        ttk.Combobox(filter_frame, textvariable=self.resp_var,
                     values=[""] + resps, width=15, state="readonly"
                     ).grid(row=1, column=3, pady=4, sticky="w")

        ttk.Label(filter_frame, text="关键字:").grid(row=2, column=0, sticky="e", pady=4)
        self.keyword_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self.keyword_var, width=28).grid(
            row=2, column=1, pady=4, sticky="w", columnspan=2)
        ttk.Label(filter_frame, text="（名称/型号/序列号/ID）",
                  foreground="#888").grid(row=2, column=3, sticky="w", padx=(4, 0))

        ttk.Button(filter_frame, text="应用筛选", command=self._on_apply_filter
                   ).grid(row=3, column=0, pady=(6, 0), sticky="w")
        ttk.Button(filter_frame, text="重置筛选", command=self._on_reset_filter
                   ).grid(row=3, column=1, pady=(6, 0), sticky="w", padx=4)
        self.filter_count_label = ttk.Label(filter_frame, text="", foreground="#2980b9")
        self.filter_count_label.grid(row=3, column=2, columnspan=2, pady=(6, 0), sticky="w")

        manual_frame = ttk.LabelFrame(main, text="手动选择设备（勾选后将忽略上方筛选）", padding=8)
        manual_frame.grid(row=2, column=0, columnspan=2, sticky="we", pady=(8, 6))

        self.use_manual_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(manual_frame, text="使用手动选择", variable=self.use_manual_var,
                        command=self._on_manual_toggle).grid(row=0, column=0, sticky="w")

        tree_frame = ttk.Frame(manual_frame)
        tree_frame.grid(row=1, column=0, columnspan=2, sticky="we", pady=(4, 0))
        cols = ("id", "name", "category", "status")
        self.device_select_tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", height=6, selectmode="extended",
        )
        self.device_select_tree.heading("id", text="设备ID")
        self.device_select_tree.heading("name", text="名称")
        self.device_select_tree.heading("category", text="类别")
        self.device_select_tree.heading("status", text="状态")
        self.device_select_tree.column("id", width=90, anchor="center")
        self.device_select_tree.column("name", width=240, anchor="w")
        self.device_select_tree.column("category", width=80, anchor="center")
        self.device_select_tree.column("status", width=80, anchor="center")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.device_select_tree.yview)
        self.device_select_tree.configure(yscrollcommand=vsb.set)
        self.device_select_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.device_select_tree.bind("<<TreeviewSelect>>", self._on_device_manual_select)
        self.device_select_tree.configure(state="disabled")

        for d in sorted(self.manager.devices, key=lambda x: x.name):
            self.device_select_tree.insert("", "end", iid=d.id, values=(
                d.id, d.name, d.category, d.status
            ), tags=(d.status,))

        self.manual_count_label = ttk.Label(manual_frame, text="", foreground="#2980b9")
        self.manual_count_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(main, text="备注:").grid(row=3, column=0, sticky="ne", pady=6)
        self.remark_text = tk.Text(main, width=55, height=3)
        self.remark_text.grid(row=3, column=1, pady=6, sticky="w")

        self.preview_label = ttk.Label(main, text="", foreground="#2980b9")
        self.preview_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        btns = ttk.Frame(main)
        btns.grid(row=5, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btns, text="创建盘点", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

    def _on_manual_toggle(self):
        if self.use_manual_var.get():
            self.device_select_tree.configure(state="normal")
        else:
            self.device_select_tree.configure(state="disabled")
            self._selected_device_ids = []
        self._refresh_preview()

    def _on_device_manual_select(self, _event=None):
        self._selected_device_ids = list(self.device_select_tree.selection())
        self.manual_count_label.config(text=f"已手动选择 {len(self._selected_device_ids)} 台设备")
        self._refresh_preview()

    def _on_apply_filter(self):
        self._refresh_preview()

    def _on_reset_filter(self):
        self.category_var.set("")
        self.status_var.set("全部")
        self.location_var.set("")
        self.resp_var.set("")
        self.keyword_var.set("")
        self._refresh_preview()

    def _count_filtered_devices(self) -> int:
        category = self.category_var.get().strip()
        status_filter = self.status_var.get().strip()
        status_val = "" if status_filter == "全部" else status_filter
        keyword = self.keyword_var.get().strip()
        storage_location = self.location_var.get().strip()
        responsible_person = self.resp_var.get().strip()
        filtered = self.manager._filter_devices_for_inventory(
            category, status_val, keyword, storage_location, responsible_person
        )
        return len(filtered)

    def _refresh_preview(self):
        if self.use_manual_var.get():
            n = len(self._selected_device_ids)
            self.filter_count_label.config(text="")
            self.preview_label.config(
                text=f"将创建包含 {n} 台设备的盘点（手动选择）" if n > 0
                else "请勾选要盘点的设备"
            )
        else:
            n = self._count_filtered_devices()
            self.filter_count_label.config(text=f"当前筛选匹配 {n} 台设备")
            self.preview_label.config(
                text=f"将创建包含 {n} 台设备的盘点（按筛选条件）" if n > 0
                else "当前筛选条件下没有匹配的设备"
            )

    def _ok(self):
        title = self.title_var.get().strip()
        if not title:
            messagebox.showerror("错误", "请填写盘点标题", parent=self)
            return

        if self.use_manual_var.get():
            if not self._selected_device_ids:
                messagebox.showerror("错误", "请至少勾选一台设备", parent=self)
                return
            device_ids = self._selected_device_ids
        else:
            n = self._count_filtered_devices()
            if n == 0:
                messagebox.showerror("错误", "当前筛选条件下没有匹配的设备", parent=self)
                return
            device_ids = None

        try:
            session = self.manager.create_inventory(
                title=title,
                category=self.category_var.get().strip(),
                status_filter="" if self.status_var.get().strip() == "全部" else self.status_var.get().strip(),
                keyword=self.keyword_var.get().strip(),
                storage_location=self.location_var.get().strip(),
                responsible_person=self.resp_var.get().strip(),
                device_ids=device_ids,
                remark=self.remark_text.get("1.0", "end").strip(),
            )
            self.result = session
            messagebox.showinfo("成功", f"盘点已创建：{session.title}\n共 {len(session.items)} 台设备", parent=self)
            self.destroy()
        except BusinessError as e:
            messagebox.showerror("创建失败", str(e), parent=self)


class FillInventoryItemDialog(tk.Toplevel):
    def __init__(self, master, manager: EquipmentManager,
                 session: InventorySession, item: InventoryItem):
        super().__init__(master)
        self.title(f"盘点填写 - {item.device_name}")
        self.geometry("560x520")
        self.resizable(False, False)
        self.manager = manager
        self.session = session
        self.item = item
        self.result = None
        self._device = manager.find_device(item.device_id)
        self._build()
        self.grab_set()
        self.transient(master)

    def _build(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        user_role = self.manager.current_user.role if self.manager.current_user else ""
        is_inspector = user_role == UserRole.INSPECTOR

        info_frame = ttk.LabelFrame(main, text="设备信息", padding=8)
        info_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(info_frame, text=f"设备ID: {self.item.device_id}").grid(row=0, column=0, sticky="w")
        ttk.Label(info_frame, text=f"名称: {self.item.device_name}").grid(row=0, column=1, sticky="w", padx=20)
        ttk.Label(info_frame, text=f"系统原状态: {self.item.original_status}",
                  foreground=STATUS_COLORS.get(self.item.original_status, "#000")).grid(
            row=1, column=0, sticky="w", pady=2)
        if self._device:
            ttk.Label(info_frame, text=f"类别: {self._device.category}").grid(row=1, column=1, sticky="w", padx=20, pady=2)
        if is_inspector:
            ttk.Label(info_frame, text="【验收账号】仅可填写实物情况、位置和备注",
                      foreground="#2980b9").grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        has_conflict, conflict_msg = self.manager._has_device_active_business(self.item.device_id)
        if has_conflict:
            tip = ttk.Label(main, text=f"⚠ 状态冲突：{conflict_msg}\n盘点中不能覆盖正在进行的业务状态，请保持实际状态与系统原状态一致。",
                            foreground="#c0392b", wraplength=520, justify="left")
            tip.pack(fill="x", pady=(0, 8))

        ttk.Label(main, text="实际状态:").pack(anchor="w")
        self.actual_status_var = tk.StringVar(value=self.item.actual_status or self.item.original_status)
        status_combo = ttk.Combobox(main, textvariable=self.actual_status_var,
                                    state="readonly", width=30,
                                    values=[DeviceStatus.AVAILABLE, DeviceStatus.BORROWED,
                                            DeviceStatus.FROZEN, DeviceStatus.INSPECTING,
                                            DeviceStatus.MAINTENANCE])
        status_combo.pack(fill="x", pady=(2, 8))
        if has_conflict:
            status_combo.configure(state="disabled")

        ttk.Label(main, text="实际存放位置:").pack(anchor="w")
        self.location_var = tk.StringVar(value=self.item.actual_location or "")
        ttk.Entry(main, textvariable=self.location_var, width=55).pack(fill="x", pady=(2, 8))

        if self._device and self._device.accessories:
            if is_inspector:
                acc_label = ttk.Label(main, text="缺失配件（验收账号不可修改）:")
            else:
                acc_label = ttk.Label(main, text="缺失配件（勾选缺失的）:")
            acc_label.pack(anchor="w")
            acc_frame = ttk.LabelFrame(main, text="配件核对", padding=6)
            acc_frame.pack(fill="x", pady=(2, 8))
            self._acc_vars = {}
            for i, acc in enumerate(self._device.accessories):
                var = tk.BooleanVar(
                    value=acc.name in (self.item.missing_accessories or [])
                )
                self._acc_vars[acc.name] = var
                label_text = f"{acc.name}"
                if acc.required:
                    label_text += " 【必备】"
                cb = ttk.Checkbutton(acc_frame, text=label_text, variable=var)
                cb.grid(row=i, column=0, sticky="w", pady=1)
                if is_inspector:
                    cb.configure(state="disabled")
        else:
            self._acc_vars = {}

        if is_inspector:
            result_label = ttk.Label(main, text="盘点结果（验收账号不可修改，由系统根据填写内容自动判定）:")
        else:
            result_label = ttk.Label(main, text="盘点结果:")
        result_label.pack(anchor="w")
        self.result_var = tk.StringVar(
            value=self.item.inventory_result or InventoryItemResult.NORMAL
        )
        result_combo = ttk.Combobox(main, textvariable=self.result_var,
                                    state="readonly", width=30,
                                    values=InventoryItemResult.ALL_RESULTS)
        result_combo.pack(fill="x", pady=(2, 8))
        if is_inspector:
            result_combo.configure(state="disabled")

        ttk.Label(main, text="备注:").pack(anchor="w")
        self.remark_text = tk.Text(main, width=55, height=3)
        self.remark_text.pack(fill="x", pady=(2, 8))
        if self.item.remark:
            self.remark_text.insert("1.0", self.item.remark)

        btns = ttk.Frame(main)
        btns.pack(pady=(8, 0))
        ttk.Button(btns, text="保存", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

    def _ok(self):
        user_role = self.manager.current_user.role if self.manager.current_user else ""
        is_inspector = user_role == UserRole.INSPECTOR

        if is_inspector:
            missing = list(self.item.missing_accessories or [])
            actual_status = self.actual_status_var.get().strip()
            actual_location = self.location_var.get().strip()

            has_conflict, _ = self.manager._has_device_active_business(self.item.device_id)
            orig_status = self.item.original_status
            orig_location = self._device.storage_location if self._device else ""
            orig_missing = list(self.item.missing_accessories or [])

            result_type = InventoryItemResult.NORMAL
            if not has_conflict and actual_status != orig_status:
                if actual_status in (DeviceStatus.FROZEN, DeviceStatus.MAINTENANCE):
                    result_type = InventoryItemResult.DAMAGED
                elif actual_status == DeviceStatus.BORROWED:
                    result_type = InventoryItemResult.LOST
            if orig_location and actual_location and actual_location != orig_location:
                result_type = InventoryItemResult.WRONG_LOCATION
            if missing and len(missing) > len(orig_missing):
                result_type = InventoryItemResult.MISSING_ACCESSORY
        else:
            missing = [name for name, var in self._acc_vars.items() if var.get()]
            result_type = self.result_var.get().strip()

        try:
            item = self.manager.fill_inventory_item(
                session_id=self.session.id,
                device_id=self.item.device_id,
                actual_status=self.actual_status_var.get().strip(),
                actual_location=self.location_var.get().strip(),
                missing_accessories=missing,
                inventory_result=result_type,
                remark=self.remark_text.get("1.0", "end").strip(),
            )
            self.result = item
            messagebox.showinfo("成功", f"已保存盘点结果：{item.inventory_result}", parent=self)
            self.destroy()
        except BusinessError as e:
            messagebox.showerror("保存失败", str(e), parent=self)


class InventoryDetailDialog(tk.Toplevel):
    def __init__(self, master, manager: EquipmentManager, session: InventorySession):
        super().__init__(master)
        self.title(f"盘点详情 - {session.title}")
        self.geometry("960x680")
        self.minsize(800, 560)
        self.manager = manager
        self.session = session
        self._build()
        self.grab_set()
        self.transient(master)

    def _build(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        info_frame = ttk.LabelFrame(main, text="盘点概要", padding=8)
        info_frame.pack(fill="x", pady=(0, 8))
        s = self.session
        ttk.Label(info_frame, text=f"标题: {s.title}").grid(row=0, column=0, sticky="w")
        status_color = "#27ae60" if s.status == InventoryStatus.COMPLETED else (
            "#e67e22" if s.status == InventoryStatus.IN_PROGRESS else "#888")
        ttk.Label(info_frame, text=f"状态: {s.status}", foreground=status_color).grid(
            row=0, column=1, sticky="w", padx=20)
        ttk.Label(info_frame, text=f"盘点ID: {s.id}").grid(row=0, column=2, sticky="w", padx=20)

        progress = self.manager.get_inventory_progress(s)
        ttk.Label(info_frame, text=f"创建人: {s.created_by} ({s.created_by_role})").grid(
            row=1, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, text=f"创建时间: {s.created_at}").grid(
            row=1, column=1, sticky="w", padx=20, pady=2)
        if s.completed_at:
            ttk.Label(info_frame, text=f"完成时间: {s.completed_at}").grid(
                row=1, column=2, sticky="w", padx=20, pady=2)
            ttk.Label(info_frame, text=f"完成人: {s.completed_by} ({s.completed_by_role})").grid(
                row=2, column=0, sticky="w", pady=2)

        progress_text = (f"进度: {progress['filled']}/{progress['total']} "
                         f"({progress['percent']}%)  正常: {progress['normal']}  "
                         f"异常: {progress['exception']}  剩余: {progress['remaining']}")
        ex_count = progress["exception"]
        ttk.Label(info_frame, text=progress_text,
                  foreground="#c0392b" if ex_count > 0 else "#27ae60").grid(
            row=2, column=1, columnspan=2, sticky="w", padx=20, pady=2)

        if s.filter_conditions:
            fc = s.filter_conditions
            parts = []
            if fc.get("category"):
                parts.append(f"类别={fc['category']}")
            if fc.get("status_filter"):
                parts.append(f"状态={fc['status_filter']}")
            if fc.get("storage_location"):
                parts.append(f"存放点={fc['storage_location']}")
            if fc.get("responsible_person"):
                parts.append(f"负责人={fc['responsible_person']}")
            if fc.get("keyword"):
                parts.append(f"关键字={fc['keyword']}")
            fc_str = "  ".join(parts) if parts else str(fc)
            ttk.Label(info_frame, text=f"筛选条件: {fc_str}").grid(
                row=3, column=0, columnspan=3, sticky="w", pady=2)
        if s.remark:
            ttk.Label(info_frame, text=f"备注: {s.remark[:100]}").grid(
                row=4, column=0, columnspan=3, sticky="w", pady=2)

        nb = ttk.Notebook(main)
        nb.pack(fill="both", expand=True, pady=(4, 0))

        summary_tab = ttk.Frame(nb)
        diff_tab = ttk.Frame(nb)
        items_tab = ttk.Frame(nb)
        nb.add(summary_tab, text="异常汇总")
        nb.add(diff_tab, text="差异明细")
        nb.add(items_tab, text="全部明细")

        self._build_summary_tab(summary_tab)
        self._build_diff_tab(diff_tab)
        self._build_items_tab(items_tab)

        btns = ttk.Frame(main)
        btns.pack(pady=(10, 0))
        if self.manager.has_permission("export_inventory") and s.status == InventoryStatus.COMPLETED:
            self.btn_export_csv = ttk.Button(btns, text="导出 CSV",
                                             command=lambda: self._do_export("csv"))
            self.btn_export_csv.pack(side="left", padx=4)
            self.btn_export_json = ttk.Button(btns, text="导出 JSON",
                                              command=lambda: self._do_export("json"))
            self.btn_export_json.pack(side="left", padx=4)
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="left", padx=6)

    def _build_summary_tab(self, parent):
        summary = self.manager.get_inventory_exception_summary(self.session)

        top_frame = ttk.Frame(parent, padding=8)
        top_frame.pack(fill="x")
        total_items = len(self.session.items)
        filled = sum(1 for it in self.session.items if it.inventory_result)
        ttk.Label(top_frame,
                  text=f"总计: {total_items} 台  已盘点: {filled} 台  "
                       f"异常: {summary.get('__total__', 0)} 台",
                  font=("", 10, "bold")).pack(side="left")

        tree_frame = ttk.Frame(parent, padding=8)
        tree_frame.pack(fill="both", expand=True)
        cols = ("result_type", "count", "devices")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        tree.heading("result_type", text="异常类型")
        tree.heading("count", text="数量")
        tree.heading("devices", text="涉及设备")
        tree.column("result_type", width=120, anchor="center")
        tree.column("count", width=60, anchor="center")
        tree.column("devices", width=600, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        display_order = [
            InventoryItemResult.LOST,
            InventoryItemResult.DAMAGED,
            InventoryItemResult.WRONG_LOCATION,
            InventoryItemResult.MISSING_ACCESSORY,
            InventoryItemResult.OTHER,
        ]
        for rtype in display_order:
            info = summary.get(rtype)
            if info and info["count"] > 0:
                tree.insert("", "end", values=(
                    rtype, info["count"],
                    "; ".join(f"{d['device_name']}({d['device_id']})" for d in info["devices"])
                ))

        if not any(summary.get(r, {}).get("count", 0) > 0 for r in display_order):
            tree.insert("", "end", values=("无异常", 0, "所有设备盘点正常"))

    def _build_diff_tab(self, parent):
        diffs = self.manager.get_inventory_diff_details(self.session)

        tree_frame = ttk.Frame(parent, padding=8)
        tree_frame.pack(fill="both", expand=True)
        cols = ("device_id", "device_name", "field", "original", "actual", "remark")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        tree.heading("device_id", text="设备ID")
        tree.heading("device_name", text="设备名称")
        tree.heading("field", text="差异项")
        tree.heading("original", text="原值")
        tree.heading("actual", text="实际值")
        tree.heading("remark", text="备注")
        tree.column("device_id", width=80, anchor="center")
        tree.column("device_name", width=150, anchor="w")
        tree.column("field", width=100, anchor="center")
        tree.column("original", width=140, anchor="w")
        tree.column("actual", width=140, anchor="w")
        tree.column("remark", width=250, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        tree.tag_configure("diff", background="#fdecea", foreground="#c0392b")

        if not diffs:
            tree.insert("", "end", values=("-", "无差异", "-", "-", "-",
                                            "所有设备状态、位置、配件均与系统一致"))
        for d in diffs:
            tree.insert("", "end", values=(
                d["device_id"], d["device_name"],
                d["field"], d["original"], d["actual"],
                d.get("remark", "")
            ), tags=("diff",))

    def _build_items_tab(self, parent):
        tree_frame = ttk.Frame(parent, padding=8)
        tree_frame.pack(fill="both", expand=True)
        cols = ("device_id", "device_name", "original_status", "actual_status",
                "location", "missing_acc", "result", "filled_by", "filled_at")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        tree.heading("device_id", text="设备ID")
        tree.heading("device_name", text="设备名称")
        tree.heading("original_status", text="系统原状态")
        tree.heading("actual_status", text="实际状态")
        tree.heading("location", text="实际位置")
        tree.heading("missing_acc", text="缺失配件")
        tree.heading("result", text="盘点结果")
        tree.heading("filled_by", text="填写人")
        tree.heading("filled_at", text="填写时间")
        tree.column("device_id", width=70, anchor="center")
        tree.column("device_name", width=140, anchor="w")
        tree.column("original_status", width=80, anchor="center")
        tree.column("actual_status", width=80, anchor="center")
        tree.column("location", width=90, anchor="w")
        tree.column("missing_acc", width=120, anchor="w")
        tree.column("result", width=80, anchor="center")
        tree.column("filled_by", width=70, anchor="w")
        tree.column("filled_at", width=130, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for it in self.session.items:
            tree.insert("", "end", values=(
                it.device_id, it.device_name, it.original_status,
                it.actual_status or "-", it.actual_location or "-",
                "; ".join(it.missing_accessories) if it.missing_accessories else "-",
                it.inventory_result or "未填写",
                it.filled_by or "-", it.filled_at or "-"
            ), tags=("exception" if it.inventory_result != InventoryItemResult.NORMAL and it.inventory_result else "normal",))

        tree.tag_configure("exception", foreground="#c0392b", background="#fdecea")

    def _do_export(self, fmt: str):
        if not self.manager.check_export_dir_detail()[0]:
            messagebox.showerror("导出失败", "请先在主界面设置导出目录。", parent=self)
            return
        default_name = f"盘点_{self.session.title}_{_now_str().replace(':', '-').replace(' ', '_')}"
        ext = f".{fmt}"
        filepath = filedialog.asksaveasfilename(
            title=f"导出盘点结果为 {fmt.upper()}",
            initialdir=self.manager.config.export_dir,
            initialfile=default_name + ext,
            defaultextension=ext,
            filetypes=[(f"{fmt.upper()} 文件", ext)]
        )
        if not filepath:
            return
        ok, msg = self.manager.export_inventory_session(self.session.id, filepath)
        if ok:
            ex_count = self.manager.get_inventory_exception_count(self.session)
            messagebox.showinfo("成功", f"{msg}\n\n共 {len(self.session.items)} 台设备，异常 {ex_count} 台",
                                parent=self)
        else:
            messagebox.showerror("失败", msg, parent=self)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.manager = EquipmentManager()
        self._selected_device_id: Optional[str] = None
        self._selected_record_id: Optional[str] = None
        self._current_alert_filter: str = "all"
        self._preserved_record_selection: List[str] = []
        self._selected_maintenance_ids: List[str] = []
        self._maint_filter_device: str = ""
        self._maint_filter_status: str = "all"
        self._maint_filter_start_from: str = ""
        self._maint_filter_start_to: str = ""
        self._selected_inventory_id: Optional[str] = None
        self._selected_inventory_item_device_id: Optional[str] = None
        self._inventory_filter_status: str = "all"
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

        self.right_notebook = ttk.Notebook(right_frame)
        self.right_notebook.pack(fill="both", expand=True)

        records_tab = ttk.Frame(self.right_notebook)
        inventory_tab = ttk.Frame(self.right_notebook)
        self.right_notebook.add(records_tab, text="借用记录")
        self.right_notebook.add(inventory_tab, text="盘点工作台")

        self._build_records_panel(records_tab)
        self._build_inventory_panel(inventory_tab)
        self._build_maintenance_panel(left_frame)

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
        self.btn_send_maintenance = ttk.Button(btns, text="送修/保养", command=self._send_to_maintenance)
        self.btn_send_maintenance.pack(side="left", padx=2)
        self.btn_cancel_maintenance = ttk.Button(btns, text="撤销送修", command=self._cancel_maintenance)
        self.btn_cancel_maintenance.pack(side="left", padx=2)
        self.btn_export_devices = ttk.Button(btns, text="导出", command=self._export_devices)
        self.btn_export_devices.pack(side="right", padx=2)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)
        cols = ("name", "category", "status", "location", "resp", "model", "serial")
        self.device_tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        self.device_tree.heading("name", text="名称")
        self.device_tree.heading("category", text="类别")
        self.device_tree.heading("status", text="状态")
        self.device_tree.heading("location", text="存放点")
        self.device_tree.heading("resp", text="负责人")
        self.device_tree.heading("model", text="型号")
        self.device_tree.heading("serial", text="序列号")
        self.device_tree.column("name", width=170, anchor="w")
        self.device_tree.column("category", width=60, anchor="center")
        self.device_tree.column("status", width=70, anchor="center")
        self.device_tree.column("location", width=110, anchor="w")
        self.device_tree.column("resp", width=60, anchor="center")
        self.device_tree.column("model", width=100, anchor="w")
        self.device_tree.column("serial", width=110, anchor="w")
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
        self.device_tree.tag_configure(DeviceStatus.MAINTENANCE,
                                       foreground=STATUS_COLORS[DeviceStatus.MAINTENANCE],
                                       background="#f4ecf7")

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

    def _build_maintenance_panel(self, parent):
        maint_frame = ttk.LabelFrame(parent, text="维修/保养记录", padding=6)
        maint_frame.pack(fill="both", expand=True, pady=(8, 0))

        filter_row = ttk.Frame(maint_frame)
        filter_row.pack(fill="x", pady=(0, 4))

        ttk.Label(filter_row, text="设备ID:").pack(side="left", padx=(0, 2))
        self.maint_device_var = tk.StringVar()
        ttk.Entry(filter_row, textvariable=self.maint_device_var, width=12).pack(side="left", padx=(0, 6))

        ttk.Label(filter_row, text="状态:").pack(side="left", padx=(0, 2))
        self.maint_status_var = tk.StringVar(value=MAINTENANCE_STATUS_LABELS["all"])
        maint_status_combo = ttk.Combobox(
            filter_row, textvariable=self.maint_status_var, width=8, state="readonly",
            values=list(MAINTENANCE_STATUS_LABELS.values())
        )
        maint_status_combo.pack(side="left", padx=(0, 6))

        ttk.Label(filter_row, text="开始时间起:").pack(side="left", padx=(0, 2))
        self.maint_from_var = tk.StringVar()
        ttk.Entry(filter_row, textvariable=self.maint_from_var, width=16).pack(side="left", padx=(0, 6))

        ttk.Label(filter_row, text="至:").pack(side="left", padx=(0, 2))
        self.maint_to_var = tk.StringVar()
        ttk.Entry(filter_row, textvariable=self.maint_to_var, width=16).pack(side="left", padx=(0, 6))

        self.btn_maint_apply = ttk.Button(filter_row, text="应用筛选",
                                          command=self._on_maint_filter_apply)
        self.btn_maint_apply.pack(side="left", padx=2)
        self.btn_maint_reset = ttk.Button(filter_row, text="重置",
                                          command=self._on_maint_filter_reset)
        self.btn_maint_reset.pack(side="left", padx=2)
        self.btn_maint_export = ttk.Button(filter_row, text="导出选中",
                                           command=self._export_maintenance_logs)
        self.btn_maint_export.pack(side="right", padx=2)

        self.maint_status_label = ttk.Label(filter_row, text="", foreground="#2980b9")
        self.maint_status_label.pack(side="right", padx=6)

        mtree_frame = ttk.Frame(maint_frame)
        mtree_frame.pack(fill="both", expand=True)
        mcols = ("id", "device", "device_name", "from_status", "reason",
                 "exp_recover", "start_time", "status", "operator")
        self.maint_tree = ttk.Treeview(mtree_frame, columns=mcols,
                                       show="headings", height=7, selectmode="extended")
        self.maint_tree.heading("id", text="记录ID")
        self.maint_tree.heading("device", text="设备ID")
        self.maint_tree.heading("device_name", text="设备名称")
        self.maint_tree.heading("from_status", text="送修前状态")
        self.maint_tree.heading("reason", text="维修原因")
        self.maint_tree.heading("exp_recover", text="预计恢复")
        self.maint_tree.heading("start_time", text="送修时间")
        self.maint_tree.heading("status", text="状态")
        self.maint_tree.heading("operator", text="经办人")
        self.maint_tree.column("id", width=80, anchor="center")
        self.maint_tree.column("device", width=80, anchor="center")
        self.maint_tree.column("device_name", width=150, anchor="w")
        self.maint_tree.column("from_status", width=80, anchor="center")
        self.maint_tree.column("reason", width=160, anchor="w")
        self.maint_tree.column("exp_recover", width=130, anchor="w")
        self.maint_tree.column("start_time", width=140, anchor="w")
        self.maint_tree.column("status", width=70, anchor="center")
        self.maint_tree.column("operator", width=80, anchor="w")
        mvsb = ttk.Scrollbar(mtree_frame, orient="vertical", command=self.maint_tree.yview)
        self.maint_tree.configure(yscrollcommand=mvsb.set)
        self.maint_tree.pack(side="left", fill="both", expand=True)
        mvsb.pack(side="right", fill="y")
        self.maint_tree.bind("<<TreeviewSelect>>", self._on_maint_selected)

        self.maint_tree.tag_configure("in_progress", foreground=STATUS_COLORS[DeviceStatus.MAINTENANCE])
        self.maint_tree.tag_configure("cancelled", foreground="#7f8c8d")

    def _build_inventory_panel(self, parent):
        inv_frame = ttk.LabelFrame(parent, text="月度盘点", padding=6)
        inv_frame.pack(fill="both", expand=True, pady=(8, 0))

        filter_row = ttk.Frame(inv_frame)
        filter_row.pack(fill="x", pady=(0, 4))

        ttk.Label(filter_row, text="盘点状态:").pack(side="left", padx=(0, 2))
        self.inv_status_var = tk.StringVar(value=INVENTORY_STATUS_LABELS["all"])
        inv_status_combo = ttk.Combobox(
            filter_row, textvariable=self.inv_status_var, width=10, state="readonly",
            values=list(INVENTORY_STATUS_LABELS.values())
        )
        inv_status_combo.pack(side="left", padx=(0, 6))

        self.btn_inv_apply = ttk.Button(filter_row, text="应用筛选",
                                        command=self._on_inv_filter_apply)
        self.btn_inv_apply.pack(side="left", padx=2)
        self.btn_inv_reset = ttk.Button(filter_row, text="重置",
                                        command=self._on_inv_filter_reset)
        self.btn_inv_reset.pack(side="left", padx=2)

        self.btn_inv_continue = ttk.Button(filter_row, text="继续上次盘点",
                                           command=self._continue_last_inventory)
        self.btn_inv_continue.pack(side="left", padx=2)

        self.btn_inv_create = ttk.Button(filter_row, text="新建盘点",
                                         command=self._create_inventory)
        self.btn_inv_create.pack(side="right", padx=2)
        self.btn_inv_export = ttk.Button(filter_row, text="导出选中",
                                         command=self._export_inventory)
        self.btn_inv_export.pack(side="right", padx=2)
        self.btn_inv_complete = ttk.Button(filter_row, text="完成盘点",
                                           command=self._complete_inventory)
        self.btn_inv_complete.pack(side="right", padx=2)
        self.btn_inv_detail = ttk.Button(filter_row, text="查看详情",
                                         command=self._view_inventory_detail)
        self.btn_inv_detail.pack(side="right", padx=2)
        self.btn_inv_fill = ttk.Button(filter_row, text="填写",
                                       command=self._fill_inventory_item)
        self.btn_inv_fill.pack(side="right", padx=2)

        self.inv_status_label = ttk.Label(filter_row, text="", foreground="#2980b9")
        self.inv_status_label.pack(side="right", padx=6)

        itree_frame = ttk.Frame(inv_frame)
        itree_frame.pack(fill="both", expand=True)
        icols = ("id", "title", "status", "items", "exceptions",
                 "created_by", "created_at", "completed_at")
        self.inv_tree = ttk.Treeview(itree_frame, columns=icols,
                                     show="headings", height=7, selectmode="browse")
        self.inv_tree.heading("id", text="盘点ID")
        self.inv_tree.heading("title", text="标题")
        self.inv_tree.heading("status", text="状态")
        self.inv_tree.heading("items", text="设备数")
        self.inv_tree.heading("exceptions", text="异常数")
        self.inv_tree.heading("created_by", text="创建人")
        self.inv_tree.heading("created_at", text="创建时间")
        self.inv_tree.heading("completed_at", text="完成时间")
        self.inv_tree.column("id", width=80, anchor="center")
        self.inv_tree.column("title", width=180, anchor="w")
        self.inv_tree.column("status", width=70, anchor="center")
        self.inv_tree.column("items", width=60, anchor="center")
        self.inv_tree.column("exceptions", width=60, anchor="center")
        self.inv_tree.column("created_by", width=80, anchor="w")
        self.inv_tree.column("created_at", width=140, anchor="w")
        self.inv_tree.column("completed_at", width=140, anchor="w")
        ivsb = ttk.Scrollbar(itree_frame, orient="vertical", command=self.inv_tree.yview)
        self.inv_tree.configure(yscrollcommand=ivsb.set)
        self.inv_tree.pack(side="left", fill="both", expand=True)
        ivsb.pack(side="right", fill="y")
        self.inv_tree.bind("<<TreeviewSelect>>", self._on_inventory_selected)

        self.inv_tree.tag_configure(InventoryStatus.DRAFT, foreground="#888")
        self.inv_tree.tag_configure(InventoryStatus.IN_PROGRESS, foreground="#e67e22")
        self.inv_tree.tag_configure(InventoryStatus.COMPLETED, foreground="#27ae60")

        iitem_frame = ttk.LabelFrame(inv_frame, text="盘点明细（选中盘点后显示）", padding=4)
        iitem_frame.pack(fill="both", expand=True, pady=(6, 0))

        iitree_frame = ttk.Frame(iitem_frame)
        iitree_frame.pack(fill="both", expand=True)
        iicols = ("device_id", "device_name", "original_status", "actual_status",
                  "result", "filled_by")
        self.inv_item_tree = ttk.Treeview(iitree_frame, columns=iicols,
                                          show="headings", height=5, selectmode="browse")
        self.inv_item_tree.heading("device_id", text="设备ID")
        self.inv_item_tree.heading("device_name", text="设备名称")
        self.inv_item_tree.heading("original_status", text="系统原状态")
        self.inv_item_tree.heading("actual_status", text="实际状态")
        self.inv_item_tree.heading("result", text="盘点结果")
        self.inv_item_tree.heading("filled_by", text="填写人")
        self.inv_item_tree.column("device_id", width=80, anchor="center")
        self.inv_item_tree.column("device_name", width=180, anchor="w")
        self.inv_item_tree.column("original_status", width=90, anchor="center")
        self.inv_item_tree.column("actual_status", width=90, anchor="center")
        self.inv_item_tree.column("result", width=90, anchor="center")
        self.inv_item_tree.column("filled_by", width=80, anchor="w")
        iivsb = ttk.Scrollbar(iitree_frame, orient="vertical", command=self.inv_item_tree.yview)
        self.inv_item_tree.configure(yscrollcommand=iivsb.set)
        self.inv_item_tree.pack(side="left", fill="both", expand=True)
        iivsb.pack(side="right", fill="y")
        self.inv_item_tree.bind("<<TreeviewSelect>>", self._on_inventory_item_selected)

        self.inv_item_tree.tag_configure("exception", foreground="#c0392b", background="#fdecea")
        self.inv_item_tree.tag_configure("unfilled", foreground="#888")

    def _build_records_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="借用记录", padding=6)
        frame.pack(fill="both", expand=True)

        filter_frame = ttk.Frame(frame)
        filter_frame.pack(fill="x", pady=(0, 4))

        ttk.Label(filter_frame, text="筛选:").pack(side="left", padx=(0, 4))
        self.filter_buttons = {}
        for key in ("all", "due_soon", "overdue", "returned"):
            btn = ttk.Button(filter_frame, text=FILTER_LABELS[key],
                             command=lambda k=key: self._on_filter_changed(k))
            btn.pack(side="left", padx=2)
            self.filter_buttons[key] = btn

        ttk.Separator(filter_frame, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(filter_frame, text="提醒天数:").pack(side="left", padx=(0, 4))
        self.reminder_days_var = tk.StringVar(value=str(self.manager.get_reminder_days()))
        self.reminder_days_entry = ttk.Spinbox(
            filter_frame, from_=1, to=365, width=6,
            textvariable=self.reminder_days_var, state="readonly"
        )
        self.reminder_days_entry.pack(side="left")
        self.btn_set_reminder_days = ttk.Button(
            filter_frame, text="应用", command=self._on_set_reminder_days
        )
        self.btn_set_reminder_days.pack(side="left", padx=(4, 8))

        self.filter_status_label = ttk.Label(filter_frame, text="", foreground="#2980b9")
        self.filter_status_label.pack(side="left")

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
        self.btn_import_records = ttk.Button(btns, text="批量导入", command=self._import_records)
        self.btn_import_records.pack(side="right", padx=2)
        self.btn_export_records = ttk.Button(btns, text="导出选中", command=self._export_selected_records)
        self.btn_export_records.pack(side="right", padx=2)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)
        cols = ("id", "device", "borrower", "dept", "borrow_time",
                "exp_return", "alert", "status", "operator")
        self.record_tree = ttk.Treeview(tree_frame, columns=cols,
                                        show="headings", selectmode="extended")
        self.record_tree.heading("id", text="记录ID")
        self.record_tree.heading("device", text="设备")
        self.record_tree.heading("borrower", text="借用人")
        self.record_tree.heading("dept", text="部门")
        self.record_tree.heading("borrow_time", text="借出时间")
        self.record_tree.heading("exp_return", text="预计归还")
        self.record_tree.heading("alert", text="提醒")
        self.record_tree.heading("status", text="状态")
        self.record_tree.heading("operator", text="借出操作员")
        self.record_tree.column("id", width=80, anchor="center")
        self.record_tree.column("device", width=180, anchor="w")
        self.record_tree.column("borrower", width=80, anchor="w")
        self.record_tree.column("dept", width=100, anchor="w")
        self.record_tree.column("borrow_time", width=140, anchor="w")
        self.record_tree.column("exp_return", width=140, anchor="w")
        self.record_tree.column("alert", width=70, anchor="center")
        self.record_tree.column("status", width=80, anchor="center")
        self.record_tree.column("operator", width=90, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.record_tree.yview)
        self.record_tree.configure(yscrollcommand=vsb.set)
        self.record_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.record_tree.bind("<<TreeviewSelect>>", self._on_record_selected)

        for s in (RecordStatus.BORROWED, RecordStatus.INSPECTING,
                  RecordStatus.RETURNED, RecordStatus.FROZEN):
            self.record_tree.tag_configure(s, foreground=STATUS_COLORS[s])
        self.record_tree.tag_configure("overdue", foreground=ALERT_OVERDUE_COLOR,
                                       background="#fdecea")
        self.record_tree.tag_configure("due_soon", foreground=ALERT_DUE_SOON_COLOR,
                                       background="#fef5e7")

    def _refresh_all(self):
        self._refresh_user_combo()
        self._refresh_devices()
        self._refresh_borrowers()
        self._restore_last_maintenance_filter()
        self._restore_last_inventory_filter()
        self._refresh_records()
        self._refresh_maintenance_logs()
        self._refresh_inventory_sessions()
        self._refresh_export_dir()
        self._apply_permissions()

    def _restore_last_maintenance_filter(self):
        saved = self.manager.get_last_maintenance_filter()
        if saved:
            self._maint_filter_device = saved.get("device_id", "")
            self._maint_filter_status = saved.get("status_filter", "all")
            self._maint_filter_start_from = saved.get("start_from", "")
            self._maint_filter_start_to = saved.get("start_to", "")
        self.maint_device_var.set(self._maint_filter_device)
        status_label = MAINTENANCE_STATUS_LABELS.get(self._maint_filter_status, MAINTENANCE_STATUS_LABELS["all"])
        self.maint_status_var.set(status_label)
        self.maint_from_var.set(self._maint_filter_start_from)
        self.maint_to_var.set(self._maint_filter_start_to)

    def _restore_last_inventory_filter(self):
        saved = self.manager.get_last_inventory_filter()
        if saved:
            self._inventory_filter_status = saved.get("status_filter", "all")
        status_label = INVENTORY_STATUS_LABELS.get(self._inventory_filter_status, INVENTORY_STATUS_LABELS["all"])
        self.inv_status_var.set(status_label)
        if self.manager.has_permission("fill_inventory"):
            session = self.manager.get_active_inventory_session()
            if session:
                self._selected_inventory_id = session.id
                self._inventory_filter_status = "all"
                self.inv_status_var.set(INVENTORY_STATUS_LABELS["all"])

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
                d.name, d.category, d.status,
                d.storage_location or "-", d.responsible_person or "-",
                d.model, d.serial_no
            ), tags=(d.status,))
        self._refresh_device_detail()

    def _refresh_borrowers(self):
        self.borrower_tree.delete(*self.borrower_tree.get_children())
        for b in self.manager.borrowers:
            self.borrower_tree.insert("", "end", iid=b.id, values=(
                b.name, b.department, b.phone
            ))

    def _refresh_records(self):
        current_selection = list(self.record_tree.selection())
        if current_selection:
            self._preserved_record_selection = current_selection
        self.record_tree.delete(*self.record_tree.get_children())
        base_records = self.manager.get_filtered_records()
        filtered_records = self.manager.filter_records_by_alert(
            base_records, self._current_alert_filter
        )
        visible_ids = set()
        for r in sorted(filtered_records, key=lambda x: x.borrow_time, reverse=True):
            alert_status = self.manager.get_record_alert_status(r)
            alert_text = ""
            tags = [r.status]
            if alert_status == "overdue":
                alert_text = "⚠ 逾期"
                tags.append("overdue")
            elif alert_status == "due_soon":
                alert_text = "⏰ 临期"
                tags.append("due_soon")
            self.record_tree.insert("", "end", iid=r.id, values=(
                r.id, r.device_name, r.borrower_name, r.borrower_department,
                r.borrow_time, r.expected_return_time, alert_text, r.status,
                r.check_out_operator
            ), tags=tags)
            visible_ids.add(r.id)
        to_restore = [rid for rid in self._preserved_record_selection if rid in visible_ids]
        if to_restore:
            try:
                self.record_tree.selection_set(to_restore)
            except Exception:
                pass
        for key, btn in self.filter_buttons.items():
            if key == self._current_alert_filter:
                btn.config(state="disabled")
            else:
                btn.config(state="normal")
        total_count = len(base_records)
        filtered_count = len(filtered_records)
        status_text = f"显示 {filtered_count}/{total_count} 条"
        if self._current_alert_filter != "all":
            status_text += f"（{FILTER_LABELS[self._current_alert_filter]}）"
        if filtered_count == 0 and self._current_alert_filter != "all":
            status_text += " - 该筛选下无记录"
        self.filter_status_label.config(text=status_text)
        self.reminder_days_var.set(str(self.manager.get_reminder_days()))

    def _on_filter_changed(self, filter_key: str):
        self._preserved_record_selection = list(self.record_tree.selection())
        self._current_alert_filter = filter_key
        self._refresh_records()

    def _on_set_reminder_days(self):
        try:
            days = int(self.reminder_days_var.get())
        except ValueError:
            messagebox.showerror("错误", "提醒天数必须是整数")
            return
        try:
            ok, msg = self.manager.set_reminder_days(days)
        except BusinessError as e:
            messagebox.showerror("错误", str(e))
            return
        if ok:
            messagebox.showinfo("成功", msg)
            self._refresh_records()
        else:
            messagebox.showerror("失败", msg)
            self.reminder_days_var.set(str(self.manager.get_reminder_days()))

    def _refresh_device_detail(self):
        self.device_detail.config(state="normal")
        self.device_detail.delete("1.0", "end")
        device = self.manager.find_device(self._selected_device_id)
        if device:
            lines = [f"设备: {device.name}  ({device.category} / {device.status})",
                     f"型号: {device.model or '-'}    序列号: {device.serial_no or '-'}",
                     f"存放点: {device.storage_location or '-'}    负责人: {device.responsible_person or '-'}",
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
            return
        ok, reason = self.manager.check_export_dir_detail()
        if ok:
            self.export_status_label.config(text="【可写】", foreground="#27ae60")
        else:
            if "不存在" in reason:
                self.export_status_label.config(text="【已失效】", foreground="#c0392b")
            elif "没有写入权限" in reason or "写入权限" in reason:
                self.export_status_label.config(text="【无权限】", foreground="#c0392b")
            else:
                self.export_status_label.config(text="【不可用】", foreground="#c0392b")

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
            "import_records": [self.btn_import_records],
            "set_reminder_days": [self.btn_set_reminder_days, self.reminder_days_entry],
            "send_to_maintenance": [self.btn_send_maintenance],
            "cancel_maintenance": [self.btn_cancel_maintenance],
            "view_maintenance": [self.btn_maint_apply, self.btn_maint_reset],
            "export_maintenance": [self.btn_maint_export],
            "create_inventory": [self.btn_inv_create],
            "complete_inventory": [self.btn_inv_complete],
            "fill_inventory": [self.btn_inv_fill, self.btn_inv_continue],
            "view_inventory": [self.btn_inv_apply, self.btn_inv_reset, self.btn_inv_detail],
            "export_inventory": [self.btn_inv_export],
        }
        for perm, widgets in perm_map.items():
            enabled = self.manager.has_permission(perm)
            for w in widgets:
                if perm == "set_reminder_days" and isinstance(w, ttk.Spinbox):
                    w.config(state="normal" if enabled else "disabled")
                else:
                    w.config(state="normal" if enabled else "disabled")

        if not self.manager.has_permission("view_maintenance"):
            self.maint_device_var.set("")
            self.maint_status_var.set(MAINTENANCE_STATUS_LABELS["all"])
            self.maint_from_var.set("")
            self.maint_to_var.set("")
            for child in self.maint_tree.winfo_children():
                child.pack_forget() if hasattr(child, "pack_forget") else None

        if not self.manager.has_permission("view_inventory"):
            self.inv_status_var.set(INVENTORY_STATUS_LABELS["all"])
            self.inv_tree.delete(*self.inv_tree.get_children())
            self.inv_item_tree.delete(*self.inv_item_tree.get_children())
            self.inv_status_label.config(text="【无权限】", foreground="#c0392b")

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
        ok, reason = self.manager.check_export_dir_detail()
        if not ok:
            messagebox.showerror("导出失败",
                                 f"当前导出目录不可用：{reason}\n\n"
                                 f"请先在顶部点击【设置...】选择一个：\n"
                                 f"  · 已经存在的目录（不会自动创建子目录）\n"
                                 f"  · 当前用户有写入权限的目录\n\n"
                                 f"在导出目录恢复可用前，任何导出操作：\n"
                                 f"  · 不会改动已选中的记录/设备数据\n"
                                 f"  · 不会生成任何导出文件\n"
                                 f"  · 不会覆盖之前保存的常用导出目录")
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
        if device.status == DeviceStatus.MAINTENANCE:
            messagebox.showerror("错误",
                                 f"设备【{device.name}】正在维修/保养中，不能借出。\n"
                                 f"请待维修完成恢复可用后再操作。")
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
        base_records = self.manager.get_filtered_records()
        visible_records = self.manager.filter_records_by_alert(
            base_records, self._current_alert_filter
        )
        visible_ids = {r.id for r in visible_records}
        sel = self.record_tree.selection()
        sel_ids = [rid for rid in sel if rid in visible_ids]
        if not sel_ids:
            if not visible_records:
                messagebox.showinfo("提示", "当前筛选结果为空，没有可导出的记录")
            else:
                messagebox.showinfo(
                    "提示",
                    f"请先在当前【{FILTER_LABELS[self._current_alert_filter]}】筛选下"
                    f"选择要导出的借用记录（支持多选）\n\n"
                    f"当前筛选共 {len(visible_records)} 条可见记录"
                )
            return
        if not self._check_export_dir():
            return
        default_name = f"借用记录_{FILTER_LABELS[self._current_alert_filter]}_{_now_str().replace(':', '-').replace(' ', '_')}"
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
        alert_status_map = {}
        for r in self.manager.records:
            st = self.manager.get_record_alert_status(r)
            if st == "overdue":
                alert_status_map[r.id] = "逾期"
            elif st == "due_soon":
                alert_status_map[r.id] = "临期"
            else:
                alert_status_map[r.id] = "正常"
        filter_info = {
            "description": FILTER_LABELS[self._current_alert_filter],
            "筛选类型": FILTER_LABELS[self._current_alert_filter],
            "提醒天数": f"{self.manager.get_reminder_days()} 天",
            "导出时间": _now_str(),
            "操作人": (f"{self.manager.current_user.display_name} ({self.manager.current_user.username})"
                       if self.manager.current_user else "unknown"),
            "角色": self.manager.current_user.role if self.manager.current_user else "unknown",
            "可见记录数": len(visible_records),
            "本次选中导出数": len(sel_ids),
            "_alert_status": alert_status_map,
        }
        ok, msg = self.manager.export_selected_records(sel_ids, filepath, filter_info)
        if ok:
            messagebox.showinfo("成功", f"{msg}\n\n共导出 {len(sel_ids)} 条记录（{FILTER_LABELS[self._current_alert_filter]} 筛选）")
        else:
            messagebox.showerror("失败", msg)

    def _import_records(self):
        if (self.manager.current_user and
                self.manager.current_user.role == UserRole.BORROWER):
            messagebox.showerror("无权限",
                                 "借用人不能进行批量导入操作。\n"
                                 "请联系管理员或验收人处理。")
            return

        initial = (self.manager.config.last_import_dir
                   or self.manager.config.export_dir
                   or os.path.expanduser("~"))
        filepath = filedialog.askopenfilename(
            title="选择要导入的借用记录文件",
            initialdir=initial,
            filetypes=[
                ("CSV / JSON 数据文件", "*.csv *.json"),
                ("CSV 表格", "*.csv"),
                ("JSON 数据", "*.json"),
                ("所有文件", "*.*"),
            ]
        )
        if not filepath:
            return

        try:
            ok, msg, summary = self.manager.precheck_import_file(filepath)
        except BusinessError as e:
            messagebox.showerror("错误", str(e))
            return

        if not ok:
            messagebox.showerror("预检失败", f"文件无法解析：\n{msg}")
            return

        dlg = ImportPrecheckDialog(self.root, filepath, summary)
        self.root.wait_window(dlg)
        if not dlg.confirmed:
            return

        try:
            ok, msg, sc, fc = self.manager.commit_import(filepath)
        except BusinessError as e:
            messagebox.showerror("错误", str(e))
            return

        self._refresh_devices()
        self._refresh_records()
        if ok:
            messagebox.showinfo(
                "导入完成",
                f"{msg}\n\n"
                f"文件：{os.path.basename(filepath)}\n"
                f"总数：{summary.total}，成功：{sc}，失败：{fc}"
            )
            self.status_var.set(f"批量导入完成：成功 {sc}，失败 {fc}")
        else:
            messagebox.showerror(
                "导入失败（已回滚）",
                f"{msg}\n\n"
                f"所有记录均未写入，设备状态和记录历史保持不变。"
            )

    def _send_to_maintenance(self):
        if not self._selected_device_id:
            messagebox.showinfo("提示", "请先在左侧选择要送修/保养的设备")
            return
        device = self.manager.find_device(self._selected_device_id)
        if not device:
            return
        if device.status not in (DeviceStatus.AVAILABLE, DeviceStatus.FROZEN):
            messagebox.showerror("错误",
                                 f"设备【{device.name}】当前状态为【{device.status}】，\n"
                                 f"仅【可借出】或【异常冻结】的设备可登记维修/保养。")
            return
        dlg = MaintenanceDialog(self.root, self.manager, device)
        self.root.wait_window(dlg)
        if dlg.result:
            self._refresh_devices()
            self._refresh_maintenance_logs()
            self.status_var.set(f"设备【{device.name}】已登记为维修/保养")

    def _cancel_maintenance(self):
        if not self._selected_device_id:
            messagebox.showinfo("提示", "请先在左侧选择要撤销送修的设备")
            return
        device = self.manager.find_device(self._selected_device_id)
        if not device:
            return
        if device.status != DeviceStatus.MAINTENANCE:
            messagebox.showerror("错误",
                                 f"设备【{device.name}】当前状态为【{device.status}】，\n"
                                 f"只有【维修中】的设备可撤销送修。")
            return
        dlg = CancelMaintenanceDialog(self.root, self.manager, device)
        self.root.wait_window(dlg)
        if dlg.result:
            self._refresh_devices()
            self._refresh_maintenance_logs()
            self.status_var.set(f"设备【{device.name}】的维修登记已撤销")

    def _on_maint_selected(self, _event=None):
        sel = self.maint_tree.selection()
        self._selected_maintenance_ids = list(sel)

    def _label_to_maint_status_key(self, label: str) -> str:
        for k, v in MAINTENANCE_STATUS_LABELS.items():
            if v == label:
                return k
        return "all"

    def _on_maint_filter_apply(self):
        self._maint_filter_device = self.maint_device_var.get().strip()
        self._maint_filter_status = self._label_to_maint_status_key(self.maint_status_var.get())
        self._maint_filter_start_from = self.maint_from_var.get().strip()
        self._maint_filter_start_to = self.maint_to_var.get().strip()
        self.manager.save_maintenance_filter({
            "device_id": self._maint_filter_device,
            "status_filter": self._maint_filter_status,
            "start_from": self._maint_filter_start_from,
            "start_to": self._maint_filter_start_to,
        })
        self._refresh_maintenance_logs()
        self.status_var.set("维修记录筛选已应用")

    def _on_maint_filter_reset(self):
        self._maint_filter_device = ""
        self._maint_filter_status = "all"
        self._maint_filter_start_from = ""
        self._maint_filter_start_to = ""
        self.maint_device_var.set("")
        self.maint_status_var.set(MAINTENANCE_STATUS_LABELS["all"])
        self.maint_from_var.set("")
        self.maint_to_var.set("")
        self.manager.save_maintenance_filter({})
        self._refresh_maintenance_logs()
        self.status_var.set("维修记录筛选已重置")

    def _refresh_maintenance_logs(self):
        if not self.manager.has_permission("view_maintenance"):
            self.maint_tree.delete(*self.maint_tree.get_children())
            self.maint_status_label.config(text="【无权限】", foreground="#c0392b")
            return
        try:
            all_logs = self.manager.get_maintenance_logs()
        except BusinessError:
            self.maint_tree.delete(*self.maint_tree.get_children())
            self.maint_status_label.config(text="【无权限】", foreground="#c0392b")
            return
        filtered = self.manager.filter_maintenance_logs(
            all_logs,
            device_id=self._maint_filter_device,
            status_filter=self._maint_filter_status,
            start_from=self._maint_filter_start_from,
            start_to=self._maint_filter_start_to,
        )
        current_selection = list(self.maint_tree.selection())
        if current_selection:
            self._selected_maintenance_ids = current_selection
        self.maint_tree.delete(*self.maint_tree.get_children())
        visible_ids = set()
        for m in sorted(filtered, key=lambda x: x.start_time, reverse=True):
            status_text = "进行中" if m.status == "in_progress" else (
                "已撤销" if m.status == "cancelled" else m.status
            )
            self.maint_tree.insert("", "end", iid=m.id, values=(
                m.id, m.device_id, m.device_name, m.from_status,
                (m.reason[:18] + "...") if len(m.reason) > 20 else m.reason,
                m.expected_recover_time, m.start_time, status_text, m.operator
            ), tags=(m.status,))
            visible_ids.add(m.id)
        to_restore = [mid for mid in self._selected_maintenance_ids if mid in visible_ids]
        if to_restore:
            try:
                self.maint_tree.selection_set(to_restore)
            except Exception:
                pass
        total = len(all_logs)
        shown = len(filtered)
        parts = [f"显示 {shown}/{total} 条"]
        if self._maint_filter_status != "all":
            parts.append(f"（{MAINTENANCE_STATUS_LABELS[self._maint_filter_status]}）")
        if self._maint_filter_device:
            parts.append(f"设备={self._maint_filter_device}")
        if shown == 0 and (self._maint_filter_status != "all" or self._maint_filter_device
                            or self._maint_filter_start_from or self._maint_filter_start_to):
            parts.append("- 该筛选下无记录")
        self.maint_status_label.config(text="  ".join(parts), foreground="#2980b9")

    def _export_maintenance_logs(self):
        if not self.manager.has_permission("view_maintenance"):
            messagebox.showerror("无权限", "当前角色不能查看或导出维修记录。")
            return
        sel = self.maint_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在维修记录列表中选择要导出的记录（支持多选）")
            return
        if not self._check_export_dir():
            return
        status_desc = MAINTENANCE_STATUS_LABELS.get(self._maint_filter_status, "全部")
        default_name = f"维修记录_{status_desc}_{_now_str().replace(':', '-').replace(' ', '_')}"
        filepath = filedialog.asksaveasfilename(
            title="导出维修记录",
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
        filter_info = {
            "description": f"维修记录（{status_desc}）",
            "筛选类型": status_desc,
            "设备ID筛选": self._maint_filter_device or "（未指定）",
            "时间起": self._maint_filter_start_from or "（未指定）",
            "时间止": self._maint_filter_start_to or "（未指定）",
            "默认维修天数": f"{self.manager.get_default_maintenance_days()} 天",
            "导出时间": _now_str(),
            "操作人": (f"{self.manager.current_user.display_name} ({self.manager.current_user.username})"
                       if self.manager.current_user else "unknown"),
            "角色": self.manager.current_user.role if self.manager.current_user else "unknown",
            "可见记录数": len(self.manager.filter_maintenance_logs(
                self.manager.maintenance_logs,
                device_id=self._maint_filter_device,
                status_filter=self._maint_filter_status,
                start_from=self._maint_filter_start_from,
                start_to=self._maint_filter_start_to,
            )),
            "本次选中导出数": len(sel),
        }
        ok, msg = self.manager.export_maintenance_logs(list(sel), filepath, filter_info)
        if ok:
            messagebox.showinfo("成功", f"{msg}\n\n共导出 {len(sel)} 条维修记录")
        else:
            messagebox.showerror("失败", msg)

    def _label_to_inventory_status_key(self, label: str) -> str:
        for k, v in INVENTORY_STATUS_LABELS.items():
            if v == label:
                return k
        return "all"

    def _on_inv_filter_apply(self):
        self._inventory_filter_status = self._label_to_inventory_status_key(
            self.inv_status_var.get())
        self.manager.save_inventory_filter({
            "status_filter": self._inventory_filter_status,
        })
        self._refresh_inventory_sessions()
        self.status_var.set("盘点筛选已应用")

    def _on_inv_filter_reset(self):
        self._inventory_filter_status = "all"
        self.inv_status_var.set(INVENTORY_STATUS_LABELS["all"])
        self.manager.save_inventory_filter({})
        self._refresh_inventory_sessions()
        self.status_var.set("盘点筛选已重置")

    def _on_inventory_selected(self, _event=None):
        sel = self.inv_tree.selection()
        self._selected_inventory_id = sel[0] if sel else None
        self._selected_inventory_item_device_id = None
        self._refresh_inventory_items()

    def _on_inventory_item_selected(self, _event=None):
        sel = self.inv_item_tree.selection()
        self._selected_inventory_item_device_id = sel[0] if sel else None

    def _refresh_inventory_sessions(self):
        if not self.manager.has_permission("view_inventory"):
            self.inv_tree.delete(*self.inv_tree.get_children())
            self.inv_item_tree.delete(*self.inv_item_tree.get_children())
            self.inv_status_label.config(text="【无权限】", foreground="#c0392b")
            return
        try:
            all_sessions = self.manager.get_inventory_sessions()
        except BusinessError:
            self.inv_tree.delete(*self.inv_tree.get_children())
            self.inv_item_tree.delete(*self.inv_item_tree.get_children())
            self.inv_status_label.config(text="【无权限】", foreground="#c0392b")
            return
        filtered = [s for s in all_sessions
                    if self._inventory_filter_status == "all"
                    or s.status == self._inventory_filter_status]
        current_selection = self.inv_tree.selection()
        if current_selection:
            self._selected_inventory_id = current_selection[0]
        self.inv_tree.delete(*self.inv_tree.get_children())
        visible_ids = set()
        for s in sorted(filtered, key=lambda x: x.created_at, reverse=True):
            ex_count = self.manager.get_inventory_exception_count(s)
            self.inv_tree.insert("", "end", iid=s.id, values=(
                s.id, s.title, s.status, len(s.items), ex_count,
                s.created_by, s.created_at, s.completed_at or "-"
            ), tags=(s.status,))
            visible_ids.add(s.id)
        if self._selected_inventory_id and self._selected_inventory_id in visible_ids:
            try:
                self.inv_tree.selection_set(self._selected_inventory_id)
            except Exception:
                pass
        else:
            self._selected_inventory_id = None
        self._refresh_inventory_items()
        total = len(all_sessions)
        shown = len(filtered)
        parts = [f"显示 {shown}/{total} 条"]
        if self._inventory_filter_status != "all":
            parts.append(f"（{INVENTORY_STATUS_LABELS[self._inventory_filter_status]}）")
        if shown == 0 and self._inventory_filter_status != "all":
            parts.append("- 该筛选下无记录")
        self.inv_status_label.config(text="  ".join(parts), foreground="#2980b9")

    def _refresh_inventory_items(self):
        self.inv_item_tree.delete(*self.inv_item_tree.get_children())
        if not self._selected_inventory_id:
            return
        session = self.manager.find_inventory_session(self._selected_inventory_id)
        if not session:
            return
        for it in session.items:
            tag = "unfilled" if not it.inventory_result else (
                "exception" if it.inventory_result != InventoryItemResult.NORMAL else "normal")
            self.inv_item_tree.insert("", "end", iid=it.device_id, values=(
                it.device_id, it.device_name, it.original_status,
                it.actual_status or "-",
                it.inventory_result or "未填写",
                it.filled_by or "-"
            ), tags=(tag,))

    def _continue_last_inventory(self):
        if not self.manager.has_permission("fill_inventory"):
            messagebox.showerror("无权限", "当前角色不能填写盘点。")
            return
        session = self.manager.get_active_inventory_session()
        if not session:
            messagebox.showinfo("提示", "没有找到未完成的上次盘点。")
            return
        self._inventory_filter_status = "all"
        self.inv_status_var.set(INVENTORY_STATUS_LABELS["all"])
        self._selected_inventory_id = session.id
        self._refresh_inventory_sessions()
        try:
            self.inv_tree.selection_set(session.id)
        except Exception:
            pass
        self.status_var.set(f"已恢复上次盘点：{session.title}")

    def _create_inventory(self):
        if not self.manager.has_permission("create_inventory"):
            messagebox.showerror("无权限", "当前角色不能创建盘点。")
            return
        dlg = CreateInventoryDialog(self.root, self.manager)
        self.root.wait_window(dlg)
        if dlg.result:
            self._selected_inventory_id = dlg.result.id
            self._refresh_inventory_sessions()
            self.status_var.set(f"盘点已创建：{dlg.result.title}")

    def _fill_inventory_item(self):
        if not self.manager.has_permission("fill_inventory"):
            messagebox.showerror("无权限", "当前角色不能填写盘点。")
            return
        if not self._selected_inventory_id:
            messagebox.showinfo("提示", "请先在盘点列表中选择一个盘点")
            return
        session = self.manager.find_inventory_session(self._selected_inventory_id)
        if not session:
            return
        if session.status == InventoryStatus.COMPLETED:
            messagebox.showinfo("提示", "该盘点已完成，不能再填写。")
            return
        if not self._selected_inventory_item_device_id:
            messagebox.showinfo("提示", "请在盘点明细中选择要填写的设备")
            return
        item = self.manager._find_inventory_item(session, self._selected_inventory_item_device_id)
        if not item:
            return
        dlg = FillInventoryItemDialog(self.root, self.manager, session, item)
        self.root.wait_window(dlg)
        if dlg.result:
            self._refresh_inventory_sessions()
            if self._selected_inventory_id:
                try:
                    self.inv_tree.selection_set(self._selected_inventory_id)
                    self._refresh_inventory_items()
                    if self._selected_inventory_item_device_id:
                        self.inv_item_tree.selection_set(self._selected_inventory_item_device_id)
                except Exception:
                    pass
            self.status_var.set(f"盘点项已填写：{dlg.result.inventory_result}")

    def _complete_inventory(self):
        if not self.manager.has_permission("complete_inventory"):
            messagebox.showerror("无权限", "当前角色不能完成盘点。")
            return
        if not self._selected_inventory_id:
            messagebox.showinfo("提示", "请先选择要完成的盘点")
            return
        session = self.manager.find_inventory_session(self._selected_inventory_id)
        if not session:
            return
        if session.status == InventoryStatus.COMPLETED:
            messagebox.showinfo("提示", "该盘点已经完成。")
            return
        unfilled = [it for it in session.items if not it.inventory_result]
        if unfilled:
            if not messagebox.askyesno(
                "未填写完成",
                f"还有 {len(unfilled)} 台设备未填写盘点结果。\n"
                f"确定要标记为已完成吗？（不建议）"
            ):
                return
        remark = simpledialog.askstring("完成盘点", "完成说明（可选）:", parent=self.root)
        try:
            completed = self.manager.complete_inventory(session.id, remark or "")
            ex_count = self.manager.get_inventory_exception_count(completed)
            messagebox.showinfo(
                "成功",
                f"盘点【{completed.title}】已完成！\n"
                f"共 {len(completed.items)} 台设备，异常 {ex_count} 台。"
            )
            self._refresh_inventory_sessions()
            self.status_var.set(f"盘点已完成：{completed.title}")
        except BusinessError as e:
            messagebox.showerror("失败", str(e))

    def _view_inventory_detail(self):
        if not self.manager.has_permission("view_inventory"):
            messagebox.showerror("无权限", "当前角色不能查看盘点详情。")
            return
        if not self._selected_inventory_id:
            messagebox.showinfo("提示", "请先选择要查看的盘点")
            return
        session = self.manager.find_inventory_session(self._selected_inventory_id)
        if not session:
            return
        InventoryDetailDialog(self.root, self.manager, session)

    def _export_inventory(self):
        if not self.manager.has_permission("export_inventory"):
            messagebox.showerror("无权限", "当前角色不能导出盘点。")
            return
        if not self._selected_inventory_id:
            messagebox.showinfo("提示", "请先选择要导出的盘点")
            return
        session = self.manager.find_inventory_session(self._selected_inventory_id)
        if not session:
            return
        if session.status != InventoryStatus.COMPLETED:
            messagebox.showerror("错误", "只有已完成的盘点才能导出。")
            return
        if not self._check_export_dir():
            return
        status_desc = INVENTORY_STATUS_LABELS.get(self._inventory_filter_status, "全部")
        default_name = f"月度盘点_{session.title}_{_now_str().replace(':', '-').replace(' ', '_')}"
        filepath = filedialog.asksaveasfilename(
            title="导出盘点结果",
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
        ok, msg = self.manager.export_inventory_session(session.id, filepath)
        if ok:
            ex_count = self.manager.get_inventory_exception_count(session)
            messagebox.showinfo("成功", f"{msg}\n\n共 {len(session.items)} 台设备，异常 {ex_count} 台")
        else:
            messagebox.showerror("失败", msg)


class ImportPrecheckDialog(tk.Toplevel):
    def __init__(self, master, filepath: str, summary):
        super().__init__(master)
        self.title(f"导入预检 - {os.path.basename(filepath)}")
        self.geometry("680x560")
        self.minsize(600, 480)
        self.summary = summary
        self.confirmed = False
        self._build(filepath)
        self.grab_set()
        self.transient(master)

    def _build(self, filepath: str):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        info = ttk.LabelFrame(main, text="预检概要", padding=8)
        info.pack(fill="x", pady=(0, 8))
        s = self.summary
        ttk.Label(info, text=f"文件：{filepath}").grid(row=0, column=0, sticky="w", columnspan=4)
        ttk.Label(info, text=f"记录总数：{s.total}").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(info, text=f"可导入：{s.importable}",
                  foreground="#27ae60").grid(row=1, column=1, sticky="w", padx=20)
        ttk.Label(info, text=f"字段缺失：{s.field_missing}",
                  foreground="#c0392b").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Label(info, text=f"设备不存在：{s.device_not_found}",
                  foreground="#c0392b").grid(row=2, column=1, sticky="w", padx=20)
        ttk.Label(info, text=f"设备状态冲突：{s.device_status_conflict}",
                  foreground="#c0392b").grid(row=2, column=2, sticky="w", padx=20)
        ttk.Label(info, text=f"借用人不存在：{s.borrower_not_found}",
                  foreground="#c0392b").grid(row=3, column=0, sticky="w", pady=2)
        ttk.Label(info, text=f"重复记录：{s.duplicate}",
                  foreground="#c0392b").grid(row=3, column=1, sticky="w", padx=20)

        tree_frame = ttk.LabelFrame(main, text="问题明细（如有）", padding=8)
        tree_frame.pack(fill="both", expand=True)
        cols = ("row", "kind", "device", "borrower", "detail")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=14)
        tree.heading("row", text="行号")
        tree.heading("kind", text="问题类型")
        tree.heading("device", text="设备ID")
        tree.heading("borrower", text="借用人ID")
        tree.heading("detail", text="说明")
        tree.column("row", width=60, anchor="center")
        tree.column("kind", width=110, anchor="center")
        tree.column("device", width=90, anchor="w")
        tree.column("borrower", width=90, anchor="w")
        tree.column("detail", width=300, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for iss in self.summary.issues:
            tree.insert("", "end", values=(
                iss.get("row", ""), iss.get("kind", ""),
                iss.get("device_id", ""), iss.get("borrower_id", ""),
                iss.get("detail", "")
            ))

        s = self.summary
        has_issue = (s.field_missing > 0 or s.device_not_found > 0
                     or s.device_status_conflict > 0 or s.borrower_not_found > 0
                     or s.duplicate > 0)
        if has_issue:
            tip_text = ("提示：存在待修正的问题（见上方明细），【确认导入】已禁用；"
                        "必须全部记录合法才可导入，否则整批不会写入任何一行。")
            tip_color = "#c0392b"
        else:
            tip_text = ("提示：所有记录均通过预检，点击【确认导入】将整批写入；"
                        "若中途异常会自动回滚，不留半条记录。")
            tip_color = "#2980b9"
        tip = ttk.Label(main, text=tip_text, foreground=tip_color)
        tip.pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(main)
        btns.pack(pady=(10, 0))
        ok_btn = ttk.Button(btns, text="确认导入", command=self._ok)
        s = self.summary
        has_issue = (s.field_missing > 0 or s.device_not_found > 0
                     or s.device_status_conflict > 0 or s.borrower_not_found > 0
                     or s.duplicate > 0)
        if has_issue:
            ok_btn.config(state="disabled")
        ok_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

    def _ok(self):
        self.confirmed = True
        self.destroy()


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
