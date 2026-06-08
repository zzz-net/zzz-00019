import os
import json
import csv
from typing import List, Optional
from models import (
    Device, Borrower, BorrowRecord, User, AppConfig,
    DeviceStatus, RecordStatus, UserRole, Accessory, _now_str
)


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
BORROWERS_FILE = os.path.join(DATA_DIR, "borrowers.json")
RECORDS_FILE = os.path.join(DATA_DIR, "records.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")


def _ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)


def _save_json(filepath: str, data):
    _ensure_data_dir()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_json(filepath: str, default):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def save_devices(devices: List[Device]):
    _save_json(DEVICES_FILE, [d.to_dict() for d in devices])


def load_devices() -> List[Device]:
    data = _load_json(DEVICES_FILE, [])
    return [Device.from_dict(d) for d in data]


def save_borrowers(borrowers: List[Borrower]):
    _save_json(BORROWERS_FILE, [b.to_dict() for b in borrowers])


def load_borrowers() -> List[Borrower]:
    data = _load_json(BORROWERS_FILE, [])
    return [Borrower.from_dict(d) for d in data]


def save_records(records: List[BorrowRecord]):
    _save_json(RECORDS_FILE, [r.to_dict() for r in records])


def load_records() -> List[BorrowRecord]:
    data = _load_json(RECORDS_FILE, [])
    return [BorrowRecord.from_dict(d) for d in data]


def save_users(users: List[User]):
    _save_json(USERS_FILE, [u.to_dict() for u in users])


def load_users() -> List[User]:
    data = _load_json(USERS_FILE, [])
    return [User.from_dict(d) for d in data]


def save_config(config: AppConfig):
    _save_json(CONFIG_FILE, config.to_dict())


def load_config() -> AppConfig:
    data = _load_json(CONFIG_FILE, {})
    if data:
        return AppConfig.from_dict(data)
    return AppConfig()


def is_dir_writable(dir_path: str) -> bool:
    if not dir_path:
        return False
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError:
            return False
    if not os.path.isdir(dir_path):
        return False
    test_file = os.path.join(dir_path, f".write_test_{os.getpid()}.tmp")
    try:
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("test")
        os.remove(test_file)
        return True
    except (IOError, OSError):
        return False


def export_records_csv(records: List[BorrowRecord], filepath: str) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "记录ID", "设备ID", "设备名称", "借用人ID", "借用人",
                "借用人部门", "借出时间", "预计归还时间", "实际归还时间",
                "状态", "借出操作员", "归还操作员", "验收操作员",
                "关闭操作员", "验收备注", "备注"
            ])
            for r in records:
                writer.writerow([
                    r.id, r.device_id, r.device_name, r.borrower_id,
                    r.borrower_name, r.borrower_department, r.borrow_time,
                    r.expected_return_time, r.actual_return_time, r.status,
                    r.check_out_operator, r.check_in_operator,
                    r.inspect_operator, r.close_operator,
                    r.inspect_remark, r.remark
                ])
        return True
    except (IOError, OSError):
        return False


def export_records_json(records: List[BorrowRecord], filepath: str) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in records], f,
                      ensure_ascii=False, indent=2)
        return True
    except (IOError, OSError):
        return False


def export_devices_csv(devices: List[Device], filepath: str) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "设备ID", "名称", "类别", "型号", "序列号",
                "状态", "配件", "备注", "创建时间"
            ])
            for d in devices:
                acc_str = "; ".join([
                    f"{a.name}(必备)" if a.required else a.name
                    for a in d.accessories
                ])
                writer.writerow([
                    d.id, d.name, d.category, d.model, d.serial_no,
                    d.status, acc_str, d.remark, d.created_at
                ])
        return True
    except (IOError, OSError):
        return False


def export_devices_json(devices: List[Device], filepath: str) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([d.to_dict() for d in devices], f,
                      ensure_ascii=False, indent=2)
        return True
    except (IOError, OSError):
        return False


