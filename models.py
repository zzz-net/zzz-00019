from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from datetime import datetime
import uuid
import json


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_id():
    return uuid.uuid4().hex[:8]


class DeviceStatus:
    AVAILABLE = "可借出"
    BORROWED = "已借出"
    FROZEN = "异常冻结"
    INSPECTING = "验收中"
    MAINTENANCE = "维修中"


class RecordStatus:
    BORROWED = "借出中"
    INSPECTING = "归还验收中"
    RETURNED = "已归还"
    FROZEN = "异常冻结"


class UserRole:
    ADMIN = "管理员"
    BORROWER = "借用人"
    INSPECTOR = "验收人"

    ALL_ROLES = [ADMIN, BORROWER, INSPECTOR]

    ROLE_PERMISSIONS = {
        ADMIN: ["add_device", "edit_device", "delete_device",
                "add_borrower", "borrow_device", "return_device",
                "inspect_return", "freeze_device", "unfreeze_device",
                "close_record", "export_data", "import_records", "view_all",
                "set_reminder_days",
                "send_to_maintenance", "cancel_maintenance",
                "view_maintenance", "export_maintenance",
                "create_inventory", "fill_inventory", "complete_inventory",
                "view_inventory", "export_inventory",
                "view_handoff_all", "create_handoff", "edit_handoff",
                "complete_handoff", "export_handoff",
                "view_own_handoff", "confirm_handoff", "object_handoff",
                "view_accessory_all", "add_accessory", "edit_accessory",
                "delete_accessory", "import_accessories", "export_accessories",
                "view_own_accessory"],
        BORROWER: ["borrow_device", "view_own", "export_data",
                   "view_own_inventory",
                   "view_own_handoff", "confirm_handoff", "object_handoff",
                   "view_own_accessory"],
        INSPECTOR: ["inspect_return", "return_device", "close_record",
                    "view_all", "export_data", "import_records",
                    "set_reminder_days",
                    "view_maintenance", "export_maintenance",
                    "fill_inventory", "view_inventory", "export_inventory",
                    "view_handoff_all", "export_handoff",
                    "view_own_handoff", "confirm_handoff", "object_handoff",
                    "view_accessory_all", "export_accessories",
                    "view_own_accessory"],
    }

    @classmethod
    def has_permission(cls, role: str, permission: str) -> bool:
        return permission in cls.ROLE_PERMISSIONS.get(role, [])


@dataclass
class Accessory:
    name: str
    required: bool = True
    present: bool = True

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)


@dataclass
class Device:
    id: str = field(default_factory=_new_id)
    name: str = ""
    category: str = ""
    model: str = ""
    serial_no: str = ""
    status: str = DeviceStatus.AVAILABLE
    storage_location: str = ""
    responsible_person: str = ""
    accessories: List[Accessory] = field(default_factory=list)
    remark: str = ""
    created_at: str = field(default_factory=_now_str)

    def to_dict(self):
        d = asdict(self)
        d["accessories"] = [a.to_dict() for a in self.accessories]
        return d

    @classmethod
    def from_dict(cls, d: dict):
        accs = [Accessory.from_dict(a) for a in d.get("accessories", [])]
        d = dict(d)
        d["accessories"] = accs
        return cls(**d)


@dataclass
class Borrower:
    id: str = field(default_factory=_new_id)
    name: str = ""
    department: str = ""
    phone: str = ""
    created_at: str = field(default_factory=_now_str)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)


@dataclass
class StatusHistoryItem:
    timestamp: str
    from_status: str
    to_status: str
    operator: str
    operator_role: str
    remark: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)


@dataclass
class BorrowRecord:
    id: str = field(default_factory=_new_id)
    device_id: str = ""
    device_name: str = ""
    borrower_id: str = ""
    borrower_name: str = ""
    borrower_department: str = ""
    borrow_time: str = field(default_factory=_now_str)
    expected_return_time: str = ""
    actual_return_time: str = ""
    status: str = RecordStatus.BORROWED
    accessories_check_out: List[Accessory] = field(default_factory=list)
    accessories_check_in: List[Accessory] = field(default_factory=list)
    check_out_operator: str = ""
    check_in_operator: str = ""
    inspect_operator: str = ""
    inspect_remark: str = ""
    close_operator: str = ""
    history: List[StatusHistoryItem] = field(default_factory=list)
    remark: str = ""

    def add_history(self, from_status: str, to_status: str,
                    operator: str, operator_role: str, remark: str = ""):
        self.history.append(StatusHistoryItem(
            timestamp=_now_str(),
            from_status=from_status,
            to_status=to_status,
            operator=operator,
            operator_role=operator_role,
            remark=remark,
        ))

    def to_dict(self):
        d = asdict(self)
        d["accessories_check_out"] = [a.to_dict() for a in self.accessories_check_out]
        d["accessories_check_in"] = [a.to_dict() for a in self.accessories_check_in]
        d["history"] = [h.to_dict() for h in self.history]
        return d

    @classmethod
    def from_dict(cls, d: dict):
        d = dict(d)
        d["accessories_check_out"] = [Accessory.from_dict(a) for a in d.get("accessories_check_out", [])]
        d["accessories_check_in"] = [Accessory.from_dict(a) for a in d.get("accessories_check_in", [])]
        d["history"] = [StatusHistoryItem.from_dict(h) for h in d.get("history", [])]
        return cls(**d)


@dataclass
class User:
    username: str = ""
    role: str = UserRole.BORROWER
    display_name: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)


