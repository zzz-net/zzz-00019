import os
import copy
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
from models import (
    Device, Borrower, BorrowRecord, User, Accessory,
    DeviceStatus, RecordStatus, UserRole, _now_str,
    ImportPrecheckSummary, ImportLogEntry, MaintenanceRecord
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
        self.config = storage.load_config()
        if self.config.last_user:
            self.current_user = self.find_user(self.config.last_user)

    def save_all(self):
        storage.save_devices(self.devices)
        storage.save_borrowers(self.borrowers)
        storage.save_records(self.records)
        storage.save_users(self.users)
        storage.save_maintenance_logs(self.maintenance_logs)
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
                        f"[{_now_str()}] 送修/保养：{reason.strip()}"

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
        self._records_snapshot_at_last_maintenance = self._make_records_snapshot()
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
                        f"[{_now_str()}] 撤销维修：{remark.strip() if remark else '未说明'}"

        active_m.status = "cancelled"
        active_m.end_time = _now_str()
        active_m.cancel_remark = remark.strip() if remark else ""
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