def seed_sample_data():
    _ensure_data_dir()

    if not os.path.exists(USERS_FILE):
        users = [
            User(username="admin", role=UserRole.ADMIN, display_name="系统管理员"),
            User(username="zhangsan", role=UserRole.BORROWER, display_name="张三"),
            User(username="lisi", role=UserRole.BORROWER, display_name="李四"),
            User(username="wangwu", role=UserRole.INSPECTOR, display_name="王五"),
            User(username="zhaoliu", role=UserRole.INSPECTOR, display_name="赵六"),
        ]
        save_users(users)

    if not os.path.exists(DEVICES_FILE):
        devices = [
            Device(
                name="爱普生投影仪 CB-X05", category="投影仪",
                model="CB-X05", serial_no="EPSN-2024-001",
                status=DeviceStatus.AVAILABLE,
                accessories=[
                    Accessory(name="电源适配器", required=True, present=True),
                    Accessory(name="HDMI线", required=True, present=True),
                    Accessory(name="VGA线", required=False, present=True),
                    Accessory(name="遥控器", required=True, present=True),
                ],
                remark="3LCD技术，3300流明"
            ),
            Device(
                name="索尼录音笔 ICD-PX470", category="录音笔",
                model="ICD-PX470", serial_no="SNY-2024-101",
                status=DeviceStatus.AVAILABLE,
                accessories=[
                    Accessory(name="USB充电线", required=True, present=True),
                    Accessory(name="立体声麦克风", required=False, present=False),
                ],
                remark="4GB内存，支持线性PCM录音"
            ),
            Device(
                name="明基投影仪 MW550", category="投影仪",
                model="MW550", serial_no="BENQ-2024-002",
                status=DeviceStatus.BORROWED,
                accessories=[
                    Accessory(name="电源适配器", required=True, present=True),
                    Accessory(name="HDMI线", required=True, present=True),
                    Accessory(name="遥控器", required=True, present=True),
                ],
                remark="3600流明，WXGA分辨率"
            ),
            Device(
                name="罗技摄像头 C920", category="摄像头",
                model="C920", serial_no="LOGT-2024-201",
                status=DeviceStatus.FROZEN,
                accessories=[
                    Accessory(name="USB数据线", required=True, present=True),
                    Accessory(name="镜头盖", required=False, present=False),
                ],
                remark="1080p高清，自动对焦"
            ),
        ]
        save_devices(devices)

    if not os.path.exists(BORROWERS_FILE):
        borrowers = [
            Borrower(name="张三", department="研发部", phone="13800000001"),
            Borrower(name="李四", department="市场部", phone="13800000002"),
            Borrower(name="陈七", department="人事部", phone="13800000007"),
        ]
        save_borrowers(borrowers)

    if not os.path.exists(RECORDS_FILE):
        devices = load_devices()
        borrowers = load_borrowers()
        dev = next((d for d in devices if d.status == DeviceStatus.BORROWED), None)
        bor = borrowers[0] if borrowers else None
        if dev and bor:
            record = BorrowRecord(
                device_id=dev.id, device_name=dev.name,
                borrower_id=bor.id, borrower_name=bor.name,
                borrower_department=bor.department,
                borrow_time="2026-06-05 09:30:00",
                expected_return_time="2026-06-07 18:00:00",
                status=RecordStatus.BORROWED,
                accessories_check_out=[
                    Accessory(name="电源适配器", required=True, present=True),
                    Accessory(name="HDMI线", required=True, present=True),
                    Accessory(name="遥控器", required=True, present=True),
                ],
                check_out_operator="admin",
                remark="季度会议使用"
            )
            record.add_history(
                DeviceStatus.AVAILABLE, RecordStatus.BORROWED,
                "admin", UserRole.ADMIN, "季度会议借出"
            )
            save_records([record])

    if not os.path.exists(CONFIG_FILE):
        config = AppConfig(
            export_dir=os.path.join(os.path.expanduser("~"), "Documents", "设备管理导出"),
            last_user="admin"
        )
        save_config(config)
