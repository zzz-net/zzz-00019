import os
import json
import csv
import copy
import sqlite3
from typing import List, Optional, Tuple, Dict
from models import (
    Device, Borrower, BorrowRecord, User, AppConfig,
    DeviceStatus, RecordStatus, UserRole, Accessory, _now_str,
    ImportPrecheckSummary, ImportLogEntry, MaintenanceRecord,
    InventorySession, InventoryItem, HandoffRecord, HandoffStatus,
    DeviceAccessory, AccessoryType
)


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
BORROWERS_FILE = os.path.join(DATA_DIR, "borrowers.json")
RECORDS_FILE = os.path.join(DATA_DIR, "records.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
IMPORT_LOGS_FILE = os.path.join(DATA_DIR, "import_logs.json")
MAINTENANCE_LOGS_FILE = os.path.join(DATA_DIR, "maintenance_logs.json")
INVENTORY_FILE = os.path.join(DATA_DIR, "inventory_sessions.json")
HANDOFF_DB_FILE = os.path.join(DATA_DIR, "handover_records.db")
ACCESSORIES_FILE = os.path.join(DATA_DIR, "accessories.json")


ACCESSORY_IMPORT_REQUIRED_FIELDS = [
    "device_id", "name"
]
ACCESSORY_IMPORT_OPTIONAL_FIELDS = [
    "device_name", "type", "quantity", "serial_no",
    "storage_location", "expiry_date", "responsible_person", "remark"
]


IMPORT_REQUIRED_FIELDS = [
    "device_id", "borrower_id", "borrow_time"
]
IMPORT_OPTIONAL_FIELDS = [
    "device_name", "borrower_name", "borrower_department",
    "expected_return_time", "actual_return_time", "status",
    "check_out_operator", "check_in_operator", "inspect_operator",
    "close_operator", "inspect_remark", "remark"
]


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
    ok, _ = check_dir_writable(dir_path)
    return ok


def check_dir_writable(dir_path: str) -> tuple[bool, str]:
    if not dir_path:
        return False, "目录路径为空"
    if not os.path.exists(dir_path):
        return False, f"目录不存在：{dir_path}"
    if not os.path.isdir(dir_path):
        return False, f"路径不是一个目录：{dir_path}"
    test_file = os.path.join(dir_path, f".write_test_{os.getpid()}.tmp")
    try:
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("test")
        os.remove(test_file)
        return True, "目录可写"
    except (IOError, OSError) as e:
        return False, f"目录没有写入权限：{dir_path}（{e}）"


def export_records_csv(records: List[BorrowRecord], filepath: str,
                       filter_info: Optional[dict] = None) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if filter_info:
                writer.writerow([f"# 导出筛选条件: {filter_info.get('description', '')}"])
                for k, v in filter_info.items():
                    if k != "description":
                        writer.writerow([f"# {k}: {v}"])
            writer.writerow([
                "记录ID", "设备ID", "设备名称", "借用人ID", "借用人",
                "借用人部门", "借出时间", "预计归还时间", "实际归还时间",
                "状态", "提醒状态", "借出操作员", "归还操作员", "验收操作员",
                "关闭操作员", "验收备注", "备注"
            ])
            for r in records:
                alert_status = filter_info.get("_alert_status", {}).get(r.id, "") if filter_info else ""
                writer.writerow([
                    r.id, r.device_id, r.device_name, r.borrower_id,
                    r.borrower_name, r.borrower_department, r.borrow_time,
                    r.expected_return_time, r.actual_return_time, r.status,
                    alert_status,
                    r.check_out_operator, r.check_in_operator,
                    r.inspect_operator, r.close_operator,
                    r.inspect_remark, r.remark
                ])
        return True
    except (IOError, OSError):
        return False


def export_records_json(records: List[BorrowRecord], filepath: str,
                        filter_info: Optional[dict] = None) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            data = {
                "export_time": _now_str(),
                "records": [r.to_dict() for r in records],
            }
            if filter_info:
                data["filter_info"] = dict(filter_info)
                if "_alert_status" in data["filter_info"]:
                    del data["filter_info"]["_alert_status"]
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except (IOError, OSError):
        return False


def export_devices_csv(devices: List[Device], filepath: str) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "设备ID", "名称", "类别", "型号", "序列号",
                "状态", "存放点", "负责人", "配件", "备注", "创建时间"
            ])
            for d in devices:
                acc_str = "; ".join([
                    f"{a.name}(必备)" if a.required else a.name
                    for a in d.accessories
                ])
                writer.writerow([
                    d.id, d.name, d.category, d.model, d.serial_no,
                    d.status, d.storage_location, d.responsible_person,
                    acc_str, d.remark, d.created_at
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
                storage_location="会议室A设备柜",
                responsible_person="张三",
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
                storage_location="行政部抽屉B2",
                responsible_person="李四",
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
                storage_location="会议室B",
                responsible_person="张三",
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
                storage_location="IT部维修区",
                responsible_person="王五",
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


def save_import_logs(logs: List[ImportLogEntry]):
    _save_json(IMPORT_LOGS_FILE, [l.to_dict() for l in logs])


def load_import_logs() -> List[ImportLogEntry]:
    data = _load_json(IMPORT_LOGS_FILE, [])
    return [ImportLogEntry.from_dict(d) for d in data]


def append_import_log(entry: ImportLogEntry):
    logs = load_import_logs()
    logs.append(entry)
    save_import_logs(logs)


def parse_import_csv(filepath: str) -> Tuple[bool, str, List[dict]]:
    if not os.path.exists(filepath):
        return False, f"文件不存在：{filepath}", []
    try:
        rows = []
        with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            if not fieldnames:
                return False, "CSV 文件为空或没有表头", []
            for i, row in enumerate(reader, start=2):
                clean_row = {}
                for k, v in row.items():
                    if k is not None:
                        clean_row[str(k).strip()] = str(v).strip() if v else ""
                clean_row["_row"] = i
                rows.append(clean_row)
        return True, "", rows
    except (IOError, OSError, csv.Error) as e:
        return False, f"CSV 解析失败：{e}", []


def parse_import_json(filepath: str) -> Tuple[bool, str, List[dict]]:
    if not os.path.exists(filepath):
        return False, f"文件不存在：{filepath}", []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return False, "JSON 根节点必须是数组", []
        rows = []
        for i, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                return False, f"第 {i} 项不是对象", []
            clean_row = {str(k).strip(): (str(v).strip() if isinstance(v, str) else v)
                         for k, v in item.items()}
            clean_row["_row"] = i
            rows.append(clean_row)
        return True, "", rows
    except (IOError, OSError, json.JSONDecodeError) as e:
        return False, f"JSON 解析失败：{e}", []


def parse_import_file(filepath: str) -> Tuple[bool, str, List[dict], str]:
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".csv":
        ok, msg, rows = parse_import_csv(filepath)
        return ok, msg, rows, "csv"
    elif ext == ".json":
        ok, msg, rows = parse_import_json(filepath)
        return ok, msg, rows, "json"
    else:
        return False, f"不支持的文件格式：{ext}（仅支持 .csv 和 .json）", [], ext


def save_maintenance_logs(logs: List[MaintenanceRecord]):
    _save_json(MAINTENANCE_LOGS_FILE, [l.to_dict() for l in logs])


def load_maintenance_logs() -> List[MaintenanceRecord]:
    data = _load_json(MAINTENANCE_LOGS_FILE, [])
    return [MaintenanceRecord.from_dict(d) for d in data]


def append_maintenance_log(entry: MaintenanceRecord):
    logs = load_maintenance_logs()
    logs.append(entry)
    save_maintenance_logs(logs)


def export_maintenance_csv(logs: List[MaintenanceRecord], filepath: str,
                           filter_info: Optional[dict] = None) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if filter_info:
                writer.writerow([f"# 导出筛选条件: {filter_info.get('description', '')}"])
                for k, v in filter_info.items():
                    if k != "description":
                        writer.writerow([f"# {k}: {v}"])
            writer.writerow([
                "维修记录ID", "设备ID", "设备名称", "送修前状态",
                "维修原因", "预计恢复时间", "经办人", "经办人角色",
                "送修时间", "结束时间", "状态", "撤销说明"
            ])
            for m in logs:
                status_text = "进行中" if m.status == "in_progress" else (
                    "已撤销" if m.status == "cancelled" else m.status
                )
                writer.writerow([
                    m.id, m.device_id, m.device_name, m.from_status,
                    m.reason, m.expected_recover_time, m.operator, m.operator_role,
                    m.start_time, m.end_time, status_text, m.cancel_remark
                ])
        return True
    except (IOError, OSError):
        return False


def export_maintenance_json(logs: List[MaintenanceRecord], filepath: str,
                            filter_info: Optional[dict] = None) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            data = {
                "export_time": _now_str(),
                "records": [m.to_dict() for m in logs],
            }
            if filter_info:
                data["filter_info"] = dict(filter_info)
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except (IOError, OSError):
        return False


def save_inventory_sessions(sessions: List[InventorySession]):
    _save_json(INVENTORY_FILE, [s.to_dict() for s in sessions])


def load_inventory_sessions() -> List[InventorySession]:
    data = _load_json(INVENTORY_FILE, [])
    return [InventorySession.from_dict(d) for d in data]


def export_inventory_csv(session: InventorySession, filepath: str,
                         operator: str = "", exception_count: int = 0) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([f"# 盘点标题: {session.title}"])
            writer.writerow([f"# 盘点ID: {session.id}"])
            writer.writerow([f"# 盘点状态: {session.status}"])
            writer.writerow([f"# 创建人: {session.created_by}"])
            writer.writerow([f"# 创建时间: {session.created_at}"])
            writer.writerow([f"# 完成时间: {session.completed_at}"])
            writer.writerow([f"# 导出操作人: {operator}"])
            writer.writerow([f"# 异常数量: {exception_count}"])
            if session.filter_conditions:
                writer.writerow(["# 筛选条件:"])
                for k, v in session.filter_conditions.items():
                    writer.writerow([f"#   {k}: {v}"])
            writer.writerow([
                "设备ID", "设备名称", "系统原状态", "盘点实际状态",
                "实际位置", "缺失配件", "盘点结果", "填写人", "填写时间", "备注"
            ])
            for it in session.items:
                writer.writerow([
                    it.device_id, it.device_name, it.original_status,
                    it.actual_status, it.actual_location,
                    "; ".join(it.missing_accessories),
                    it.inventory_result, it.filled_by,
                    it.filled_at, it.remark
                ])
        return True
    except (IOError, OSError):
        return False


def export_inventory_json(session: InventorySession, filepath: str,
                          operator: str = "", exception_count: int = 0) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            data = {
                "export_time": _now_str(),
                "export_operator": operator,
                "exception_count": exception_count,
                "session": session.to_dict(),
            }
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except (IOError, OSError):
        return False


HANDOFF_FIELDS = [
    "id", "device_id", "device_name", "action_type", "source_record_id",
    "current_holder_id", "current_holder_name", "target_holder_id",
    "target_holder_name", "business_status", "last_inventory_id",
    "last_inventory_result", "last_inventory_time", "admin_remark",
    "draft_remark", "borrower_confirm", "borrower_remark",
    "objection_reason", "created_by", "created_by_role", "created_at",
    "confirmed_by", "confirmed_at", "completed_by", "completed_at",
    "final_conclusion", "status"
]


def _get_handoff_conn():
    _ensure_data_dir()
    conn = sqlite3.connect(HANDOFF_DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS handoff_records (
            id TEXT PRIMARY KEY,
            device_id TEXT,
            device_name TEXT,
            action_type TEXT,
            source_record_id TEXT,
            current_holder_id TEXT,
            current_holder_name TEXT,
            target_holder_id TEXT,
            target_holder_name TEXT,
            business_status TEXT,
            last_inventory_id TEXT,
            last_inventory_result TEXT,
            last_inventory_time TEXT,
            admin_remark TEXT,
            draft_remark TEXT,
            borrower_confirm INTEGER,
            borrower_remark TEXT,
            objection_reason TEXT,
            created_by TEXT,
            created_by_role TEXT,
            created_at TEXT,
            confirmed_by TEXT,
            confirmed_at TEXT,
            completed_by TEXT,
            completed_at TEXT,
            final_conclusion TEXT,
            status TEXT
        )
    """)
    conn.commit()
    return conn


def save_handoff_records(records: List[HandoffRecord]):
    conn = _get_handoff_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM handoff_records")
        for r in records:
            values = []
            for f in HANDOFF_FIELDS:
                v = getattr(r, f)
                if isinstance(v, bool):
                    v = 1 if v else 0
                values.append(v)
            placeholders = ", ".join(["?"] * len(HANDOFF_FIELDS))
            cur.execute(
                f"INSERT INTO handoff_records ({', '.join(HANDOFF_FIELDS)}) VALUES ({placeholders})",
                values
            )
        conn.commit()
    finally:
        conn.close()


def load_handoff_records() -> List[HandoffRecord]:
    conn = _get_handoff_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {', '.join(HANDOFF_FIELDS)} FROM handoff_records ORDER BY created_at DESC")
        rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if "borrower_confirm" in d:
                d["borrower_confirm"] = bool(d["borrower_confirm"])
            result.append(HandoffRecord.from_dict(d))
        return result
    finally:
        conn.close()


def upsert_handoff_record(record: HandoffRecord):
    conn = _get_handoff_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM handoff_records WHERE id = ?", (record.id,))
        exists = cur.fetchone()
        values = []
        for f in HANDOFF_FIELDS:
            v = getattr(record, f)
            if isinstance(v, bool):
                v = 1 if v else 0
            values.append(v)
        if exists:
            assignments = ", ".join([f"{f} = ?" for f in HANDOFF_FIELDS])
            cur.execute(
                f"UPDATE handoff_records SET {assignments} WHERE id = ?",
                values + [record.id]
            )
        else:
            placeholders = ", ".join(["?"] * len(HANDOFF_FIELDS))
            cur.execute(
                f"INSERT INTO handoff_records ({', '.join(HANDOFF_FIELDS)}) VALUES ({placeholders})",
                values
            )
        conn.commit()
    finally:
        conn.close()


def delete_handoff_record(record_id: str):
    conn = _get_handoff_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM handoff_records WHERE id = ?", (record_id,))
        conn.commit()
    finally:
        conn.close()


def export_handoff_csv(records: List[HandoffRecord], filepath: str,
                       filter_info: Optional[dict] = None,
                       operator: str = "") -> bool:
    try:
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if filter_info:
                writer.writerow([f"# 导出筛选条件: {filter_info.get('description', '')}"])
                for k, v in filter_info.items():
                    if k != "description" and k != "_alert_status":
                        writer.writerow([f"# {k}: {v}"])
            writer.writerow([f"# 导出操作人: {operator}"])
            writer.writerow([f"# 导出时间: {_now_str()}"])
            writer.writerow([
                "交接记录ID", "设备ID", "设备名称", "交接动作", "关联业务单ID",
                "当前持有人ID", "当前持有人",
                "目标持有人ID", "目标持有人",
                "业务状态",
                "最近盘点ID", "最近盘点结论", "最近盘点时间",
                "管理员备注", "草稿备注",
                "借用人是否确认", "借用人确认备注", "异议原因",
                "创建人", "创建人角色", "创建时间",
                "确认人", "确认时间",
                "处理人(完成)", "完成时间",
                "最终结论", "当前状态"
            ])
            for r in records:
                writer.writerow([
                    r.id, r.device_id, r.device_name, r.action_type, r.source_record_id,
                    r.current_holder_id, r.current_holder_name,
                    r.target_holder_id, r.target_holder_name,
                    r.business_status,
                    r.last_inventory_id, r.last_inventory_result, r.last_inventory_time,
                    r.admin_remark, r.draft_remark,
                    "是" if r.borrower_confirm else "否",
                    r.borrower_remark, r.objection_reason,
                    r.created_by, r.created_by_role, r.created_at,
                    r.confirmed_by, r.confirmed_at,
                    r.completed_by, r.completed_at,
                    r.final_conclusion, r.status
                ])
        return True
    except (IOError, OSError):
        return False


def export_handoff_json(records: List[HandoffRecord], filepath: str,
                        filter_info: Optional[dict] = None,
                        operator: str = "") -> bool:
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            data = {
                "export_time": _now_str(),
                "export_operator": operator,
                "records": [r.to_dict() for r in records],
            }
            if filter_info:
                safe_filter = {k: v for k, v in filter_info.items() if k != "_alert_status"}
                data["filter_info"] = safe_filter
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except (IOError, OSError):
        return False


def save_accessories(accessories: List[DeviceAccessory]):
    _save_json(ACCESSORIES_FILE, [a.to_dict() for a in accessories])


def load_accessories() -> List[DeviceAccessory]:
    data = _load_json(ACCESSORIES_FILE, [])
    return [DeviceAccessory.from_dict(d) for d in data]


def export_accessories_csv(accessories: List[DeviceAccessory], filepath: str,
                           filter_info: Optional[dict] = None,
                           operator: str = "",
                           devices_map: Optional[Dict[str, Device]] = None) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([f"# 导出操作人: {operator}"])
            writer.writerow([f"# 导出时间: {_now_str()}"])
            if filter_info:
                writer.writerow([f"# 筛选条件: {filter_info.get('description', '')}"])
                for k, v in filter_info.items():
                    if k != "description":
                        writer.writerow([f"# {k}: {v}"])
            writer.writerow([
                "附件ID", "设备ID", "设备名称", "设备类别", "设备型号",
                "设备序列号", "设备状态", "设备存放点", "设备负责人",
                "附件/证照名称", "类型", "数量", "编号",
                "存放位置", "到期日", "责任人", "备注",
                "创建时间", "创建人", "更新时间", "更新人"
            ])
            for a in accessories:
                dev = devices_map.get(a.device_id) if devices_map else None
                writer.writerow([
                    a.id, a.device_id,
                    a.device_name if a.device_name else (dev.name if dev else ""),
                    dev.category if dev else "",
                    dev.model if dev else "",
                    dev.serial_no if dev else "",
                    dev.status if dev else "",
                    dev.storage_location if dev else "",
                    dev.responsible_person if dev else "",
                    a.name, a.type, a.quantity, a.serial_no,
                    a.storage_location, a.expiry_date, a.responsible_person, a.remark,
                    a.created_at, a.created_by, a.updated_at, a.updated_by
                ])
        return True
    except (IOError, OSError):
        return False


def export_accessories_json(accessories: List[DeviceAccessory], filepath: str,
                            filter_info: Optional[dict] = None,
                            operator: str = "",
                            devices_map: Optional[Dict[str, Device]] = None) -> bool:
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            records = []
            for a in accessories:
                rec = a.to_dict()
                dev = devices_map.get(a.device_id) if devices_map else None
                if dev:
                    rec["device_info"] = {
                        "category": dev.category,
                        "model": dev.model,
                        "serial_no": dev.serial_no,
                        "status": dev.status,
                        "storage_location": dev.storage_location,
                        "responsible_person": dev.responsible_person,
                    }
                records.append(rec)
            data = {
                "export_time": _now_str(),
                "export_operator": operator,
                "records": records,
            }
            if filter_info:
                data["filter_info"] = dict(filter_info)
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except (IOError, OSError):
        return False
