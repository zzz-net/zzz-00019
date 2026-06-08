import os
import copy
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
from models import (
    Device, Borrower, BorrowRecord, User, Accessory,
    DeviceStatus, RecordStatus, UserRole, _now_str,
    ImportPrecheckSummary, ImportLogEntry, MaintenanceRecord,
    InventorySession, InventoryItem, InventoryStatus, InventoryItemResult,
    HandoffRecord, HandoffAction, HandoffStatus,
    DeviceAccessory, AccessoryType
)
import storage


class BusinessError(Exception):
    pass


class EquipmentManager:
    def __init__(self):
        self.devices: List[Device] = []
        self.borrowers: List[Borrower] = []
        self.records: List[BorrowRecord] = []
        self.users: List[User] = []
        self.maintenance_logs: List[MaintenanceRecord] = []
        self.inventory_sessions: List[InventorySession] = []
        self.handoff_records: List[HandoffRecord] = []
        self.accessories: List[DeviceAccessory] = []
        self.config = storage.AppConfig()
        self.current_user: Optional[User] = None
        self._records_snapshot_at_last_maintenance: Dict[str, str] = {}
        self.load_all()

    def load_all(self):
        storage.seed_sample_data()
        self.devices = storage.load_devices()
        self.borrowers = storage.load_borrowers()
        self.records = storage.load_records()
        self.users = storage.load_users()
        self.maintenance_logs = storage.load_maintenance_logs()
        self.inventory_sessions = storage.load_inventory_sessions()
        self.handoff_records = storage.load_handoff_records()
        self.accessories = storage.load_accessories()
        self.config = storage.load_config()
        self._records_snapshot_at_last_maintenance = dict(
            self.config.maintenance_records_snapshot or {}
        )
        if self.config.last_user:
            self.current_user = self.find_user(self.config.last_user)

    def save_all(self):
        storage.save_devices(self.devices)
        storage.save_borrowers(self.borrowers)
        storage.save_records(self.records)
        storage.save_users(self.users)
        storage.save_maintenance_logs(self.maintenance_logs)
        storage.save_inventory_sessions(self.inventory_sessions)
        storage.save_handoff_records(self.handoff_records)
        storage.save_accessories(self.accessories)
        storage.save_config(self.config)

    def find_user(self, username: str) -> Optional[User]:
        return next((u for u in self.users if u.username == username), None)

    def find_device(self, device_id: str) -> Optional[Device]:
        return next((d for d in self.devices if d.id == device_id), None)

    def find_borrower(self, borrower_id: str) -> Optional[Borrower]:
        return next((b for b in self.borrowers if b.id == borrower_id), None)

    def find_record(self, record_id: str) -> Optional[BorrowRecord]:
        return next((r for r in self.records if r.id == record_id), None)

    def get_active_record_for_device(self, device_id: str) -> Optional[BorrowRecord]:
        for r in self.records:
            if r.device_id == device_id and r.status in (
                RecordStatus.BORROWED, RecordStatus.INSPECTING
            ):
                return r
        return None

    def switch_user(self, username: str) -> User:
        user = self.find_user(username)
        if not user:
            raise BusinessError(f"用户不存在: {username}")
        self.current_user = user
        self.config.last_user = username
        self.save_all()
        return user

    def has_permission(self, permission: str) -> bool:
        if not self.current_user:
            return False
        return UserRole.has_permission(self.current_user.role, permission)

    def _require_permission(self, permission: str):
        if not self.has_permission(permission):
            role = self.current_user.role if self.current_user else "未登录"
            raise BusinessError(f"当前角色【{role}】无权限执行此操作")

    def add_device(self, name: str, category: str, model: str = "",
                   serial_no: str = "", accessories: List[Accessory] = None,
                   remark: str = "") -> Device:
        self._require_permission("add_device")
        if not name.strip():
            raise BusinessError("设备名称不能为空")
        device = Device(
            name=name.strip(), category=category.strip(),
            model=model.strip(), serial_no=serial_no.strip(),
            accessories=accessories or [], remark=remark.strip()
        )
        self.devices.append(device)
        self.save_all()
        return device

    def update_device(self, device_id: str, **kwargs) -> Device:
        self._require_permission("edit_device")
        device = self.find_device(device_id)
        if not device:
            raise BusinessError("设备不存在")
        for k, v in kwargs.items():
            if hasattr(device, k):
                setattr(device, k, v)
        self.save_all()
        return device

    def delete_device(self, device_id: str):
        self._require_permission("delete_device")
        device = self.find_device(device_id)
        if not device:
            raise BusinessError("设备不存在")
        active = self.get_active_record_for_device(device_id)
        if active:
            raise BusinessError("该设备存在进行中的借用记录，无法删除")
        if device.status == DeviceStatus.MAINTENANCE:
            raise BusinessError(
                f"设备【{device.name}】正在维修/保养中，无法删除。"
                f"请先撤销维修登记或待维修完成。"
            )
        self.devices.remove(device)
        self.save_all()

    def add_borrower(self, name: str, department: str = "",
                     phone: str = "") -> Borrower:
        self._require_permission("add_borrower")
        if not name.strip():
            raise BusinessError("借用人姓名不能为空")
        borrower = Borrower(
            name=name.strip(), department=department.strip(),
            phone=phone.strip()
        )
        self.borrowers.append(borrower)
        self.save_all()
        return borrower

    def borrow_device(self, device_id: str, borrower_id: str,
                      expected_return_time: str = "",
                      accessories: List[Accessory] = None,
                      remark: str = "") -> BorrowRecord:
        self._require_permission("borrow_device")
        device = self.find_device(device_id)
        borrower = self.find_borrower(borrower_id)
        if not device:
            raise BusinessError("设备不存在")
        if not borrower:
            raise BusinessError("借用人不存在")

        if device.status == DeviceStatus.BORROWED:
            raise BusinessError(
                f"设备【{device.name}】已借出，不能再次借出。"
                f"请先归还后再操作。"
            )
        if device.status == DeviceStatus.FROZEN:
            raise BusinessError(
                f"设备【{device.name}】处于异常冻结状态，不能借出。"
            )
        if device.status == DeviceStatus.MAINTENANCE:
            raise BusinessError(
                f"设备【{device.name}】正在维修/保养中，不能借出。"
                f"请待维修完成恢复可用后再操作。"
            )

        missing_required = []
        if accessories:
            for acc in accessories:
                if acc.required and not acc.present:
                    missing_required.append(acc.name)
        if missing_required:
            raise BusinessError(
                f"缺少必备配件：{', '.join(missing_required)}。"
                f"借出前请确认配件齐全。"
            )

        from_status = device.status
        device.status = DeviceStatus.BORROWED

        record = BorrowRecord(
            device_id=device.id, device_name=device.name,
            borrower_id=borrower.id, borrower_name=borrower.name,
            borrower_department=borrower.department,
            expected_return_time=expected_return_time,
            status=RecordStatus.BORROWED,
            accessories_check_out=accessories or [
                Accessory(name=a.name, required=a.required, present=a.present)
                for a in device.accessories
            ],
            check_out_operator=self.current_user.username
            if self.current_user else "",
            remark=remark
        )
        record.add_history(
            from_status, RecordStatus.BORROWED,
            self.current_user.username if self.current_user else "system",
            self.current_user.role if self.current_user else UserRole.ADMIN,
            remark or "借出登记"
        )
        self.records.append(record)
        self.save_all()
        return record

    def submit_return(self, record_id: str,
                      accessories: List[Accessory] = None,
                      remark: str = "") -> BorrowRecord:
        self._require_permission("return_device")
        record = self.find_record(record_id)
        if not record:
            raise BusinessError("借用记录不存在")
        if record.status != RecordStatus.BORROWED:
            raise BusinessError(
                f"当前记录状态为【{record.status}】，无法提交归还。"
            )

        device = self.find_device(record.device_id)
        from_status = record.status
        record.status = RecordStatus.INSPECTING
        if device:
            device.status = DeviceStatus.INSPECTING
        record.check_in_operator = (
            self.current_user.username if self.current_user else ""
        )
        record.accessories_check_in = accessories or []
        if remark:
            record.remark = (record.remark + "\n" if record.remark else "") + remark
        record.add_history(
            from_status, RecordStatus.INSPECTING,
            self.current_user.username if self.current_user else "system",
            self.current_user.role if self.current_user else UserRole.ADMIN,
            remark or "提交归还，等待验收"
        )
        self.save_all()
        return record

    def inspect_return(self, record_id: str,
                       accessories: List[Accessory],
                       inspect_remark: str = "",
                       force_accept: bool = False) -> Tuple[BorrowRecord, bool]:
        self._require_permission("inspect_return")
        record = self.find_record(record_id)
        if not record:
            raise BusinessError("借用记录不存在")
        if record.status != RecordStatus.INSPECTING:
            raise BusinessError(
                f"当前记录状态为【{record.status}】，无需验收。"
            )

        missing_required = []
        for acc in accessories:
            if acc.required and not acc.present:
                missing_required.append(acc.name)

        device = self.find_device(record.device_id)
        frozen = False
        from_status = record.status

        if missing_required and not force_accept:
            record.status = RecordStatus.FROZEN
            if device:
                device.status = DeviceStatus.FROZEN
            frozen = True
            status_msg = RecordStatus.FROZEN
        else:
            record.status = RecordStatus.RETURNED
            record.actual_return_time = _now_str()
            if device:
                device.status = DeviceStatus.AVAILABLE
            status_msg = RecordStatus.RETURNED

        record.accessories_check_in = accessories
        record.inspect_operator = (
            self.current_user.username if self.current_user else ""
        )
        record.inspect_remark = inspect_remark
        record.add_history(
            from_status, status_msg,
            self.current_user.username if self.current_user else "system",
            self.current_user.role if self.current_user else UserRole.ADMIN,
            (f"验收完成，缺少必备配件：{', '.join(missing_required)}，进入异常冻结"
             if frozen else
             ("验收通过，完成归还" + (f"（强制接收，缺少：{', '.join(missing_required)}）"
                                      if missing_required else "")))
            + (f" 备注：{inspect_remark}" if inspect_remark else "")
        )
        self.save_all()
        return record, frozen

    def close_record(self, record_id: str, remark: str = "") -> BorrowRecord:
        self._require_permission("close_record")
        record = self.find_record(record_id)
        if not record:
            raise BusinessError("借用记录不存在")
        if record.status != RecordStatus.FROZEN:
            raise BusinessError(
                f"当前记录状态为【{record.status}】，只有异常冻结记录需要关闭。"
            )

        if (self.current_user and
                self.current_user.role == UserRole.BORROWER):
            raise BusinessError(
                "借用人不能代替验收人关闭冻结记录。"
                "请联系验收人或管理员处理。"
            )

        from_status = record.status
        record.status = RecordStatus.RETURNED
        record.actual_return_time = _now_str()
        device = self.find_device(record.device_id)
        if device:
            device.status = DeviceStatus.AVAILABLE
        record.close_operator = (
            self.current_user.username if self.current_user else ""
        )
        record.add_history(
            from_status, RecordStatus.RETURNED,
            self.current_user.username if self.current_user else "system",
            self.current_user.role if self.current_user else UserRole.ADMIN,
            remark or "关闭冻结记录，标记为已归还"
        )
        self.save_all()
        return record

    def freeze_device(self, device_id: str, reason: str = "") -> Device:
        self._require_permission("freeze_device")
        device = self.find_device(device_id)
        if not device:
            raise BusinessError("设备不存在")
        device.status = DeviceStatus.FROZEN
        device.remark = (device.remark + "\n" if device.remark else "") + \
                        f"[{_now_str()}] 冻结原因：{reason or '未说明'}"
        self.save_all()
        return device

    def unfreeze_device(self, device_id: str, reason: str = "") -> Device:
        self._require_permission("unfreeze_device")
        device = self.find_device(device_id)
        if not device:
            raise BusinessError("设备不存在")
        if device.status != DeviceStatus.FROZEN:
            raise BusinessError("设备未处于冻结状态")
        active = self.get_active_record_for_device(device_id)
        if active and active.status == RecordStatus.FROZEN:
            raise BusinessError(
                "该设备存在冻结中的借用记录，"
                "请先关闭记录后再解冻设备。"
            )
        device.status = DeviceStatus.AVAILABLE
        device.remark = (device.remark + "\n" if device.remark else "") + \
                        f"[{_now_str()}] 已解冻：{reason or '未说明'}"
        self.save_all()
        return device

    def set_export_dir(self, export_dir: str) -> Tuple[bool, str]:
        ok, reason = storage.check_dir_writable(export_dir)
        if not ok:
            return False, (
                f"导出目录设置失败：{reason}\n"
                f"请选择一个已存在且当前用户有写入权限的目录。\n"
                f"（不会自动创建不存在的子目录）"
            )
        self.config.export_dir = export_dir
        self.save_all()
        return True, "导出目录设置成功"

    def can_write_to_export_dir(self) -> bool:
        return storage.is_dir_writable(self.config.export_dir)

    def check_export_dir_detail(self) -> Tuple[bool, str]:
        return storage.check_dir_writable(self.config.export_dir)

    def export_selected_records(self, record_ids: List[str],
                                filepath: str,
                                filter_info: Optional[dict] = None) -> Tuple[bool, str]:
        ok, reason = self.check_export_dir_detail()
        if not ok:
            return False, (
                f"导出失败：{reason}\n"
                f"请先设置一个可写的导出目录。\n"
                f"已选记录数据未做任何改动。"
            )
        selected = [r for r in self.records if r.id in record_ids]
        if filepath.lower().endswith(".csv"):
            ok = storage.export_records_csv(selected, filepath, filter_info)
        else:
            ok = storage.export_records_json(selected, filepath, filter_info)
        if not ok:
            return False, (
                f"导出失败，目标文件无法写入：{filepath}\n"
                f"请检查路径是否在导出目录下、文件是否被占用。\n"
                f"已选记录数据未做任何改动。"
            )
        return True, f"导出成功：{filepath}"

    def export_all_devices(self, filepath: str) -> Tuple[bool, str]:
        ok, reason = self.check_export_dir_detail()
        if not ok:
            return False, (
                f"导出失败：{reason}\n"
                f"请先设置一个可写的导出目录。\n"
                f"设备数据未做任何改动。"
            )
        if filepath.lower().endswith(".csv"):
            ok = storage.export_devices_csv(self.devices, filepath)
        else:
            ok = storage.export_devices_json(self.devices, filepath)
        if not ok:
            return False, (
                f"导出失败，目标文件无法写入：{filepath}\n"
                f"请检查路径是否在导出目录下、文件是否被占用。\n"
                f"设备数据未做任何改动。"
            )
        return True, f"导出成功：{filepath}"

    def get_filtered_records(self) -> List[BorrowRecord]:
        if (self.current_user and
                self.current_user.role == UserRole.BORROWER):
            return [r for r in self.records
                    if r.borrower_name == self.current_user.display_name
                    or r.borrower_id == self.current_user.username]
        return self.records

    @staticmethod
    def _parse_datetime(s: str) -> Optional[datetime]:
        if not s:
            return None
        s = s.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    def is_overdue(self, record: BorrowRecord) -> bool:
        if record.status == RecordStatus.RETURNED:
            return False
        dt = self._parse_datetime(record.expected_return_time)
        if not dt:
            return False
        return datetime.now() > dt

    def is_due_soon(self, record: BorrowRecord, days: Optional[int] = None) -> bool:
        if record.status == RecordStatus.RETURNED:
            return False
        if self.is_overdue(record):
            return False
        dt = self._parse_datetime(record.expected_return_time)
        if not dt:
            return False
        threshold_days = days if days is not None else self.config.reminder_days
        return datetime.now() <= dt <= datetime.now() + timedelta(days=threshold_days)

    def get_record_alert_status(self, record: BorrowRecord) -> str:
        if self.is_overdue(record):
            return "overdue"
        if self.is_due_soon(record):
            return "due_soon"
        return "normal"

    def set_reminder_days(self, days: int) -> Tuple[bool, str]:
        self._require_permission("set_reminder_days")
        try:
            days_int = int(days)
        except (ValueError, TypeError):
            return False, "提醒天数必须是正整数"
        if days_int <= 0:
            return False, "提醒天数必须大于 0"
        if days_int > 365:
            return False, "提醒天数不能超过 365 天"
        self.config.reminder_days = days_int
        self.save_all()
        return True, f"提醒天数已设置为 {days_int} 天"

    def get_reminder_days(self) -> int:
        return self.config.reminder_days

    def filter_records_by_alert(self,
                                records: List[BorrowRecord],
                                alert_filter: str) -> List[BorrowRecord]:
        if alert_filter == "all":
            return list(records)
        elif alert_filter == "returned":
            return [r for r in records if r.status == RecordStatus.RETURNED]
        elif alert_filter == "overdue":
            return [r for r in records if self.is_overdue(r)]
        elif alert_filter == "due_soon":
            return [r for r in records if self.is_due_soon(r)]
        return list(records)

    def _make_row_issue(self, row: dict, kind: str, detail: str) -> dict:
        return {
            "row": row.get("_row", "?"),
            "kind": kind,
            "detail": detail,
            "device_id": row.get("device_id", ""),
            "borrower_id": row.get("borrower_id", ""),
        }

    def precheck_import_file(self, filepath: str) -> Tuple[bool, str, ImportPrecheckSummary]:
        self._require_permission("import_records")

        ok, msg, rows, fmt = storage.parse_import_file(filepath)
        if not ok:
            return False, msg, ImportPrecheckSummary()

        self.config.last_import_dir = os.path.dirname(filepath)
        self.config.last_import_format = fmt

        summary = ImportPrecheckSummary(total=len(rows))
        seen_keys = set()

        for row in rows:
            issues_for_row = []

            missing_fields = []
            for f in storage.IMPORT_REQUIRED_FIELDS:
                val = row.get(f, "")
                if val is None or (isinstance(val, str) and not val.strip()):
                    missing_fields.append(f)
            if missing_fields:
                summary.field_missing += 1
                issues_for_row.append(self._make_row_issue(
                    row, "字段缺失",
                    f"缺少必填字段：{', '.join(missing_fields)}"
                ))

            device = None
            if not issues_for_row or "device_id" not in missing_fields:
                device_id = str(row.get("device_id", "")).strip()
                device = self.find_device(device_id)
                if not device:
                    summary.device_not_found += 1
                    issues_for_row.append(self._make_row_issue(
                        row, "设备不存在",
                        f"设备ID【{device_id}】在系统中不存在"
                    ))

            borrower = None
            if not issues_for_row or "borrower_id" not in missing_fields:
                borrower_id = str(row.get("borrower_id", "")).strip()
                borrower = self.find_borrower(borrower_id)
                if not borrower:
                    summary.borrower_not_found += 1
                    issues_for_row.append(self._make_row_issue(
                        row, "借用人不存在",
                        f"借用人ID【{borrower_id}】在系统中不存在"
                    ))

            if device and device.status in (DeviceStatus.BORROWED, DeviceStatus.INSPECTING):
                active = self.get_active_record_for_device(device.id)
                if active:
                    summary.device_status_conflict += 1
                    issues_for_row.append(self._make_row_issue(
                        row, "设备状态冲突",
                        f"设备【{device.name}】当前状态为【{device.status}】，"
                        f"已有进行中的借用记录"
                    ))

            if device and device.status == DeviceStatus.MAINTENANCE:
                row_status = str(row.get("status", "")).strip() or RecordStatus.BORROWED
                if row_status in (RecordStatus.BORROWED, RecordStatus.INSPECTING):
                    summary.device_status_conflict += 1
                    issues_for_row.append(self._make_row_issue(
                        row, "设备状态冲突",
                        f"设备【{device.name}】当前为【维修中】，"
                        f"不能导入为【{row_status}】状态"
                    ))

            dup_key = None
            if device and borrower:
                dup_key = (device.id, borrower.id, str(row.get("borrow_time", "")).strip())
                if dup_key in seen_keys:
                    summary.duplicate += 1
                    issues_for_row.append(self._make_row_issue(
                        row, "重复记录",
                        f"同一文件内：设备【{device.id}】+ 借用人【{borrower.id}】"
                        f"+ 借出时间相同"
                    ))
                else:
                    for existing in self.records:
                        if (existing.device_id == device.id
                                and existing.borrower_id == borrower.id
                                and existing.borrow_time == str(row.get("borrow_time", "")).strip()):
                            summary.duplicate += 1
                            issues_for_row.append(self._make_row_issue(
                                row, "重复记录",
                                f"与已有记录【{existing.id}】重复：相同设备、借用人、借出时间"
                            ))
                            break

            if dup_key and not any(i["kind"] == "重复记录" for i in issues_for_row):
                seen_keys.add(dup_key)

            if issues_for_row:
                summary.issues.extend(issues_for_row)
            else:
                summary.importable += 1

        self.config.last_import_summary = summary.to_dict()
        self.save_all()

        return True, "", summary

    def commit_import(self, filepath: str) -> Tuple[bool, str, int, int]:
        self._require_permission("import_records")

        ok, msg, rows, fmt = storage.parse_import_file(filepath)
        if not ok:
            self._append_import_log(filepath, fmt, 0, 0, 0, [msg])
            return False, msg, 0, 0

        pre_ok, pre_msg, summary = self.precheck_import_file(filepath)
        if not pre_ok:
            self._append_import_log(filepath, fmt, len(rows), 0, len(rows), [pre_msg])
            return False, pre_msg, 0, len(rows)
        has_issue = (
            summary.field_missing > 0 or summary.device_not_found > 0
            or summary.device_status_conflict > 0 or summary.borrower_not_found > 0
            or summary.duplicate > 0
        )
        if has_issue:
            parts = []
            if summary.field_missing:
                parts.append(f"字段缺失 {summary.field_missing}")
            if summary.device_not_found:
                parts.append(f"设备不存在 {summary.device_not_found}")
            if summary.device_status_conflict:
                parts.append(f"设备状态冲突 {summary.device_status_conflict}")
            if summary.borrower_not_found:
                parts.append(f"借用人不存在 {summary.borrower_not_found}")
            if summary.duplicate:
                parts.append(f"重复记录 {summary.duplicate}")
            reason = (
                "预检发现问题，整批未写入（必须全部合法才可导入："
                + "；".join(parts)
                + "。"
            )
            self._append_import_log(
                filepath, fmt, len(rows), 0, len(rows), [reason]
            )
            return False, reason, 0, len(rows)

        devices_backup = copy.deepcopy(self.devices)
        records_backup = copy.deepcopy(self.records)
        device_state: Dict[str, str] = {d.id: d.status for d in self.devices}

        success_count = 0
        fail_count = 0
        fail_reasons = []
        imported_records: List[BorrowRecord] = []

        try:
            for row in rows:
                missing = [f for f in storage.IMPORT_REQUIRED_FIELDS
                           if not str(row.get(f, "")).strip()]
                if missing:
                    fail_count += 1
                    fail_reasons.append(f"第{row.get('_row','?')}行: 字段缺失 {', '.join(missing)}")
                    continue

                device_id = str(row.get("device_id", "")).strip()
                borrower_id = str(row.get("borrower_id", "")).strip()
                borrow_time = str(row.get("borrow_time", "")).strip()

                device = self.find_device(device_id)
                if not device:
                    fail_count += 1
                    fail_reasons.append(f"第{row.get('_row','?')}行: 设备不存在【{device_id}】")
                    continue

                borrower = self.find_borrower(borrower_id)
                if not borrower:
                    fail_count += 1
                    fail_reasons.append(f"第{row.get('_row','?')}行: 借用人不存在【{borrower_id}】")
                    continue

                if device_state.get(device.id) in (DeviceStatus.BORROWED, DeviceStatus.INSPECTING):
                    fail_count += 1
                    fail_reasons.append(f"第{row.get('_row','?')}行: 设备状态冲突【{device.name}】")
                    continue

                is_dup = False
                for existing in imported_records + self.records:
                    if (existing.device_id == device.id
                            and existing.borrower_id == borrower.id
                            and existing.borrow_time == borrow_time):
                        is_dup = True
                        break
                if is_dup:
                    fail_count += 1
                    fail_reasons.append(f"第{row.get('_row','?')}行: 重复记录")
                    continue

                status_str = str(row.get("status", "")).strip() or RecordStatus.BORROWED

                if device_state.get(device.id) == DeviceStatus.MAINTENANCE:
                    if status_str in (RecordStatus.BORROWED, RecordStatus.INSPECTING):
                        fail_count += 1
                        fail_reasons.append(
                            f"第{row.get('_row','?')}行: 设备【{device.name}】维修中，不能导入为借出中/验收中"
                        )
                        continue
                valid_statuses = [RecordStatus.BORROWED, RecordStatus.INSPECTING,
                                  RecordStatus.RETURNED, RecordStatus.FROZEN]
                if status_str not in valid_statuses:
                    status_str = RecordStatus.BORROWED

                from_status = device_state.get(device.id, DeviceStatus.AVAILABLE)

                if status_str == RecordStatus.BORROWED:
                    new_device_status = DeviceStatus.BORROWED
                elif status_str == RecordStatus.INSPECTING:
                    new_device_status = DeviceStatus.INSPECTING
                elif status_str == RecordStatus.RETURNED:
                    new_device_status = DeviceStatus.AVAILABLE
                elif status_str == RecordStatus.FROZEN:
                    new_device_status = DeviceStatus.FROZEN
                else:
                    new_device_status = DeviceStatus.BORROWED

                device.status = new_device_status
                device_state[device.id] = new_device_status

                record = BorrowRecord(
                    device_id=device.id,
                    device_name=device.name,
                    borrower_id=borrower.id,
                    borrower_name=borrower.name,
                    borrower_department=borrower.department,
                    borrow_time=borrow_time,
                    expected_return_time=str(row.get("expected_return_time", "")).strip(),
                    actual_return_time=str(row.get("actual_return_time", "")).strip(),
                    status=status_str,
                    check_out_operator=str(row.get("check_out_operator", "")).strip()
                                      or (self.current_user.username if self.current_user else ""),
                    check_in_operator=str(row.get("check_in_operator", "")).strip(),
                    inspect_operator=str(row.get("inspect_operator", "")).strip(),
                    close_operator=str(row.get("close_operator", "")).strip(),
                    inspect_remark=str(row.get("inspect_remark", "")).strip(),
                    remark=str(row.get("remark", "")).strip(),
                )
                record.add_history(
                    from_status, status_str,
                    self.current_user.username if self.current_user else "system",
                    self.current_user.role if self.current_user else UserRole.ADMIN,
                    f"批量导入（来自文件：{os.path.basename(filepath)}）"
                )
                self.records.append(record)
                imported_records.append(record)
                success_count += 1

            self.save_all()
            self._append_import_log(filepath, fmt, len(rows), success_count, fail_count, fail_reasons)
            return True, f"成功导入 {success_count} 条，失败 {fail_count} 条", success_count, fail_count

        except Exception as e:
            self.devices = devices_backup
            self.records = records_backup
            try:
                self.save_all()
            except Exception:
                pass
            rollback_reason = f"导入过程发生异常，整批已回滚：{e}"
            self._append_import_log(filepath, fmt, len(rows), 0, len(rows), [rollback_reason])
            return False, rollback_reason, 0, 0

    def _append_import_log(self, filepath: str, fmt: str, total: int,
                           success: int, fail: int, reasons: List[str]):
        try:
            entry = ImportLogEntry(
                timestamp=_now_str(),
                operator=self.current_user.username if self.current_user else "",
                operator_role=self.current_user.role if self.current_user else "",
                file_path=filepath,
                file_format=fmt,
                total=total,
                success_count=success,
                fail_count=fail,
                fail_reasons=reasons,
            )
            storage.append_import_log(entry)
        except Exception:
            pass

    def get_import_logs(self) -> List[ImportLogEntry]:
        self._require_permission("import_records")
        return storage.load_import_logs()

    def get_last_import_info(self) -> dict:
        self._require_permission("import_records")
        return {
            "last_import_dir": self.config.last_import_dir,
            "last_import_format": self.config.last_import_format,
            "last_import_summary": self.config.last_import_summary,
        }

    def _make_records_snapshot(self) -> Dict[str, str]:
        snap = {}
        for r in self.records:
            snap[r.id] = r.status + "|" + (r.actual_return_time or "")
        return snap

    def send_to_maintenance(self, device_id: str, reason: str,
                            expected_recover_time: str = "") -> Tuple[MaintenanceRecord, str]:
        self._require_permission("send_to_maintenance")
        device = self.find_device(device_id)
        if not device:
            raise BusinessError("设备不存在")
        if device.status not in (DeviceStatus.AVAILABLE, DeviceStatus.FROZEN):
            raise BusinessError(
                f"设备【{device.name}】当前状态为【{device.status}】，"
                f"仅【可借出】或【异常冻结】的设备可登记维修/保养。"
            )
        active = self.get_active_record_for_device(device_id)
        if active:
            raise BusinessError(
                f"设备【{device.name}】存在进行中的借用记录（状态：{active.status}），"
                f"不能登记维修。请先完成归还流程。"
            )
        if not reason or not str(reason).strip():
            raise BusinessError("请填写维修/保养原因")

        from_status = device.status
        device.status = DeviceStatus.MAINTENANCE
        device.remark = (device.remark + "\n" if device.remark else "") + \
                        f"[{_now_str()}] 状态变更：{from_status} → {DeviceStatus.MAINTENANCE}（送修/保养：{reason.strip()}）"

        rec = MaintenanceRecord(
            device_id=device.id,
            device_name=device.name,
            from_status=from_status,
            reason=reason.strip(),
            expected_recover_time=expected_recover_time.strip() if expected_recover_time else "",
            operator=self.current_user.username if self.current_user else "",
            operator_role=self.current_user.role if self.current_user else "",
            status="in_progress",
        )
        self.maintenance_logs.append(rec)
        snap = self._make_records_snapshot()
        self._records_snapshot_at_last_maintenance = snap
        self.config.maintenance_records_snapshot = snap
        self.save_all()
        return rec, f"设备【{device.name}】已登记为维修/保养（原因：{reason.strip()}）"

    def get_active_maintenance_for_device(self, device_id: str) -> Optional[MaintenanceRecord]:
        for m in reversed(self.maintenance_logs):
            if m.device_id == device_id and m.status == "in_progress":
                return m
        return None

    def can_cancel_maintenance(self, device_id: str) -> Tuple[bool, str]:
        active_m = self.get_active_maintenance_for_device(device_id)
        if not active_m:
            return False, "该设备没有进行中的维修登记"
        current_snap = self._make_records_snapshot()
        if self._records_snapshot_at_last_maintenance and \
                self._records_snapshot_at_last_maintenance != current_snap:
            return False, "送修登记后已有借用/归还记录发生变化，无法撤销"
        return True, ""

    def cancel_last_maintenance(self, device_id: str, remark: str = "") -> Tuple[MaintenanceRecord, str]:
        self._require_permission("cancel_maintenance")
        device = self.find_device(device_id)
        if not device:
            raise BusinessError("设备不存在")
        can, reason = self.can_cancel_maintenance(device_id)
        if not can:
            raise BusinessError(f"无法撤销维修登记：{reason}")
        active_m = self.get_active_maintenance_for_device(device_id)
        if not active_m:
            raise BusinessError("该设备没有进行中的维修登记")
        if device.status != DeviceStatus.MAINTENANCE:
            raise BusinessError(f"设备当前状态为【{device.status}】，不是维修中，无法撤销")

        recover_to = active_m.from_status or DeviceStatus.AVAILABLE
        if recover_to not in (DeviceStatus.AVAILABLE, DeviceStatus.FROZEN):
            recover_to = DeviceStatus.AVAILABLE
        device.status = recover_to
        device.remark = (device.remark + "\n" if device.remark else "") + \
                        f"[{_now_str()}] 状态变更：{DeviceStatus.MAINTENANCE} → {recover_to}（撤销维修：{remark.strip() if remark else '未说明'}）"

        active_m.status = "cancelled"
        active_m.end_time = _now_str()
        active_m.cancel_remark = remark.strip() if remark else ""
        self._records_snapshot_at_last_maintenance = {}
        self.config.maintenance_records_snapshot = {}
        self.save_all()
        return active_m, f"已撤销维修登记，设备恢复为【{recover_to}】"

    def get_maintenance_logs(self) -> List[MaintenanceRecord]:
        self._require_permission("view_maintenance")
        return list(self.maintenance_logs)

    def filter_maintenance_logs(self,
                                logs: List[MaintenanceRecord],
                                device_id: str = "",
                                status_filter: str = "all",
                                start_from: str = "",
                                start_to: str = "") -> List[MaintenanceRecord]:
        result = list(logs)
        if device_id and device_id.strip():
            did = device_id.strip()
            result = [m for m in result if m.device_id == did]
        if status_filter and status_filter != "all":
            if status_filter == "in_progress":
                result = [m for m in result if m.status == "in_progress"]
            elif status_filter == "cancelled":
                result = [m for m in result if m.status == "cancelled"]
        if start_from and start_from.strip():
            dt_from = self._parse_datetime(start_from.strip())
            if dt_from:
                result = [m for m in result
                          if self._parse_datetime(m.start_time)
                          and self._parse_datetime(m.start_time) >= dt_from]
        if start_to and start_to.strip():
            dt_to = self._parse_datetime(start_to.strip())
            if dt_to:
                result = [m for m in result
                          if self._parse_datetime(m.start_time)
                          and self._parse_datetime(m.start_time) <= dt_to]
        return result

    def export_maintenance_logs(self, log_ids: List[str],
                                filepath: str,
                                filter_info: Optional[dict] = None) -> Tuple[bool, str]:
        self._require_permission("export_maintenance")
        ok, reason = self.check_export_dir_detail()
        if not ok:
            return False, (
                f"导出失败：{reason}\n"
                f"请先设置一个可写的导出目录。"
            )
        selected = [m for m in self.maintenance_logs if m.id in log_ids]
        if filepath.lower().endswith(".csv"):
            ok = storage.export_maintenance_csv(selected, filepath, filter_info)
        else:
            ok = storage.export_maintenance_json(selected, filepath, filter_info)
        if not ok:
            return False, f"导出失败，目标文件无法写入：{filepath}"
        return True, f"导出成功：{filepath}"

    def set_default_maintenance_days(self, days: int) -> Tuple[bool, str]:
        self._require_permission("send_to_maintenance")
        try:
            days_int = int(days)
        except (ValueError, TypeError):
            return False, "默认维修天数必须是正整数"
        if days_int <= 0:
            return False, "默认维修天数必须大于 0"
        if days_int > 365:
            return False, "默认维修天数不能超过 365 天"
        self.config.default_maintenance_days = days_int
        self.save_all()
        return True, f"默认维修天数已设置为 {days_int} 天"

    def get_default_maintenance_days(self) -> int:
        return self.config.default_maintenance_days

    def save_maintenance_filter(self, flt: dict):
        try:
            self.config.last_maintenance_filter = dict(flt) if flt else {}
            self.save_all()
        except Exception:
            pass

    def get_last_maintenance_filter(self) -> dict:
        return dict(self.config.last_maintenance_filter or {})

    def find_inventory_session(self, session_id: str) -> Optional[InventorySession]:
        return next((s for s in self.inventory_sessions if s.id == session_id), None)

    def _has_device_active_business(self, device_id: str) -> Tuple[bool, str]:
        device = self.find_device(device_id)
        if not device:
            return False, ""
        if device.status == DeviceStatus.BORROWED:
            active = self.get_active_record_for_device(device_id)
            if active:
                return True, f"设备【{device.name}】已借出，借用人：{active.borrower_name}"
        if device.status == DeviceStatus.INSPECTING:
            return True, f"设备【{device.name}】处于归还验收中"
        if device.status == DeviceStatus.MAINTENANCE:
            active_m = self.get_active_maintenance_for_device(device_id)
            if active_m:
                return True, f"设备【{device.name}】正在维修/保养中，原因：{active_m.reason}"
        if device.status == DeviceStatus.FROZEN:
            return True, f"设备【{device.name}】处于异常冻结状态"
        return False, ""

    def _filter_devices_for_inventory(self, category: str = "",
                                       status_filter: str = "all",
                                       keyword: str = "",
                                       storage_location: str = "",
                                       responsible_person: str = "") -> List[Device]:
        result = list(self.devices)
        if category and category.strip():
            cat = category.strip()
            result = [d for d in result if d.category == cat]
        if status_filter and status_filter != "all":
            result = [d for d in result if d.status == status_filter]
        if storage_location and storage_location.strip():
            loc = storage_location.strip()
            result = [d for d in result if d.storage_location == loc]
        if responsible_person and responsible_person.strip():
            rp = responsible_person.strip()
            result = [d for d in result if d.responsible_person == rp]
        if keyword and keyword.strip():
            kw = keyword.strip().lower()
            result = [d for d in result
                      if kw in d.name.lower()
                      or kw in (d.model or "").lower()
                      or kw in (d.serial_no or "").lower()
                      or kw in d.id.lower()
                      or kw in (d.storage_location or "").lower()
                      or kw in (d.responsible_person or "").lower()]
        return result

    def create_inventory(self, title: str, category: str = "",
                         status_filter: str = "all", keyword: str = "",
                         storage_location: str = "", responsible_person: str = "",
                         device_ids: Optional[List[str]] = None,
                         remark: str = "") -> InventorySession:
        self._require_permission("create_inventory")
        if not title or not str(title).strip():
            raise BusinessError("盘点标题不能为空")

        if device_ids:
            selected_devices = [d for d in self.devices if d.id in device_ids]
            if not selected_devices:
                raise BusinessError("未选中任何有效设备")
        else:
            selected_devices = self._filter_devices_for_inventory(
                category, status_filter, keyword,
                storage_location, responsible_person
            )
            if not selected_devices:
                raise BusinessError("当前筛选条件下没有符合条件的设备")

        items: List[InventoryItem] = []
        for dev in selected_devices:
            items.append(InventoryItem(
                device_id=dev.id,
                device_name=dev.name,
                original_status=dev.status,
            ))

        filter_conditions = {
            "title": title.strip(),
            "category": category or "",
            "status_filter": status_filter or "all",
            "keyword": keyword or "",
            "storage_location": storage_location or "",
            "responsible_person": responsible_person or "",
            "manual_device_count": len(device_ids) if device_ids else 0,
            "total_devices": len(selected_devices),
        }

        session = InventorySession(
            title=title.strip(),
            status=InventoryStatus.DRAFT,
            created_by=self.current_user.username if self.current_user else "",
            created_by_role=self.current_user.role if self.current_user else "",
            filter_conditions=filter_conditions,
            items=items,
            remark=remark.strip() if remark else "",
        )
        self.inventory_sessions.append(session)
        self.config.last_active_inventory_session_id = session.id
        self.save_all()
        return session

    def get_inventory_sessions(self) -> List[InventorySession]:
        if not self.current_user:
            return []
        if self.current_user.role == UserRole.BORROWER:
            self._require_permission("view_own_inventory")
            borrower_name = self.current_user.display_name
            borrower_id = self.current_user.username
            visible: List[InventorySession] = []
            for s in self.inventory_sessions:
                if s.status != InventoryStatus.COMPLETED:
                    continue
                related_items = [it for it in s.items
                                 if self._is_item_related_to_borrower(
                                     it, borrower_name, borrower_id)]
                if related_items:
                    filtered_session = InventorySession(
                        id=s.id, title=s.title, status=s.status,
                        created_by=s.created_by, created_by_role=s.created_by_role,
                        created_at=s.created_at, completed_at=s.completed_at,
                        completed_by=s.completed_by, completed_by_role=s.completed_by_role,
                        filter_conditions=s.filter_conditions,
                        items=related_items,
                        remark=s.remark,
                    )
                    visible.append(filtered_session)
            return visible
        self._require_permission("view_inventory")
        return list(self.inventory_sessions)

    def _is_item_related_to_borrower(self, item: InventoryItem,
                                      borrower_name: str,
                                      borrower_id: str) -> bool:
        for r in self.records:
            if (r.device_id == item.device_id
                    and (r.borrower_name == borrower_name
                         or r.borrower_id == borrower_id)):
                return True
        return False

    def _find_inventory_item(self, session: InventorySession,
                              device_id: str) -> Optional[InventoryItem]:
        return next((it for it in session.items if it.device_id == device_id), None)

    def fill_inventory_item(self, session_id: str, device_id: str,
                            actual_status: str = "", actual_location: str = "",
                            missing_accessories: Optional[List[str]] = None,
                            inventory_result: str = "",
                            remark: str = "") -> InventoryItem:
        self._require_permission("fill_inventory")
        session = self.find_inventory_session(session_id)
        if not session:
            raise BusinessError("盘点记录不存在")
        if session.status == InventoryStatus.COMPLETED:
            raise BusinessError("该盘点已完成，不能再填写")
        item = self._find_inventory_item(session, device_id)
        if not item:
            raise BusinessError("该设备不在本次盘点范围内")

        has_conflict, conflict_msg = self._has_device_active_business(device_id)
        if has_conflict and inventory_result and inventory_result != InventoryItemResult.NORMAL:
            if actual_status and actual_status != item.original_status:
                raise BusinessError(
                    f"{conflict_msg}，盘点中不能覆盖正在进行的业务状态。"
                    f"请保持实际状态与系统原状态一致，或先完成相关业务流程再盘点。"
                )

        item.actual_status = actual_status.strip() if actual_status else item.original_status
        item.actual_location = actual_location.strip() if actual_location else ""
        item.missing_accessories = list(missing_accessories) if missing_accessories else []
        if inventory_result and inventory_result in InventoryItemResult.ALL_RESULTS:
            item.inventory_result = inventory_result
        elif missing_accessories and len(missing_accessories) > 0:
            item.inventory_result = InventoryItemResult.ACCESSORY_MISSING
        elif actual_status and actual_status != item.original_status:
            item.inventory_result = InventoryItemResult.OTHER
        elif not item.inventory_result:
            item.inventory_result = InventoryItemResult.NORMAL
        item.remark = remark.strip() if remark else item.remark
        item.filled_by = self.current_user.username if self.current_user else ""
        item.filled_by_role = self.current_user.role if self.current_user else ""
        item.filled_at = _now_str()

        if session.status == InventoryStatus.DRAFT:
            session.status = InventoryStatus.IN_PROGRESS

        self.save_all()
        return item

    def complete_inventory(self, session_id: str,
                           remark: str = "") -> InventorySession:
        self._require_permission("complete_inventory")
        session = self.find_inventory_session(session_id)
        if not session:
            raise BusinessError("盘点记录不存在")
        if session.status == InventoryStatus.COMPLETED:
            raise BusinessError("该盘点已经完成")
        if not session.items:
            raise BusinessError("盘点没有包含任何设备，无法完成")

        unfilled = [it for it in session.items if not it.inventory_result]
        if unfilled:
            raise BusinessError(
                f"还有 {len(unfilled)} 台设备未填写盘点结果，"
                f"请全部填写后再完成盘点。"
            )

        session.status = InventoryStatus.COMPLETED
        session.completed_at = _now_str()
        session.completed_by = self.current_user.username if self.current_user else ""
        session.completed_by_role = self.current_user.role if self.current_user else ""
        if remark and remark.strip():
            session.remark = (session.remark + "\n" if session.remark else "") + remark.strip()

        self.save_all()
        return session

    def get_inventory_exception_count(self, session: InventorySession) -> int:
        return sum(1 for it in session.items
                   if it.inventory_result
                   and it.inventory_result != InventoryItemResult.NORMAL)

    def export_inventory_session(self, session_id: str,
                                  filepath: str) -> Tuple[bool, str]:
        self._require_permission("export_inventory")
        session = self.find_inventory_session(session_id)
        if not session:
            return False, "盘点记录不存在"
        if session.status != InventoryStatus.COMPLETED:
            return False, "只有已完成的盘点才能导出"

        ok, reason = self.check_export_dir_detail()
        if not ok:
            return False, f"导出失败：{reason}\n请先设置一个可写的导出目录。"

        operator = self.current_user.username if self.current_user else ""
        exception_count = self.get_inventory_exception_count(session)

        if filepath.lower().endswith(".csv"):
            ok = storage.export_inventory_csv(session, filepath, operator, exception_count)
        else:
            ok = storage.export_inventory_json(session, filepath, operator, exception_count)
        if not ok:
            return False, f"导出失败，目标文件无法写入：{filepath}"
        return True, f"导出成功：{filepath}"

    def save_inventory_filter(self, flt: dict):
        try:
            self.config.last_inventory_filter = dict(flt) if flt else {}
            self.save_all()
        except Exception:
            pass

    def get_last_inventory_filter(self) -> dict:
        return dict(self.config.last_inventory_filter or {})

    def get_unique_categories(self) -> List[str]:
        cats = sorted({d.category for d in self.devices if d.category})
        return cats

    def get_unique_storage_locations(self) -> List[str]:
        locs = sorted({d.storage_location for d in self.devices if d.storage_location})
        return locs

    def get_unique_responsible_persons(self) -> List[str]:
        rps = sorted({d.responsible_person for d in self.devices if d.responsible_person})
        return rps

    def set_active_inventory_session(self, session_id: str):
        self.config.last_active_inventory_session_id = session_id
        self.save_all()

    def get_active_inventory_session(self) -> Optional[InventorySession]:
        sid = self.config.last_active_inventory_session_id
        if not sid:
            return None
        session = self.find_inventory_session(sid)
        if session and session.status != InventoryStatus.COMPLETED:
            return session
        return None

    def clear_active_inventory_session(self):
        self.config.last_active_inventory_session_id = ""
        self.save_all()

    def get_inventory_progress(self, session: InventorySession) -> dict:
        total = len(session.items)
        filled = sum(1 for it in session.items if it.inventory_result)
        exceptions = self.get_inventory_exception_count(session)
        normal = filled - exceptions
        return {
            "total": total,
            "filled": filled,
            "remaining": total - filled,
            "exceptions": exceptions,
            "normal": normal,
            "progress_pct": round((filled / total * 100), 1) if total > 0 else 0.0,
        }

    def get_inventory_diff_details(self, session: InventorySession) -> List[dict]:
        details = []
        for it in session.items:
            dev = self.find_device(it.device_id)
            if not dev:
                continue
            diffs = []
            if it.actual_status and it.actual_status != it.original_status:
                diffs.append(f"状态: {it.original_status} → {it.actual_status}")
            if it.actual_location and it.actual_location != (dev.storage_location or ""):
                diffs.append(f"位置: {dev.storage_location or '未记录'} → {it.actual_location}")
            if it.missing_accessories:
                diffs.append(f"缺失配件: {', '.join(it.missing_accessories)}")
            if it.inventory_result and it.inventory_result != InventoryItemResult.NORMAL:
                diffs.append(f"盘点结果: {it.inventory_result}")
            details.append({
                "device_id": it.device_id,
                "device_name": it.device_name,
                "original_status": it.original_status,
                "actual_status": it.actual_status,
                "original_location": dev.storage_location or "",
                "actual_location": it.actual_location,
                "result": it.inventory_result,
                "remark": it.remark,
                "diffs": diffs,
                "has_diff": len(diffs) > 0,
                "filled_by": it.filled_by,
                "filled_at": it.filled_at,
            })
        return details

    def get_inventory_exception_summary(self, session: InventorySession) -> dict:
        summary = {
            "total": len(session.items),
            "normal": 0,
            "missing": 0,
            "damaged": 0,
            "location_wrong": 0,
            "accessory_missing": 0,
            "other": 0,
            "unfilled": 0,
            "by_result": {},
        }
        for it in session.items:
            if not it.inventory_result:
                summary["unfilled"] += 1
                continue
            if it.inventory_result == InventoryItemResult.NORMAL:
                summary["normal"] += 1
            elif it.inventory_result == InventoryItemResult.MISSING:
                summary["missing"] += 1
            elif it.inventory_result == InventoryItemResult.DAMAGED:
                summary["damaged"] += 1
            elif it.inventory_result == InventoryItemResult.LOCATION_WRONG:
                summary["location_wrong"] += 1
            elif it.inventory_result == InventoryItemResult.ACCESSORY_MISSING:
                summary["accessory_missing"] += 1
            elif it.inventory_result == InventoryItemResult.OTHER:
                summary["other"] += 1
            key = it.inventory_result
            if key not in summary["by_result"]:
                summary["by_result"][key] = []
            summary["by_result"][key].append(it.device_name)
        return summary

    def find_handoff(self, handoff_id: str) -> Optional[HandoffRecord]:
        return next((h for h in self.handoff_records if h.id == handoff_id), None)

    def _get_last_inventory_for_device(self, device_id: str) -> Optional[InventoryItem]:
        last_item = None
        last_time = ""
        for s in self.inventory_sessions:
            if s.status != InventoryStatus.COMPLETED:
                continue
            for it in s.items:
                if it.device_id == device_id and it.inventory_result and it.filled_at:
                    if it.filled_at > last_time:
                        last_time = it.filled_at
                        last_item = it
                        last_item = InventoryItem(
                            device_id=it.device_id,
                            device_name=it.device_name,
                            original_status=it.original_status,
                            actual_status=it.actual_status,
                            actual_location=it.actual_location,
                            missing_accessories=list(it.missing_accessories),
                            remark=it.remark,
                            inventory_result=it.inventory_result,
                            filled_by=it.filled_by,
                            filled_by_role=it.filled_by_role,
                            filled_at=it.filled_at,
                        )
                        last_item._session_id = s.id
                        last_item._session_title = s.title
        return last_item

    def _get_device_current_holder(self, device_id: str) -> Tuple[str, str, str]:
        active = self.get_active_record_for_device(device_id)
        if active:
            return active.borrower_id, active.borrower_name, active.status
        device = self.find_device(device_id)
        if device:
            if device.status == DeviceStatus.MAINTENANCE:
                return "maintenance", "维修中", device.status
            if device.status == DeviceStatus.FROZEN:
                return "frozen", "冻结中", device.status
            return "", "", device.status
        return "", "", ""

    def _check_handoff_status_conflict(self, device_id: str,
                                        action_type: str) -> Tuple[bool, str]:
        device = self.find_device(device_id)
        if not device:
            return True, "设备不存在"
        if action_type == HandoffAction.BORROW_OUT:
            if device.status == DeviceStatus.BORROWED:
                return True, f"设备【{device.name}】已借出，不能重复发起借出交接"
            if device.status == DeviceStatus.MAINTENANCE:
                return True, f"设备【{device.name}】正在维修中，不能借出交接"
            if device.status == DeviceStatus.FROZEN:
                return True, f"设备【{device.name}】处于异常冻结状态，不能借出交接"
            if device.status == DeviceStatus.INSPECTING:
                return True, f"设备【{device.name}】正在归还验收中，不能借出交接"
        elif action_type == HandoffAction.RETURN_BACK:
            if device.status != DeviceStatus.BORROWED and device.status != DeviceStatus.INSPECTING:
                return True, (f"设备【{device.name}】当前状态为【{device.status}】，"
                              f"不是已借出或验收中，无法发起归还交接")
        elif action_type == HandoffAction.MAINTENANCE_BACK:
            if device.status != DeviceStatus.MAINTENANCE:
                return True, (f"设备【{device.name}】当前状态为【{device.status}】，"
                              f"不是维修中，无法发起维修后交回交接")
        elif action_type == HandoffAction.FREEZE_RELEASE:
            if device.status != DeviceStatus.FROZEN:
                return True, (f"设备【{device.name}】当前状态为【{device.status}】，"
                              f"不是冻结状态，无法发起冻结解除交接")
        return False, ""

    def create_handoff(self, device_id: str, action_type: str,
                       source_record_id: str = "",
                       admin_remark: str = "",
                       draft_remark: str = "",
                       target_holder_id: str = "",
                       target_holder_name: str = "") -> HandoffRecord:
        self._require_permission("create_handoff")
        device = self.find_device(device_id)
        if not device:
            raise BusinessError("设备不存在")
        if action_type not in HandoffAction.ALL_ACTIONS:
            raise BusinessError(f"不支持的交接动作：{action_type}")

        has_conflict, conflict_msg = self._check_handoff_status_conflict(device_id, action_type)
        if has_conflict:
            raise BusinessError(
                f"{conflict_msg}\n设备状态与交接动作冲突，已保持原状态不变。"
                f"请先完成相关业务流程后再发起交接复核。"
            )

        holder_id, holder_name, biz_status = self._get_device_current_holder(device_id)

        if action_type == HandoffAction.BORROW_OUT and target_holder_id:
            target_holder = self.find_borrower(target_holder_id)
            if target_holder:
                target_holder_name = target_holder_name or target_holder.name

        last_inv = self._get_last_inventory_for_device(device_id)
        last_inv_id = ""
        last_inv_result = ""
        last_inv_time = ""
        if last_inv:
            last_inv_id = getattr(last_inv, "_session_id", "")
            last_inv_result = last_inv.inventory_result or ""
            last_inv_time = last_inv.filled_at or ""

        record = HandoffRecord(
            device_id=device.id,
            device_name=device.name,
            action_type=action_type,
            source_record_id=source_record_id,
            current_holder_id=holder_id,
            current_holder_name=holder_name,
            target_holder_id=target_holder_id,
            target_holder_name=target_holder_name,
            business_status=biz_status,
            last_inventory_id=last_inv_id,
            last_inventory_result=last_inv_result,
            last_inventory_time=last_inv_time,
            admin_remark=admin_remark.strip(),
            draft_remark=draft_remark.strip(),
            created_by=self.current_user.username if self.current_user else "",
            created_by_role=self.current_user.role if self.current_user else "",
            status=HandoffStatus.PENDING,
        )
        self.handoff_records.append(record)
        self.save_all()
        return record

    def update_handoff_draft(self, handoff_id: str,
                             admin_remark: str = "",
                             draft_remark: str = "",
                             target_holder_id: str = "",
                             target_holder_name: str = "") -> HandoffRecord:
        self._require_permission("edit_handoff")
        record = self.find_handoff(handoff_id)
        if not record:
            raise BusinessError("交接记录不存在")
        if record.status not in (HandoffStatus.PENDING, HandoffStatus.OBJECTED):
            raise BusinessError(
                f"当前交接状态为【{record.status}】，只有待确认或有异议的记录可以编辑草稿"
            )
        record.admin_remark = admin_remark.strip()
        record.draft_remark = draft_remark.strip()
        if target_holder_id:
            record.target_holder_id = target_holder_id
            record.target_holder_name = target_holder_name or record.target_holder_name
        self.save_all()
        return record

    def confirm_handoff_as_borrower(self, handoff_id: str,
                                     remark: str = "") -> HandoffRecord:
        self._require_permission("confirm_handoff")
        record = self.find_handoff(handoff_id)
        if not record:
            raise BusinessError("交接记录不存在")
        if record.status == HandoffStatus.COMPLETED:
            raise BusinessError("该交接已完成，不能再次确认")
        if self.current_user:
            username = self.current_user.username
            display_name = self.current_user.display_name
            related_ids = {record.current_holder_id, record.current_holder_name,
                           record.target_holder_id, record.target_holder_name}
            if (username not in related_ids and display_name not in related_ids):
                raise BusinessError(
                    f"您不是该交接的相关持有人（当前持有人：{record.current_holder_name}，"
                    f"目标持有人：{record.target_holder_name}），无权确认此交接"
                )
        record.borrower_confirm = True
        record.borrower_remark = remark.strip()
        record.objection_reason = ""
        record.confirmed_by = self.current_user.username if self.current_user else ""
        record.confirmed_at = _now_str()
        if record.status == HandoffStatus.OBJECTED:
            record.status = HandoffStatus.PENDING
        else:
            record.status = HandoffStatus.CONFIRMED
        self.save_all()
        return record

    def object_handoff_as_borrower(self, handoff_id: str,
                                    reason: str = "",
                                    remark: str = "") -> HandoffRecord:
        self._require_permission("object_handoff")
        record = self.find_handoff(handoff_id)
        if not record:
            raise BusinessError("交接记录不存在")
        if record.status == HandoffStatus.COMPLETED:
            raise BusinessError("该交接已完成，不能再提交异议")
        if not reason or not reason.strip():
            raise BusinessError("提出异议必须填写原因")
        if self.current_user:
            username = self.current_user.username
            display_name = self.current_user.display_name
            related_ids = {record.current_holder_id, record.current_holder_name,
                           record.target_holder_id, record.target_holder_name}
            if (username not in related_ids and display_name not in related_ids):
                raise BusinessError(
                    f"您不是该交接的相关持有人（当前持有人：{record.current_holder_name}，"
                    f"目标持有人：{record.target_holder_name}），无权对此交接提出异议"
                )
        record.borrower_confirm = False
        record.objection_reason = reason.strip()
        record.borrower_remark = remark.strip()
        record.status = HandoffStatus.OBJECTED
        self.save_all()
        return record

    def complete_handoff(self, handoff_id: str,
                         final_conclusion: str = "") -> HandoffRecord:
        self._require_permission("complete_handoff")
        record = self.find_handoff(handoff_id)
        if not record:
            raise BusinessError("交接记录不存在")
        if record.status == HandoffStatus.COMPLETED:
            raise BusinessError("该交接已完成")

        has_conflict, conflict_msg = self._check_handoff_status_conflict(
            record.device_id, record.action_type
        )
        if has_conflict:
            raise BusinessError(
                f"{conflict_msg}\n完成交接前发现设备状态与交接动作冲突，"
                f"已保持原状态不变，请先处理相关业务。"
            )

        if not record.borrower_confirm and record.status != HandoffStatus.OBJECTED:
            raise BusinessError("借用人尚未确认，无法完成交接")

        record.final_conclusion = final_conclusion.strip()
        record.completed_by = self.current_user.username if self.current_user else ""
        record.completed_at = _now_str()
        record.status = HandoffStatus.COMPLETED
        if not record.confirmed_by:
            record.confirmed_by = record.completed_by
            record.confirmed_at = record.completed_at
        self.save_all()
        return record

    def get_handoff_records(self) -> List[HandoffRecord]:
        if not self.current_user:
            return []
        role = self.current_user.role
        if role == UserRole.BORROWER:
            self._require_permission("view_own_handoff")
            name = self.current_user.display_name
            uid = self.current_user.username
            return [h for h in self.handoff_records
                    if (h.current_holder_id in (name, uid)
                        or h.current_holder_name == name
                        or h.target_holder_id in (name, uid)
                        or h.target_holder_name == name)]
        self._require_permission("view_handoff_all")
        return list(self.handoff_records)

    def filter_handoff_records(self, records: List[HandoffRecord],
                                device_id: str = "",
                                current_holder: str = "",
                                business_status: str = "",
                                status_filter: str = "all",
                                action_type: str = "all") -> List[HandoffRecord]:
        result = list(records)
        if device_id and device_id.strip():
            did = device_id.strip().lower()
            result = [h for h in result
                      if did in h.device_id.lower()
                      or did in (h.device_name or "").lower()]
        if current_holder and current_holder.strip():
            ch = current_holder.strip()
            result = [h for h in result
                      if ch in (h.current_holder_name or "")
                      or ch in (h.current_holder_id or "")]
        if business_status and business_status.strip() and business_status.strip() != "all":
            bs = business_status.strip()
            result = [h for h in result if h.business_status == bs]
        if status_filter and status_filter != "all":
            result = [h for h in result if h.status == status_filter]
        if action_type and action_type != "all":
            result = [h for h in result if h.action_type == action_type]
        return result

    def save_handoff_filter(self, flt: dict):
        try:
            self.config.last_handoff_filter = dict(flt) if flt else {}
            self.save_all()
        except Exception:
            pass

    def get_last_handoff_filter(self) -> dict:
        return dict(self.config.last_handoff_filter or {})

    def export_handoff_records(self, handoff_ids: List[str],
                                filepath: str,
                                filter_info: Optional[dict] = None) -> Tuple[bool, str]:
        self._require_permission("export_handoff")
        ok, reason = self.check_export_dir_detail()
        if not ok:
            return False, f"导出失败：{reason}\n请先设置一个可写的导出目录。"
        selected = [h for h in self.handoff_records if h.id in handoff_ids]
        if not selected:
            return False, "没有选中任何交接记录"
        operator = self.current_user.username if self.current_user else ""
        if filepath.lower().endswith(".csv"):
            ok = storage.export_handoff_csv(selected, filepath, filter_info, operator)
        else:
            ok = storage.export_handoff_json(selected, filepath, filter_info, operator)
        if not ok:
            return False, f"导出失败，目标文件无法写入：{filepath}"
        return True, f"导出成功：{filepath}"

    def find_accessory(self, accessory_id: str) -> Optional[DeviceAccessory]:
        return next((a for a in self.accessories if a.id == accessory_id), None)

    def get_accessories_by_device(self, device_id: str) -> List[DeviceAccessory]:
        return [a for a in self.accessories if a.device_id == device_id]

    def _get_visible_device_ids_for_current_user(self) -> set:
        if not self.current_user:
            return set()
        if self.current_user.role in (UserRole.ADMIN, UserRole.INSPECTOR):
            return {d.id for d in self.devices}
        name = self.current_user.display_name
        uid = self.current_user.username
        device_ids = set()
        for r in self.records:
            if (r.borrower_name == name or r.borrower_id == uid):
                device_ids.add(r.device_id)
        return device_ids

    def get_accessories(self) -> List[DeviceAccessory]:
        if not self.current_user:
            return []
        if self.has_permission("view_accessory_all"):
            return list(self.accessories)
        if self.has_permission("view_own_accessory"):
            visible_dev_ids = self._get_visible_device_ids_for_current_user()
            return [a for a in self.accessories if a.device_id in visible_dev_ids]
        return []

    def can_modify_accessory_device(self, device_id: str) -> Tuple[bool, str]:
        device = self.find_device(device_id)
        if not device:
            return False, "设备不存在"
        if device.status == DeviceStatus.MAINTENANCE:
            if self.current_user and self.current_user.role == UserRole.BORROWER:
                return False, f"设备【{device.name}】正在维修中，借用人不能修改其附件"
        return True, ""

    def add_accessory(self, device_id: str, name: str,
                      type: str = AccessoryType.ACCESSORY,
                      quantity: int = 1, serial_no: str = "",
                      storage_location: str = "", expiry_date: str = "",
                      responsible_person: str = "", remark: str = "") -> DeviceAccessory:
        self._require_permission("add_accessory")
        if not device_id or not str(device_id).strip():
            raise BusinessError("必须选择设备")
        device = self.find_device(device_id.strip())
        if not device:
            raise BusinessError("设备不存在")
        can_mod, reason = self.can_modify_accessory_device(device.id)
        if not can_mod:
            raise BusinessError(reason)
        if not name or not str(name).strip():
            raise BusinessError("附件/证照名称不能为空")
        try:
            qty = int(quantity)
        except (ValueError, TypeError):
            raise BusinessError("数量必须是正整数")
        if qty <= 0:
            raise BusinessError("数量必须大于 0")
        if expiry_date and expiry_date.strip():
            dt = self._parse_datetime(expiry_date.strip())
            if not dt:
                raise BusinessError("到期日格式错误，应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS")
        if serial_no and serial_no.strip():
            for a in self.accessories:
                if a.serial_no == serial_no.strip():
                    raise BusinessError(f"编号【{serial_no.strip()}】已存在，请使用不同编号")

        acc = DeviceAccessory(
            device_id=device.id,
            device_name=device.name,
            name=name.strip(),
            type=type if type in AccessoryType.ALL_TYPES else AccessoryType.ACCESSORY,
            quantity=qty,
            serial_no=serial_no.strip(),
            storage_location=storage_location.strip(),
            expiry_date=expiry_date.strip() if expiry_date else "",
            responsible_person=responsible_person.strip(),
            remark=remark.strip(),
            created_by=self.current_user.username if self.current_user else "",
            created_by_role=self.current_user.role if self.current_user else "",
        )
        self.accessories.append(acc)
        self.save_all()
        return acc

    def update_accessory(self, accessory_id: str, **kwargs) -> DeviceAccessory:
        self._require_permission("edit_accessory")
        acc = self.find_accessory(accessory_id)
        if not acc:
            raise BusinessError("附件/证照不存在")
        can_mod, reason = self.can_modify_accessory_device(acc.device_id)
        if not can_mod:
            raise BusinessError(reason)

        if "quantity" in kwargs:
            try:
                qty = int(kwargs["quantity"])
            except (ValueError, TypeError):
                raise BusinessError("数量必须是正整数")
            if qty <= 0:
                raise BusinessError("数量必须大于 0")
            kwargs["quantity"] = qty

        if "expiry_date" in kwargs and kwargs["expiry_date"]:
            dt = self._parse_datetime(str(kwargs["expiry_date"]).strip())
            if not dt:
                raise BusinessError("到期日格式错误，应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS")

        if "serial_no" in kwargs and kwargs["serial_no"]:
            new_serial = str(kwargs["serial_no"]).strip()
            for a in self.accessories:
                if a.id != acc.id and a.serial_no == new_serial:
                    raise BusinessError(f"编号【{new_serial}】已存在，请使用不同编号")
            kwargs["serial_no"] = new_serial

        if "device_id" in kwargs:
            new_device_id = str(kwargs["device_id"]).strip()
            if new_device_id != acc.device_id:
                new_device = self.find_device(new_device_id)
                if not new_device:
                    raise BusinessError("目标设备不存在")
                can_mod2, reason2 = self.can_modify_accessory_device(new_device.id)
                if not can_mod2:
                    raise BusinessError(reason2)
                kwargs["device_id"] = new_device.id
                kwargs["device_name"] = new_device.name

        for k, v in kwargs.items():
            if hasattr(acc, k):
                setattr(acc, k, v)
        acc.updated_at = _now_str()
        acc.updated_by = self.current_user.username if self.current_user else ""
        self.save_all()
        return acc

    def delete_accessory(self, accessory_id: str):
        self._require_permission("delete_accessory")
        acc = self.find_accessory(accessory_id)
        if not acc:
            raise BusinessError("附件/证照不存在")
        can_mod, reason = self.can_modify_accessory_device(acc.device_id)
        if not can_mod:
            raise BusinessError(reason)
        self.accessories.remove(acc)
        self.save_all()

    def filter_accessories(self, accessories: List[DeviceAccessory],
                           device_id: str = "",
                           type_filter: str = "all",
                           keyword: str = "",
                           serial_no: str = "",
                           expiry_from: str = "",
                           expiry_to: str = "",
                           responsible_person: str = "") -> List[DeviceAccessory]:
        result = list(accessories)
        if device_id and device_id.strip():
            did = device_id.strip()
            result = [a for a in result if a.device_id == did]
        if type_filter and type_filter != "all":
            result = [a for a in result if a.type == type_filter]
        if serial_no and serial_no.strip():
            sn = serial_no.strip().lower()
            result = [a for a in result if sn in (a.serial_no or "").lower()]
        if responsible_person and responsible_person.strip():
            rp = responsible_person.strip()
            result = [a for a in result if rp in (a.responsible_person or "")]
        if expiry_from and expiry_from.strip():
            dt_from = self._parse_datetime(expiry_from.strip())
            if dt_from:
                result = [a for a in result
                          if a.expiry_date and self._parse_datetime(a.expiry_date)
                          and self._parse_datetime(a.expiry_date) >= dt_from]
        if expiry_to and expiry_to.strip():
            dt_to = self._parse_datetime(expiry_to.strip())
            if dt_to:
                result = [a for a in result
                          if a.expiry_date and self._parse_datetime(a.expiry_date)
                          and self._parse_datetime(a.expiry_date) <= dt_to]
        if keyword and keyword.strip():
            kw = keyword.strip().lower()
            result = [a for a in result
                      if kw in a.name.lower()
                      or kw in (a.serial_no or "").lower()
                      or kw in (a.device_name or "").lower()
                      or kw in a.device_id.lower()
                      or kw in (a.storage_location or "").lower()
                      or kw in (a.responsible_person or "").lower()]
        return result

    def save_accessory_filter(self, flt: dict):
        try:
            self.config.last_accessory_filter = dict(flt) if flt else {}
            self.save_all()
        except Exception:
            pass

    def get_last_accessory_filter(self) -> dict:
        return dict(self.config.last_accessory_filter or {})

    def precheck_accessory_import_file(self, filepath: str) -> Tuple[bool, str, ImportPrecheckSummary]:
        self._require_permission("import_accessories")

        ok, msg, rows, fmt = storage.parse_import_file(filepath)
        if not ok:
            return False, msg, ImportPrecheckSummary()

        summary = ImportPrecheckSummary(total=len(rows))
        seen_serials = set()
        existing_serials = {a.serial_no for a in self.accessories if a.serial_no}

        for row in rows:
            issues_for_row = []

            missing_fields = []
            for f in storage.ACCESSORY_IMPORT_REQUIRED_FIELDS:
                val = row.get(f, "")
                if val is None or (isinstance(val, str) and not val.strip()):
                    missing_fields.append(f)
            if missing_fields:
                summary.field_missing += 1
                issues_for_row.append(self._make_row_issue(
                    row, "字段缺失",
                    f"缺少必填字段：{', '.join(missing_fields)}"
                ))

            device = None
            if not issues_for_row or "device_id" not in missing_fields:
                device_id = str(row.get("device_id", "")).strip()
                device = self.find_device(device_id)
                if not device:
                    summary.device_not_found += 1
                    issues_for_row.append(self._make_row_issue(
                        row, "设备不存在",
                        f"设备ID【{device_id}】在系统中不存在"
                    ))

            qty_raw = row.get("quantity", "")
            if qty_raw is not None and str(qty_raw).strip():
                try:
                    qty = int(str(qty_raw).strip())
                    if qty <= 0:
                        raise ValueError
                except (ValueError, TypeError):
                    summary.issues.append(self._make_row_issue(
                        row, "数量非法",
                        f"数量【{qty_raw}】不是正整数"
                    ))
                    issues_for_row.append("数量非法")

            expiry_raw = str(row.get("expiry_date", "")).strip()
            if expiry_raw:
                dt = self._parse_datetime(expiry_raw)
                if not dt:
                    summary.issues.append(self._make_row_issue(
                        row, "日期格式错误",
                        f"到期日【{expiry_raw}】格式错误，应为 YYYY-MM-DD"
                    ))
                    issues_for_row.append("日期格式错误")

            serial_raw = str(row.get("serial_no", "")).strip()
            if serial_raw:
                if serial_raw in seen_serials:
                    summary.duplicate += 1
                    issues_for_row.append(self._make_row_issue(
                        row, "重复编号",
                        f"同一文件内编号【{serial_raw}】重复"
                    ))
                elif serial_raw in existing_serials:
                    summary.duplicate += 1
                    issues_for_row.append(self._make_row_issue(
                        row, "重复编号",
                        f"编号【{serial_raw}】已在系统中存在"
                    ))
                else:
                    seen_serials.add(serial_raw)

            if any(i for i in issues_for_row if not isinstance(i, str)):
                real_issues = [i for i in issues_for_row if not isinstance(i, str)]
                summary.issues.extend(real_issues)
            else:
                if not issues_for_row:
                    summary.importable += 1

        return True, "", summary

    def commit_accessory_import(self, filepath: str) -> Tuple[bool, str, int, int]:
        self._require_permission("import_accessories")

        ok, msg, rows, fmt = storage.parse_import_file(filepath)
        if not ok:
            self._append_import_log(filepath, fmt, 0, 0, 0, [msg])
            return False, msg, 0, 0

        pre_ok, pre_msg, summary = self.precheck_accessory_import_file(filepath)
        if not pre_ok:
            self._append_import_log(filepath, fmt, len(rows), 0, len(rows), [pre_msg])
            return False, pre_msg, 0, len(rows)
        has_issue = (
            summary.field_missing > 0 or summary.device_not_found > 0
            or summary.duplicate > 0 or summary.issues
        )
        if has_issue:
            parts = []
            if summary.field_missing:
                parts.append(f"字段缺失 {summary.field_missing}")
            if summary.device_not_found:
                parts.append(f"未知设备 {summary.device_not_found}")
            if summary.duplicate:
                parts.append(f"重复编号 {summary.duplicate}")
            other_issues = [i for i in summary.issues if i.get("kind") in ("数量非法", "日期格式错误")]
            if other_issues:
                parts.append(f"其他错误 {len(other_issues)}")
            reason = (
                "预检发现问题，整批未写入（必须全部合法才可导入）："
                + "；".join(parts)
            )
            self._append_import_log(
                filepath, fmt, len(rows), 0, len(rows), [reason]
            )
            return False, reason, 0, len(rows)

        backup = copy.deepcopy(self.accessories)

        success_count = 0
        fail_count = 0
        fail_reasons = []
        seen_serials = set()

        try:
            for row in rows:
                try:
                    device_id = str(row.get("device_id", "")).strip()
                    device = self.find_device(device_id)
                    if not device:
                        fail_count += 1
                        fail_reasons.append(f"第{row.get('_row','?')}行: 设备不存在")
                        continue

                    name = str(row.get("name", "")).strip()
                    if not name:
                        fail_count += 1
                        fail_reasons.append(f"第{row.get('_row','?')}行: 名称为空")
                        continue

                    qty_raw = str(row.get("quantity", "")).strip()
                    qty = 1
                    if qty_raw:
                        qty = int(qty_raw)
                    if qty <= 0:
                        fail_count += 1
                        fail_reasons.append(f"第{row.get('_row','?')}行: 数量非法")
                        continue

                    serial_no = str(row.get("serial_no", "")).strip()
                    if serial_no:
                        if serial_no in seen_serials:
                            fail_count += 1
                            fail_reasons.append(f"第{row.get('_row','?')}行: 编号重复")
                            continue
                        seen_serials.add(serial_no)

                    expiry = str(row.get("expiry_date", "")).strip()
                    if expiry:
                        dt = self._parse_datetime(expiry)
                        if not dt:
                            fail_count += 1
                            fail_reasons.append(f"第{row.get('_row','?')}行: 日期格式错误")
                            continue

                    acc_type = str(row.get("type", "")).strip()
                    if acc_type not in AccessoryType.ALL_TYPES:
                        acc_type = AccessoryType.ACCESSORY

                    acc = DeviceAccessory(
                        device_id=device.id,
                        device_name=device.name,
                        name=name,
                        type=acc_type,
                        quantity=qty,
                        serial_no=serial_no,
                        storage_location=str(row.get("storage_location", "")).strip(),
                        expiry_date=expiry,
                        responsible_person=str(row.get("responsible_person", "")).strip(),
                        remark=str(row.get("remark", "")).strip(),
                        created_by=self.current_user.username if self.current_user else "",
                        created_by_role=self.current_user.role if self.current_user else "",
                    )
                    self.accessories.append(acc)
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    fail_reasons.append(f"第{row.get('_row','?')}行: {e}")

            self.save_all()
            self._append_import_log(filepath, fmt, len(rows), success_count, fail_count, fail_reasons)
            return True, f"成功导入 {success_count} 条，失败 {fail_count} 条", success_count, fail_count

        except Exception as e:
            self.accessories = backup
            try:
                self.save_all()
            except Exception:
                pass
            rollback_reason = f"导入过程发生异常，整批已回滚：{e}"
            self._append_import_log(filepath, fmt, len(rows), 0, len(rows), [rollback_reason])
            return False, rollback_reason, 0, 0

    def export_accessories(self, accessory_ids: List[str],
                           filepath: str,
                           filter_info: Optional[dict] = None) -> Tuple[bool, str]:
        self._require_permission("export_accessories")
        ok, reason = self.check_export_dir_detail()
        if not ok:
            return False, f"导出失败：{reason}\n请先设置一个可写的导出目录。"
        selected = [a for a in self.accessories if a.id in accessory_ids]
        if not selected:
            return False, "没有选中任何附件/证照记录"
        operator = self.current_user.username if self.current_user else ""
        devices_map = {d.id: d for d in self.devices}
        if filepath.lower().endswith(".csv"):
            ok = storage.export_accessories_csv(selected, filepath, filter_info, operator, devices_map)
        else:
            ok = storage.export_accessories_json(selected, filepath, filter_info, operator, devices_map)
        if not ok:
            return False, f"导出失败，目标文件无法写入：{filepath}"
        return True, f"导出成功：{filepath}"

    def get_accessory_check_hint(self, device_id: str) -> str:
        accs = self.get_accessories_by_device(device_id)
        if not accs:
            return ""
        parts = [f"{a.name} x{a.quantity}" for a in accs]
        return "请核对附件/证照：" + "；".join(parts)
