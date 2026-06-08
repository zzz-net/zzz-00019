from typing import List, Optional, Tuple
from models import (
    Device, Borrower, BorrowRecord, User, Accessory,
    DeviceStatus, RecordStatus, UserRole, _now_str
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
        self.config = storage.AppConfig()
        self.current_user: Optional[User] = None
        self.load_all()

    def load_all(self):
        storage.seed_sample_data()
        self.devices = storage.load_devices()
        self.borrowers = storage.load_borrowers()
        self.records = storage.load_records()
        self.users = storage.load_users()
        self.config = storage.load_config()
        if self.config.last_user:
            self.current_user = self.find_user(self.config.last_user)

    def save_all(self):
        storage.save_devices(self.devices)
        storage.save_borrowers(self.borrowers)
        storage.save_records(self.records)
        storage.save_users(self.users)
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
                                filepath: str) -> Tuple[bool, str]:
        ok, reason = self.check_export_dir_detail()
        if not ok:
            return False, (
                f"导出失败：{reason}\n"
                f"请先设置一个可写的导出目录。\n"
                f"已选记录数据未做任何改动。"
            )
        selected = [r for r in self.records if r.id in record_ids]
        if filepath.lower().endswith(".csv"):
            ok = storage.export_records_csv(selected, filepath)
        else:
            ok = storage.export_records_json(selected, filepath)
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