@dataclass
class ImportPrecheckSummary:
    total: int = 0
    importable: int = 0
    field_missing: int = 0
    device_not_found: int = 0
    device_status_conflict: int = 0
    borrower_not_found: int = 0
    duplicate: int = 0
    issues: List[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)


@dataclass
class ImportLogEntry:
    timestamp: str = ""
    operator: str = ""
    operator_role: str = ""
    file_path: str = ""
    file_format: str = ""
    total: int = 0
    success_count: int = 0
    fail_count: int = 0
    fail_reasons: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)


@dataclass
class MaintenanceRecord:
    id: str = field(default_factory=_new_id)
    device_id: str = ""
    device_name: str = ""
    from_status: str = ""
    reason: str = ""
    expected_recover_time: str = ""
    operator: str = ""
    operator_role: str = ""
    start_time: str = field(default_factory=_now_str)
    end_time: str = ""
    status: str = "in_progress"
    cancel_remark: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)


@dataclass
class InventoryStatus:
    DRAFT = "草稿"
    IN_PROGRESS = "进行中"
    COMPLETED = "已完成"


class InventoryItemResult:
    NORMAL = "正常"
    MISSING = "丢失"
    DAMAGED = "损坏"
    LOCATION_WRONG = "位置错误"
    ACCESSORY_MISSING = "配件缺失"
    OTHER = "其他异常"

    ALL_RESULTS = [NORMAL, MISSING, DAMAGED, LOCATION_WRONG, ACCESSORY_MISSING, OTHER]


@dataclass
class InventoryItem:
    device_id: str = ""
    device_name: str = ""
    original_status: str = ""
    actual_status: str = ""
    actual_location: str = ""
    missing_accessories: List[str] = field(default_factory=list)
    remark: str = ""
    inventory_result: str = ""
    filled_by: str = ""
    filled_by_role: str = ""
    filled_at: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)


@dataclass
class InventorySession:
    id: str = field(default_factory=_new_id)
    title: str = ""
    status: str = InventoryStatus.DRAFT
    created_by: str = ""
    created_by_role: str = ""
    created_at: str = field(default_factory=_now_str)
    completed_at: str = ""
    completed_by: str = ""
    completed_by_role: str = ""
    filter_conditions: dict = field(default_factory=dict)
    items: List[InventoryItem] = field(default_factory=list)
    remark: str = ""

    def to_dict(self):
        d = asdict(self)
        d["items"] = [it.to_dict() for it in self.items]
        return d

    @classmethod
    def from_dict(cls, d: dict):
        d = dict(d)
        d["items"] = [InventoryItem.from_dict(it) for it in d.get("items", [])]
        return cls(**d)


class HandoffAction:
    BORROW_OUT = "借出"
    RETURN_BACK = "归还"
    MAINTENANCE_BACK = "维修后交回"
    FREEZE_RELEASE = "冻结解除"

    ALL_ACTIONS = [BORROW_OUT, RETURN_BACK, MAINTENANCE_BACK, FREEZE_RELEASE]


class HandoffStatus:
    PENDING = "待确认"
    CONFIRMED = "已确认"
    OBJECTED = "有异议"
    COMPLETED = "已完成"

    ALL_STATUSES = [PENDING, CONFIRMED, OBJECTED, COMPLETED]


@dataclass
class HandoffRecord:
    id: str = field(default_factory=_new_id)
    device_id: str = ""
    device_name: str = ""
    action_type: str = HandoffAction.BORROW_OUT
    source_record_id: str = ""
    current_holder_id: str = ""
    current_holder_name: str = ""
    target_holder_id: str = ""
    target_holder_name: str = ""
    business_status: str = ""
    last_inventory_id: str = ""
    last_inventory_result: str = ""
    last_inventory_time: str = ""
    admin_remark: str = ""
    draft_remark: str = ""
    borrower_confirm: bool = False
    borrower_remark: str = ""
    objection_reason: str = ""
    created_by: str = ""
    created_by_role: str = ""
    created_at: str = field(default_factory=_now_str)
    confirmed_by: str = ""
    confirmed_at: str = ""
    completed_by: str = ""
    completed_at: str = ""
    final_conclusion: str = ""
    status: str = HandoffStatus.PENDING

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)


class AccessoryType:
    ACCESSORY = "附件"
    CERTIFICATE = "证照"

    ALL_TYPES = [ACCESSORY, CERTIFICATE]


@dataclass
class DeviceAccessory:
    id: str = field(default_factory=_new_id)
    device_id: str = ""
    device_name: str = ""
    name: str = ""
    type: str = AccessoryType.ACCESSORY
    quantity: int = 1
    serial_no: str = ""
    storage_location: str = ""
    expiry_date: str = ""
    responsible_person: str = ""
    remark: str = ""
    created_at: str = field(default_factory=_now_str)
    created_by: str = ""
    created_by_role: str = ""
    updated_at: str = ""
    updated_by: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)


@dataclass
class AppConfig:
    export_dir: str = ""
    last_user: str = ""
    last_import_dir: str = ""
    last_import_format: str = ""
    last_import_summary: dict = field(default_factory=dict)
    reminder_days: int = 3
    default_maintenance_days: int = 7
    last_maintenance_filter: dict = field(default_factory=dict)
    maintenance_records_snapshot: dict = field(default_factory=dict)
    last_inventory_filter: dict = field(default_factory=dict)
    last_active_inventory_session_id: str = ""
    last_handoff_filter: dict = field(default_factory=dict)
    last_accessory_filter: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)
