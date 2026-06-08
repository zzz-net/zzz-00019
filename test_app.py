import os
import sys
import shutil
import tempfile
import csv
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (
    Device, Borrower, BorrowRecord, Accessory, User, AppConfig,
    DeviceStatus, RecordStatus, UserRole, MaintenanceRecord
)
from business import EquipmentManager, BusinessError
import storage


TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_test")


def setup_test_env():
    if os.path.exists(TEST_DATA_DIR):
        shutil.rmtree(TEST_DATA_DIR)
    os.makedirs(TEST_DATA_DIR, exist_ok=True)
    storage.DATA_DIR = TEST_DATA_DIR
    storage.DEVICES_FILE = os.path.join(TEST_DATA_DIR, "devices.json")
    storage.BORROWERS_FILE = os.path.join(TEST_DATA_DIR, "borrowers.json")
    storage.RECORDS_FILE = os.path.join(TEST_DATA_DIR, "records.json")
    storage.USERS_FILE = os.path.join(TEST_DATA_DIR, "users.json")
    storage.CONFIG_FILE = os.path.join(TEST_DATA_DIR, "config.json")
    storage.IMPORT_LOGS_FILE = os.path.join(TEST_DATA_DIR, "import_logs.json")
    storage.MAINTENANCE_LOGS_FILE = os.path.join(TEST_DATA_DIR, "maintenance_logs.json")


def cleanup_test_env():
    if os.path.exists(TEST_DATA_DIR):
        shutil.rmtree(TEST_DATA_DIR)


passed = 0
failed = 0


def assert_eq(actual, expected, msg=""):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  [PASS] {msg}")
    else:
        failed += 1
        print(f"  [FAIL] {msg}")
        print(f"         期望: {expected}")
        print(f"         实际: {actual}")


def assert_true(cond, msg=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {msg}")
    else:
        failed += 1
        print(f"  [FAIL] {msg}")


def assert_raises(fn, exc_type, msg=""):
    global passed, failed
    try:
        fn()
        failed += 1
        print(f"  [FAIL] {msg} - 期望抛出 {exc_type.__name__}，但无异常")
    except exc_type:
        passed += 1
        print(f"  [PASS] {msg}")
    except Exception as e:
        failed += 1
        print(f"  [FAIL] {msg} - 期望 {exc_type.__name__}，实际 {type(e).__name__}: {e}")


def test_basic_data_and_permissions():
    print("\n=== 测试1: 基础数据加载 & 权限切换 ===")
    mgr = _fresh_manager()

    assert_true(len(mgr.devices) >= 3, "样例设备加载")
    assert_true(len(mgr.borrowers) >= 2, "样例借用人加载")
    assert_true(len(mgr.users) >= 3, "样例用户加载")
    assert_true(mgr.current_user is not None, "默认用户已登录")

    mgr.switch_user("admin")
    assert_eq(mgr.current_user.role, UserRole.ADMIN, "切换到管理员")
    assert_true(mgr.has_permission("add_device"), "管理员有添加设备权限")
    assert_true(mgr.has_permission("close_record"), "管理员有关闭冻结权限")

    mgr.switch_user("zhangsan")
    assert_eq(mgr.current_user.role, UserRole.BORROWER, "切换到借用人张三")
    assert_true(mgr.has_permission("borrow_device"), "借用人有借出权限")
    assert_true(not mgr.has_permission("inspect_return"), "借用人无验收权限")
    assert_true(not mgr.has_permission("close_record"), "借用人无关闭冻结权限")
    assert_true(not mgr.has_permission("add_device"), "借用人无增设备权限")

    mgr.switch_user("wangwu")
    assert_eq(mgr.current_user.role, UserRole.INSPECTOR, "切换到验收人王五")
    assert_true(mgr.has_permission("inspect_return"), "验收人有验收权限")
    assert_true(not mgr.has_permission("add_device"), "验收人无增设备权限")


def _fresh_manager():
    setup_test_env()
    return EquipmentManager()


def test_borrow_flow_success():
    print("\n=== 测试2: 正常借出流程 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    avail_device = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
    borrower = mgr.borrowers[0]

    record = mgr.borrow_device(
        device_id=avail_device.id,
        borrower_id=borrower.id,
        expected_return_time="2026-06-10 18:00:00",
        accessories=[Accessory(name=a.name, required=a.required, present=True)
                     for a in avail_device.accessories],
        remark="单元测试借出"
    )

    assert_eq(record.device_name, avail_device.name, "记录关联正确设备")
    assert_eq(record.borrower_name, borrower.name, "记录关联正确借用人")
    assert_eq(record.status, RecordStatus.BORROWED, "记录状态: 借出中")
    assert_eq(mgr.find_device(avail_device.id).status,
              DeviceStatus.BORROWED, "设备状态同步为已借出")
    assert_true(len(record.history) >= 1, "状态历史有记录")
    assert_eq(record.history[-1].to_status, RecordStatus.BORROWED,
              "历史最后状态为借出中")
    assert_eq(record.check_out_operator, "admin", "登记操作员正确")


def test_borrow_fail_duplicate():
    print("\n=== 测试3: 失败路径 - 已借出设备不能再次借出 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    borrowed_device = next(d for d in mgr.devices if d.status == DeviceStatus.BORROWED)
    borrower = mgr.borrowers[0]

    def try_borrow():
        mgr.borrow_device(
            device_id=borrowed_device.id,
            borrower_id=borrower.id,
            accessories=borrowed_device.accessories
        )

    assert_raises(try_borrow, BusinessError, "重复借出抛出异常")


def test_borrow_fail_frozen():
    print("\n=== 测试4: 失败路径 - 冻结设备不能借出 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    frozen_device = next(d for d in mgr.devices if d.status == DeviceStatus.FROZEN)
    borrower = mgr.borrowers[0]

    def try_borrow():
        mgr.borrow_device(
            device_id=frozen_device.id,
            borrower_id=borrower.id,
            accessories=frozen_device.accessories
        )

    assert_raises(try_borrow, BusinessError, "冻结设备借出抛出异常")


def test_return_and_inspect_freeze():
    print("\n=== 测试5: 归还验收 - 缺少必备配件 -> 异常冻结 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    avail_device = next(d for d in mgr.devices
                        if d.status == DeviceStatus.AVAILABLE
                        and any(a.required for a in d.accessories))
    borrower = mgr.borrowers[0]

    record = mgr.borrow_device(
        device_id=avail_device.id,
        borrower_id=borrower.id,
        accessories=[Accessory(name=a.name, required=a.required, present=True)
                     for a in avail_device.accessories],
        remark="验收冻结测试"
    )

    mgr.switch_user("wangwu")
    bad_acc = []
    for a in record.accessories_check_out:
        if a.required and bad_acc == []:
            bad_acc.append(Accessory(name=a.name, required=a.required, present=False))
        else:
            bad_acc.append(Accessory(name=a.name, required=a.required, present=a.present))

    record = mgr.submit_return(record.id, accessories=bad_acc, remark="归还")
    assert_eq(record.status, RecordStatus.INSPECTING, "提交后状态: 验收中")

    mgr.switch_user("wangwu")
    record, is_frozen = mgr.inspect_return(record.id, accessories=bad_acc,
                                           inspect_remark="发现缺配件")
    assert_true(is_frozen, "验收后记录被冻结")
    assert_eq(record.status, RecordStatus.FROZEN, "记录状态: 异常冻结")
    assert_eq(mgr.find_device(avail_device.id).status,
              DeviceStatus.FROZEN, "设备同步冻结")


def test_borrower_cannot_close_frozen():
    print("\n=== 测试6: 失败路径 - 借用人不能关闭冻结记录 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    avail_device = next(d for d in mgr.devices
                        if d.status == DeviceStatus.AVAILABLE
                        and any(a.required for a in d.accessories))
    borrower = mgr.borrowers[0]

    record = mgr.borrow_device(
        device_id=avail_device.id,
        borrower_id=borrower.id,
        accessories=[Accessory(name=a.name, required=a.required, present=True)
                     for a in avail_device.accessories]
    )

    bad_acc = []
    for a in record.accessories_check_out:
        if a.required and bad_acc == []:
            bad_acc.append(Accessory(name=a.name, required=a.required, present=False))
        else:
            bad_acc.append(Accessory(name=a.name, required=a.required, present=a.present))

    mgr.switch_user("admin")
    record = mgr.submit_return(record.id, accessories=bad_acc)
    record, _ = mgr.inspect_return(record.id, accessories=bad_acc)
    assert_eq(record.status, RecordStatus.FROZEN, "确认记录已冻结")

    mgr.switch_user("zhangsan")
    def try_close():
        mgr.close_record(record.id, "尝试关闭")

    assert_raises(try_close, BusinessError, "借用人关闭冻结记录抛出异常")


def test_inspector_can_close_frozen():
    print("\n=== 测试7: 验收人可以关闭冻结记录 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    avail_device = next(d for d in mgr.devices
                        if d.status == DeviceStatus.AVAILABLE
                        and any(a.required for a in d.accessories))
    borrower = mgr.borrowers[0]

    record = mgr.borrow_device(
        device_id=avail_device.id,
        borrower_id=borrower.id,
        accessories=[Accessory(name=a.name, required=a.required, present=True)
                     for a in avail_device.accessories]
    )

    bad_acc = []
    for a in record.accessories_check_out:
        if a.required and bad_acc == []:
            bad_acc.append(Accessory(name=a.name, required=a.required, present=False))
        else:
            bad_acc.append(Accessory(name=a.name, required=a.required, present=a.present))

    mgr.switch_user("admin")
    record = mgr.submit_return(record.id, accessories=bad_acc)
    record, _ = mgr.inspect_return(record.id, accessories=bad_acc)

    mgr.switch_user("wangwu")
    record = mgr.close_record(record.id, "验收人关闭冻结")
    assert_eq(record.status, RecordStatus.RETURNED, "关闭后记录已归还")
    assert_eq(mgr.find_device(avail_device.id).status,
              DeviceStatus.AVAILABLE, "设备已解冻恢复可借出")
    assert_true(len(record.history) >= 4, "状态历史完整")


def test_persistence():
    print("\n=== 测试8: 本地持久化（关闭重开数据仍在） ===")
    setup_test_env()
    mgr1 = EquipmentManager()
    mgr1.switch_user("admin")
    avail_device = next(d for d in mgr1.devices if d.status == DeviceStatus.AVAILABLE)
    borrower = mgr1.borrowers[0]
    record = mgr1.borrow_device(
        device_id=avail_device.id,
        borrower_id=borrower.id,
        remark="持久化测试"
    )
    record_id = record.id
    device_id = avail_device.id

    mgr2 = EquipmentManager()
    device2 = mgr2.find_device(device_id)
    record2 = mgr2.find_record(record_id)

    assert_true(device2 is not None, "设备持久化存在")
    assert_eq(device2.status, DeviceStatus.BORROWED, "设备状态持久化正确")
    assert_true(record2 is not None, "记录持久化存在")
    assert_eq(record2.status, RecordStatus.BORROWED, "记录状态持久化正确")
    assert_eq(record2.remark, "持久化测试", "备注持久化正确")


def test_export_dir_writable():
    print("\n=== 测试9: 导出目录不可写时的校验 ===")
    mgr = _fresh_manager()

    ok, _ = mgr.set_export_dir("")
    assert_true(not ok, "空目录设置失败")

    ok, _ = mgr.set_export_dir("Z:\\NonExistentDrive\\exports")
    assert_true(not ok, "不存在的盘符路径设置失败")

    with tempfile.TemporaryDirectory() as tmpdir:
        ok, _ = mgr.set_export_dir(tmpdir)
        assert_true(ok, "临时目录设置成功")
        assert_true(mgr.can_write_to_export_dir(), "临时目录可写")


def test_export_csv_json():
    print("\n=== 测试10: CSV/JSON 导出（与界面数据一致） ===")
    mgr = _fresh_manager()
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr.set_export_dir(tmpdir)

        csv_path = os.path.join(tmpdir, "records.csv")
        ok, msg = mgr.export_selected_records([mgr.records[0].id], csv_path)
        assert_true(ok, "CSV 导出成功: " + msg)
        assert_true(os.path.exists(csv_path) and os.path.getsize(csv_path) > 0,
                    "CSV 文件存在且非空")

        json_path = os.path.join(tmpdir, "records.json")
        ok, msg = mgr.export_selected_records([mgr.records[0].id], json_path)
        assert_true(ok, "JSON 导出成功: " + msg)
        assert_true(os.path.exists(json_path) and os.path.getsize(json_path) > 0,
                    "JSON 文件存在且非空")

        dev_csv = os.path.join(tmpdir, "devices.csv")
        ok, msg = mgr.export_all_devices(dev_csv)
        assert_true(ok, "设备 CSV 导出成功")
        assert_true(os.path.exists(dev_csv) and os.path.getsize(dev_csv) > 0,
                    "设备 CSV 文件存在且非空")


def test_borrower_view_filter():
    print("\n=== 测试11: 借用人仅能查看自己的记录 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")
    all_count = len(mgr.get_filtered_records())

    mgr.switch_user("zhangsan")
    filtered = mgr.get_filtered_records()
    for r in filtered:
        assert_true(
            r.borrower_name == "张三" or r.borrower_id == "zhangsan",
            f"借用人看到的记录属于自己 ({r.borrower_name})"
        )
    assert_true(len(filtered) <= all_count, "借用人记录数 <= 全部记录数")


def test_force_accept_inspection():
    print("\n=== 测试12: 强制通过验收（忽略缺配件） ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    avail_device = next(d for d in mgr.devices
                        if d.status == DeviceStatus.AVAILABLE
                        and any(a.required for a in d.accessories))
    borrower = mgr.borrowers[0]

    record = mgr.borrow_device(
        device_id=avail_device.id,
        borrower_id=borrower.id,
        accessories=[Accessory(name=a.name, required=a.required, present=True)
                     for a in avail_device.accessories]
    )

    bad_acc = []
    for a in record.accessories_check_out:
        if a.required and bad_acc == []:
            bad_acc.append(Accessory(name=a.name, required=a.required, present=False))
        else:
            bad_acc.append(Accessory(name=a.name, required=a.required, present=a.present))

    mgr.switch_user("admin")
    record = mgr.submit_return(record.id, accessories=bad_acc)
    record, is_frozen = mgr.inspect_return(record.id, accessories=bad_acc,
                                           inspect_remark="强制通过", force_accept=True)
    assert_true(not is_frozen, "强制通过不会冻结")
    assert_eq(record.status, RecordStatus.RETURNED, "强制通过后记录已归还")
    assert_eq(mgr.find_device(avail_device.id).status,
              DeviceStatus.AVAILABLE, "设备恢复可借出")


def test_missing_subdir_not_created_and_config_not_polluted():
    print("\n=== 测试13: 缺失子目录 - 不自动创建、不污染配置 ===")
    setup_test_env()
    mgr = EquipmentManager()
    original_dir = mgr.config.export_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        missing_subdir = os.path.join(tmpdir, "does", "not", "exist")
        assert_true(not os.path.exists(missing_subdir),
                    "前置条件：子目录确实不存在")

        ok, msg = mgr.set_export_dir(missing_subdir)
        assert_true(not ok, "缺失子目录设置返回失败")
        assert_true("不存在" in msg, f"错误信息包含'不存在'关键词（实际：{msg}")
        assert_true("不会自动创建" in msg,
                    f"错误信息提示不会自动创建（实际：{msg}）")
        assert_true(not os.path.exists(missing_subdir),
                    "缺失子目录没有被悄悄创建")
        assert_eq(mgr.config.export_dir, original_dir,
                  "失败时 config.export_dir 保持原值，不被污染")

    mgr2 = EquipmentManager()
    assert_eq(mgr2.config.export_dir, original_dir,
              "跨重启：配置文件中 export_dir 仍是原始合法值")


def test_invalidated_dir_export_fails_no_file_and_data_intact():
    print("\n=== 测试14: 目录失效（被删除）- 导出失败、不生成文件、不改动数据 ===")
    setup_test_env()
    mgr = EquipmentManager()

    with tempfile.TemporaryDirectory() as tmpdir:
        ok, _ = mgr.set_export_dir(tmpdir)
        assert_true(ok, "先设置一个合法的临时目录成功")

    assert_true(not os.path.exists(tmpdir), "前置条件：临时目录已被 with 块删除")
    assert_eq(mgr.config.export_dir, tmpdir,
              "配置仍保留上次合法路径（只是现在失效）")
    assert_true(not mgr.can_write_to_export_dir(),
                "can_write_to_export_dir 正确返回 False")
    ok, reason = mgr.check_export_dir_detail()
    assert_true(not ok, "check_export_dir_detail 返回失败")
    assert_true("不存在" in reason or "失效" in reason or "不可用" in reason,
                f"详细原因包含目录状态信息（实际：{reason}）")

    fake_csv = os.path.join(tmpdir, "should_not_exist.csv")
    ok, msg = mgr.export_selected_records([mgr.records[0].id], fake_csv)
    assert_true(not ok, "导出操作明确返回失败")
    assert_true("不可用" in msg or "不存在" in msg or "失败" in msg,
                f"导出失败提示对用户友好（实际：{msg[:80]}）")
    assert_true(not os.path.exists(fake_csv),
                "不生成任何导出文件（连目录都不应被创建）")
    assert_true(not os.path.exists(tmpdir),
                "失效的父目录也没有被重新创建")

    record_before = mgr.records[0].to_dict()
    ok, _ = mgr.export_selected_records([mgr.records[0].id], fake_csv)
    record_after = mgr.records[0].to_dict()
    assert_eq(record_before, record_after,
              "导出失败不改动任何已选记录数据")

    ok, _ = mgr.export_all_devices(os.path.join(tmpdir, "devs.json"))
    assert_true(not ok, "设备导出也失败")
    assert_eq(mgr.config.export_dir, tmpdir,
              "导出失败不覆盖已保存的常用导出目录")


def test_unwritable_dir_not_saved():
    print("\n=== 测试15: 无写入权限目录 - 不保存进配置 ===")
    setup_test_env()
    mgr = EquipmentManager()
    original_dir = mgr.config.export_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        readonly_dir = os.path.join(tmpdir, "readonly")
        os.makedirs(readonly_dir, exist_ok=True)
        try:
            os.chmod(readonly_dir, 0o444)
            ok_write_test = storage.is_dir_writable(readonly_dir)
            if not ok_write_test:
                ok, msg = mgr.set_export_dir(readonly_dir)
                assert_true(not ok, "只读目录设置返回失败")
                assert_true("权限" in msg or "写入" in msg,
                            f"错误信息包含权限关键词（实际：{msg}）")
                assert_eq(mgr.config.export_dir, original_dir,
                          "失败时配置保持原值")
            else:
                assert_true(True,
                            "当前环境下 0o444 目录仍可写（Windows 常见），跳过权限硬验证")
        finally:
            os.chmod(readonly_dir, 0o777)


def test_valid_dir_still_works_after_failed_attempts():
    print("\n=== 测试16: 失败尝试后合法目录仍正常导出 ===")
    setup_test_env()
    mgr = EquipmentManager()

    mgr.set_export_dir("Z:\\BadPath\\NoSuch")
    mgr.set_export_dir("")

    with tempfile.TemporaryDirectory() as tmpdir:
        ok, msg = mgr.set_export_dir(tmpdir)
        assert_true(ok, f"合法目录设置成功（{msg}）")
        assert_eq(mgr.config.export_dir, tmpdir,
                  "合法目录成功写入配置")

        csv_path = os.path.join(tmpdir, "r.csv")
        ok, msg = mgr.export_selected_records([mgr.records[0].id], csv_path)
        assert_true(ok, f"CSV 导出成功: {msg}")
        assert_true(os.path.exists(csv_path) and os.path.getsize(csv_path) > 0,
                    "CSV 文件真实存在且非空")

        json_path = os.path.join(tmpdir, "d.json")
        ok, msg = mgr.export_all_devices(json_path)
        assert_true(ok, "设备 JSON 导出成功")
        assert_true(os.path.exists(json_path) and os.path.getsize(json_path) > 0,
                    "JSON 文件真实存在且非空")


def test_last_valid_dir_preserved_across_restart():
    print("\n=== 测试17: 跨重启只保留上一次合法目录 ===")
    setup_test_env()
    mgr1 = EquipmentManager()

    with tempfile.TemporaryDirectory() as tmpdir:
        ok, _ = mgr1.set_export_dir(tmpdir)
        assert_true(ok, "首次设置合法目录")
        valid_dir = mgr1.config.export_dir

        mgr1.set_export_dir("Z:\\InvalidDir\\Sub")
        assert_eq(mgr1.config.export_dir, valid_dir,
                  "失败尝试未覆盖内存中的合法目录")

        mgr2 = EquipmentManager()
        assert_eq(mgr2.config.export_dir, valid_dir,
                  "跨重启：配置文件仅保存了上一次成功的合法目录")
        assert_true(mgr2.can_write_to_export_dir(),
                    "跨重启后合法目录仍可写")

    mgr3 = EquipmentManager()
    assert_eq(mgr3.config.export_dir, valid_dir,
              "即使合法目录已被删除，配置仍保留原值（由 GUI 显示为【已失效】）")
    assert_true(not mgr3.can_write_to_export_dir(),
                "目录被删除后 can_write 返回 False")


def _write_csv(path: str, rows: list):
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        if not rows:
            return
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _write_json(path: str, data: list):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def test_import_permission_denied_for_borrower():
    print("\n=== 测试18: 借用人无批量导入权限 ===")
    mgr = _fresh_manager()
    mgr.switch_user("zhangsan")

    def try_precheck():
        mgr.precheck_import_file("dummy.csv")

    def try_commit():
        mgr.commit_import("dummy.csv")

    def try_logs():
        mgr.get_import_logs()

    assert_raises(try_precheck, BusinessError, "借用人预检抛出权限异常")
    assert_raises(try_commit, BusinessError, "借用人提交导入抛出权限异常")
    assert_raises(try_logs, BusinessError, "借用人查看日志抛出权限异常")
    assert_true(not mgr.has_permission("import_records"),
                "借用人角色无 import_records 权限")


def test_import_admin_and_inspector_allowed():
    print("\n=== 测试19: 管理员和验收人拥有导入权限 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")
    assert_true(mgr.has_permission("import_records"), "管理员有 import_records 权限")
    mgr.switch_user("wangwu")
    assert_true(mgr.has_permission("import_records"), "验收人有 import_records 权限")


def test_import_precheck_detects_all_issues():
    print("\n=== 测试20: 预检正确识别各类问题 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    avail_dev = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
    borrowed_dev = next(d for d in mgr.devices if d.status == DeviceStatus.BORROWED)
    frozen_dev = next(d for d in mgr.devices if d.status == DeviceStatus.FROZEN)
    borrower = mgr.borrowers[0]

    with tempfile.TemporaryDirectory() as tmpdir:
        rows = [
            {"device_id": "", "borrower_id": borrower.id, "borrow_time": "2026-06-01 10:00:00"},
            {"device_id": avail_dev.id, "borrower_id": "", "borrow_time": "2026-06-01 10:00:00"},
            {"device_id": avail_dev.id, "borrower_id": borrower.id, "borrow_time": ""},
            {"device_id": "NO_SUCH_DEVICE", "borrower_id": borrower.id, "borrow_time": "2026-06-01 10:00:00"},
            {"device_id": avail_dev.id, "borrower_id": "NO_SUCH_BORROWER", "borrow_time": "2026-06-01 10:00:00"},
            {"device_id": borrowed_dev.id, "borrower_id": borrower.id, "borrow_time": "2026-06-02 10:00:00"},
            {"device_id": avail_dev.id, "borrower_id": borrower.id, "borrow_time": "2026-06-03 10:00:00"},
            {"device_id": avail_dev.id, "borrower_id": borrower.id, "borrow_time": "2026-06-03 10:00:00"},
        ]
        csv_path = os.path.join(tmpdir, "precheck.csv")
        _write_csv(csv_path, rows)

        ok, msg, summary = mgr.precheck_import_file(csv_path)
        assert_true(ok, "预检执行成功：" + msg)
        assert_eq(summary.total, 8, "总数为 8")
        assert_true(summary.field_missing >= 3, f"字段缺失 >= 3（实际 {summary.field_missing}）")
        assert_eq(summary.device_not_found, 1, "设备不存在 1 条")
        assert_eq(summary.borrower_not_found, 1, "借用人不存在 1 条")
        assert_true(summary.device_status_conflict >= 1,
                    f"设备状态冲突 >= 1（实际 {summary.device_status_conflict}）")
        assert_true(summary.duplicate >= 1, f"重复记录 >= 1（实际 {summary.duplicate}）")
        assert_true(len(summary.issues) > 0, "问题明细列表非空")
        kinds = {i["kind"] for i in summary.issues}
        assert_true("字段缺失" in kinds, "问题类型包含：字段缺失")
        assert_true("设备不存在" in kinds, "问题类型包含：设备不存在")
        assert_true("借用人不存在" in kinds, "问题类型包含：借用人不存在")


def test_import_csv_and_json_success():
    print("\n=== 测试21: CSV / JSON 双格式成功导入 ===")
    for fmt_name, writer in [("CSV", _write_csv), ("JSON", _write_json)]:
        mgr = _fresh_manager()
        mgr.switch_user("admin")

        avail_devs = [d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE]
        assert_true(len(avail_devs) >= 2, f"可用设备 >= 2（{fmt_name}）")
        borrower = mgr.borrowers[0]

        records_before = len(mgr.records)
        dev0_status_before = avail_devs[0].status
        dev1_status_before = avail_devs[1].status

        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {
                    "device_id": avail_devs[0].id,
                    "borrower_id": borrower.id,
                    "borrow_time": "2026-06-01 09:00:00",
                    "expected_return_time": "2026-06-05 18:00:00",
                    "status": RecordStatus.BORROWED,
                    "remark": f"{fmt_name} 导入测试 #1",
                },
                {
                    "device_id": avail_devs[1].id,
                    "borrower_id": borrower.id,
                    "borrow_time": "2026-06-02 14:00:00",
                    "expected_return_time": "2026-06-06 18:00:00",
                    "status": RecordStatus.BORROWED,
                    "remark": f"{fmt_name} 导入测试 #2",
                },
            ]
            path = os.path.join(tmpdir, f"import_ok.{fmt_name.lower()}")
            writer(path, rows)

            ok, msg, sc, fc = mgr.commit_import(path)
            assert_true(ok, f"{fmt_name} 导入成功：{msg}")
            assert_eq(sc, 2, f"{fmt_name} 成功 2 条")
            assert_eq(fc, 0, f"{fmt_name} 失败 0 条")
            assert_eq(len(mgr.records), records_before + 2,
                      f"{fmt_name} 记录数 +2")

            d0 = mgr.find_device(avail_devs[0].id)
            d1 = mgr.find_device(avail_devs[1].id)
            assert_eq(d0.status, DeviceStatus.BORROWED,
                      f"{fmt_name} 设备 0 状态同步为已借出")
            assert_eq(d1.status, DeviceStatus.BORROWED,
                      f"{fmt_name} 设备 1 状态同步为已借出")

            new_records = [r for r in mgr.records
                           if r.remark and f"{fmt_name} 导入测试" in r.remark]
            assert_eq(len(new_records), 2, f"{fmt_name} 找到 2 条新记录")
            for r in new_records:
                assert_true(len(r.history) >= 1,
                            f"{fmt_name} 新记录带状态历史")
                assert_true("批量导入" in r.history[-1].remark,
                            f"{fmt_name} 历史备注包含'批量导入'")
                assert_eq(r.check_out_operator, "admin",
                          f"{fmt_name} 操作员正确")


def test_import_rollback_on_conflict():
    print("\n=== 测试22: 中途冲突整批回滚，不留半条记录 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    avail_dev = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
    borrower = mgr.borrowers[0]
    records_before = len(mgr.records)
    devices_snapshot = [(d.id, d.status) for d in mgr.devices]

    with tempfile.TemporaryDirectory() as tmpdir:
        rows = [
            {
                "device_id": avail_dev.id,
                "borrower_id": borrower.id,
                "borrow_time": "2026-06-01 10:00:00",
                "status": RecordStatus.BORROWED,
            },
        ]
        path = os.path.join(tmpdir, "rollback.json")
        _write_json(path, rows)

        original_save_all = EquipmentManager.save_all
        call_counter = {"n": 0}

        def patched_save_all(self_inner):
            call_counter["n"] += 1
            if call_counter["n"] >= 2:
                raise RuntimeError("模拟持久化写入故障")
            return original_save_all(self_inner)

        EquipmentManager.save_all = patched_save_all
        try:
            ok, msg, sc, fc = mgr.commit_import(path)
        finally:
            EquipmentManager.save_all = original_save_all

        assert_true(not ok, "导入返回失败")
        assert_true("回滚" in msg, f"失败信息包含'回滚'（实际：{msg[:80]}）")
        assert_eq(len(mgr.records), records_before,
                  "回滚后记录数与导入前一致")
        for (did, dstatus), d in zip(devices_snapshot, mgr.devices):
            assert_eq(d.id, did, "设备ID顺序未变")
            assert_eq(d.status, dstatus,
                      f"设备 {did} 状态回滚到 {dstatus}")

        mgr2 = EquipmentManager()
        assert_eq(len(mgr2.records), records_before,
                  "跨重启：持久化文件也已回滚，无半条记录")


def test_import_config_persisted_across_restart():
    print("\n=== 测试23: 导入目录/格式/预检摘要跨重启保留 ===")
    setup_test_env()
    mgr1 = EquipmentManager()
    mgr1.switch_user("admin")

    avail_dev = next(d for d in mgr1.devices if d.status == DeviceStatus.AVAILABLE)
    borrower = mgr1.borrowers[0]

    with tempfile.TemporaryDirectory() as tmpdir:
        rows = [
            {"device_id": "BAD_ID", "borrower_id": borrower.id, "borrow_time": "2026-06-01 10:00:00"},
            {"device_id": avail_dev.id, "borrower_id": borrower.id, "borrow_time": "2026-06-01 11:00:00"},
        ]
        path = os.path.join(tmpdir, "precheck_config.csv")
        _write_csv(path, rows)

        ok, _, summary = mgr1.precheck_import_file(path)
        assert_true(ok, "预检成功")
        assert_eq(mgr1.config.last_import_dir, tmpdir,
                  "内存中 last_import_dir 已记录")
        assert_eq(mgr1.config.last_import_format, "csv",
                  "内存中 last_import_format 已记录")
        assert_true(len(mgr1.config.last_import_summary) > 0,
                    "内存中 last_import_summary 非空")

        mgr2 = EquipmentManager()
        mgr2.switch_user("admin")
        assert_eq(mgr2.config.last_import_dir, tmpdir,
                  "跨重启：last_import_dir 保留")
        assert_eq(mgr2.config.last_import_format, "csv",
                  "跨重启：last_import_format 保留")
        assert_true(len(mgr2.config.last_import_summary) > 0,
                    "跨重启：last_import_summary 保留")
        info = mgr2.get_last_import_info()
        assert_eq(info["last_import_dir"], tmpdir, "get_last_import_info 返回目录")
        assert_eq(info["last_import_format"], "csv", "get_last_import_info 返回格式")
        assert_true("total" in info["last_import_summary"],
                    "摘要中包含 total 字段")


def test_import_log_generated():
    print("\n=== 测试24: 纯合法文件导入 - 日志生成与持久化 ===")
    setup_test_env()
    mgr1 = EquipmentManager()
    mgr1.switch_user("admin")

    avail_devs = [d for d in mgr1.devices if d.status == DeviceStatus.AVAILABLE]
    borrower = mgr1.borrowers[0]

    with tempfile.TemporaryDirectory() as tmpdir:
        rows_ok = [
            {
                "device_id": avail_devs[0].id,
                "borrower_id": borrower.id,
                "borrow_time": "2026-06-01 09:00:00",
                "status": RecordStatus.BORROWED,
                "remark": "日志测试1",
            },
            {
                "device_id": avail_devs[1].id,
                "borrower_id": borrower.id,
                "borrow_time": "2026-06-01 10:00:00",
                "status": RecordStatus.BORROWED,
                "remark": "日志测试2",
            },
        ]
        path_ok = os.path.join(tmpdir, "log_ok.csv")
        _write_csv(path_ok, rows_ok)
        ok, msg, sc, fc = mgr1.commit_import(path_ok)
        assert_true(ok, "纯合法文件导入成功：" + msg)
        assert_eq(sc, 2, "成功 2 条")
        assert_eq(fc, 0, "失败 0 条")

        logs = mgr1.get_import_logs()
        assert_true(len(logs) >= 1, "至少有 1 条导入日志")
        last = logs[-1]
        assert_eq(last.operator, "admin", "日志操作者 admin")
        assert_eq(last.operator_role, UserRole.ADMIN, "日志角色 管理员")
        assert_eq(last.file_format, "csv", "日志格式 csv")
        assert_eq(last.total, 2, "日志总数 2")
        assert_eq(last.success_count, 2, "日志成功数 2")
        assert_eq(last.fail_count, 0, "日志失败数 0")
        assert_eq(len(last.fail_reasons), 0, "失败原因列表为空")
        assert_true(last.timestamp, "时间戳非空")

        mgr2 = EquipmentManager()
        mgr2.switch_user("admin")
        logs2 = mgr2.get_import_logs()
        assert_true(len(logs2) >= 1, "跨重启：日志依然存在")
        assert_eq(logs2[-1].file_path, path_ok, "跨重启：日志文件路径一致")


def test_import_rejects_mixed_csv_no_side_effects():
    print("\n=== 测试25: CSV 混合（1有效+1设备不存在）整批拒绝，全链路无副作用 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    avail_dev = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
    borrower = mgr.borrowers[0]
    records_before = len(mgr.records)
    devices_snapshot = [(d.id, d.status) for d in mgr.devices]
    history_lens_before = {r.id: len(r.history) for r in mgr.records}
    avail_status_before = avail_dev.status
    logs_before = len(mgr.get_import_logs())

    with tempfile.TemporaryDirectory() as tmpdir:
        rows = [
            {
                "device_id": avail_dev.id,
                "borrower_id": borrower.id,
                "borrow_time": "2026-06-01 09:00:00",
                "status": RecordStatus.BORROWED,
                "remark": "本应写入",
            },
            {
                "device_id": "NO_SUCH",
                "borrower_id": borrower.id,
                "borrow_time": "2026-06-01 10:00:00",
            },
        ]
        path = os.path.join(tmpdir, "mixed.csv")
        _write_csv(path, rows)

        ok_pre, _, summary_pre = mgr.precheck_import_file(path)
        assert_true(ok_pre, "预检执行成功")
        assert_eq(summary_pre.total, 2, "预检总数 2")
        assert_eq(summary_pre.importable, 1, "预检可导入 1")
        assert_eq(summary_pre.device_not_found, 1, "预检设备不存在 1")

        ok, msg, sc, fc = mgr.commit_import(path)
        assert_true(not ok, "混合 CSV 返回失败")
        assert_true("整批" in msg, f"返回消息含'整批'关键词：{msg[:80]}")
        assert_true("预检发现问题" in msg, "返回消息含'预检发现问题'")
        assert_eq(sc, 0, "成功数 0")
        assert_eq(fc, 2, "失败数 2（整批都记为失败）")

        assert_eq(len(mgr.records), records_before,
                  "记录数保持不变")
        for (did, dstatus), d in zip(devices_snapshot, mgr.devices):
            assert_eq(d.status, dstatus,
                      f"设备 {did} 状态与导入前完全一致")
        d = mgr.find_device(avail_dev.id)
        assert_eq(d.status, avail_status_before,
                  "原本可借出的设备仍是可借出")
        for r in mgr.records:
            assert_eq(len(r.history), history_lens_before[r.id],
                      f"已有记录 {r.id} 的历史长度未变")

        logs = mgr.get_import_logs()
        assert_eq(len(logs), logs_before + 1, "多了 1 条日志")
        last = logs[-1]
        assert_eq(last.operator, "admin", "失败日志操作者为 admin")
        assert_eq(last.success_count, 0, "失败日志 success_count = 0")
        assert_eq(last.fail_count, 2, "失败日志 fail_count = 2")
        assert_eq(last.file_format, "csv", "失败日志格式 csv")
        assert_true(len(last.fail_reasons) >= 1, "失败原因至少 1 条")
        assert_true("预检发现问题" in last.fail_reasons[0]
                    or "整批" in last.fail_reasons[0],
                    "失败原因含预检/整批关键词")

        info = mgr.get_last_import_info()
        assert_eq(info["last_import_format"], "csv",
                  "预检摘要格式仍为 csv（预检信息保留）")
        assert_true(info["last_import_summary"],
                    "预检摘要被保存（跨重启可见）")
        assert_eq(info["last_import_summary"].get("device_not_found"), 1,
                  "摘要中 device_not_found = 1")

        mgr2 = EquipmentManager()
        mgr2.switch_user("admin")
        assert_eq(len(mgr2.records), records_before,
                  "跨重启：记录数仍保持原状")
        assert_eq(mgr2.find_device(avail_dev.id).status, avail_status_before,
                  "跨重启：设备状态仍保持原状")
        info2 = mgr2.get_last_import_info()
        assert_eq(info2["last_import_summary"].get("device_not_found"), 1,
                  "跨重启：预检摘要中的 device_not_found 仍为 1")
        logs2 = mgr2.get_import_logs()
        assert_eq(len(logs2), logs_before + 1,
                  "跨重启：失败日志仍然存在")


def test_import_rejects_mixed_json_no_side_effects():
    print("\n=== 测试26: JSON 混合（1有效+1借用人不存在）整批拒绝，全链路无副作用 ===")
    mgr = _fresh_manager()
    mgr.switch_user("wangwu")

    avail_dev = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
    borrower = mgr.borrowers[0]
    records_before = len(mgr.records)
    devices_snapshot = [(d.id, d.status) for d in mgr.devices]
    history_lens_before = {r.id: len(r.history) for r in mgr.records}
    avail_status_before = avail_dev.status
    logs_before = len(mgr.get_import_logs())

    with tempfile.TemporaryDirectory() as tmpdir:
        rows = [
            {
                "device_id": avail_dev.id,
                "borrower_id": borrower.id,
                "borrow_time": "2026-06-03 09:00:00",
                "status": RecordStatus.BORROWED,
                "remark": "本应写入",
            },
            {
                "device_id": avail_dev.id,
                "borrower_id": "NO_SUCH_BORROWER",
                "borrow_time": "2026-06-04 09:00:00",
            },
        ]
        path = os.path.join(tmpdir, "mixed.json")
        _write_json(path, rows)

        ok, msg, sc, fc = mgr.commit_import(path)
        assert_true(not ok, "混合 JSON 返回失败")
        assert_true("整批" in msg or "预检发现问题" in msg,
                    f"返回消息含预检/整批关键词：{msg[:80]}")
        assert_eq(sc, 0, "成功数 0")
        assert_eq(fc, 2, "失败数 2（整批）")

        assert_eq(len(mgr.records), records_before,
                  "记录数保持不变")
        for (did, dstatus), d in zip(devices_snapshot, mgr.devices):
            assert_eq(d.status, dstatus,
                      f"设备 {did} 状态与导入前完全一致")
        assert_eq(mgr.find_device(avail_dev.id).status, avail_status_before,
                  "原本可借出的设备仍是可借出")
        for r in mgr.records:
            assert_eq(len(r.history), history_lens_before[r.id],
                      f"已有记录 {r.id} 的历史长度未变")

        logs = mgr.get_import_logs()
        assert_eq(len(logs), logs_before + 1, "多了 1 条日志")
        last = logs[-1]
        assert_eq(last.operator, "wangwu", "失败日志操作者为验收人 wangwu")
        assert_eq(last.operator_role, UserRole.INSPECTOR,
                  "失败日志角色为 验收人")
        assert_eq(last.success_count, 0, "失败日志 success_count = 0")
        assert_eq(last.fail_count, 2, "失败日志 fail_count = 2")
        assert_eq(last.file_format, "json", "失败日志格式 json")

        info = mgr.get_last_import_info()
        assert_eq(info["last_import_format"], "json",
                  "预检摘要格式仍为 json")
        assert_eq(info["last_import_summary"].get("borrower_not_found"), 1,
                  "摘要中 borrower_not_found = 1")


def test_reminder_days_permission():
    print("\n=== 测试27: 提醒天数设置 - 角色权限 ===")
    mgr = _fresh_manager()

    mgr.switch_user("zhangsan")
    assert_true(not mgr.has_permission("set_reminder_days"), "借用人无 set_reminder_days 权限")
    def try_set_borrower():
        mgr.set_reminder_days(5)
    assert_raises(try_set_borrower, BusinessError, "借用人设置提醒天数抛出权限异常")

    mgr.switch_user("admin")
    assert_true(mgr.has_permission("set_reminder_days"), "管理员有 set_reminder_days 权限")
    ok, msg = mgr.set_reminder_days(7)
    assert_true(ok, f"管理员设置 7 天成功: {msg}")
    assert_eq(mgr.get_reminder_days(), 7, "内存中提醒天数为 7")

    mgr.switch_user("wangwu")
    assert_true(mgr.has_permission("set_reminder_days"), "验收人有 set_reminder_days 权限")
    ok, msg = mgr.set_reminder_days(10)
    assert_true(ok, f"验收人设置 10 天成功: {msg}")
    assert_eq(mgr.get_reminder_days(), 10, "内存中提醒天数为 10")


def test_reminder_days_validation():
    print("\n=== 测试28: 提醒天数设置 - 合法值校验 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")
    default_days = mgr.get_reminder_days()

    ok, msg = mgr.set_reminder_days(0)
    assert_true(not ok, "0 天设置失败")
    assert_true("大于 0" in msg, f"错误信息包含'大于 0'（实际: {msg}）")
    assert_eq(mgr.get_reminder_days(), default_days, "失败时天数保持默认值")

    ok, msg = mgr.set_reminder_days(-1)
    assert_true(not ok, "负数天数设置失败")
    assert_eq(mgr.get_reminder_days(), default_days, "失败时天数保持默认值")

    ok, msg = mgr.set_reminder_days(400)
    assert_true(not ok, "超过 365 天设置失败")
    assert_true("不能超过 365" in msg, f"错误信息包含上限提示（实际: {msg}）")
    assert_eq(mgr.get_reminder_days(), default_days, "失败时天数保持默认值")

    ok, msg = mgr.set_reminder_days("abc")
    assert_true(not ok, "非数字天数设置失败")
    assert_eq(mgr.get_reminder_days(), default_days, "失败时天数保持默认值")

    ok, msg = mgr.set_reminder_days(1)
    assert_true(ok, "1 天设置成功")
    assert_eq(mgr.get_reminder_days(), 1, "提醒天数为 1")

    ok, msg = mgr.set_reminder_days(365)
    assert_true(ok, "365 天设置成功")
    assert_eq(mgr.get_reminder_days(), 365, "提醒天数为 365")


def test_reminder_days_persistence_across_restart():
    print("\n=== 测试29: 提醒天数 - 跨重启持久化 ===")
    setup_test_env()
    mgr1 = EquipmentManager()
    mgr1.switch_user("admin")
    assert_eq(mgr1.get_reminder_days(), 3, "默认提醒天数为 3")

    ok, _ = mgr1.set_reminder_days(14)
    assert_true(ok, "设置 14 天成功")
    assert_eq(mgr1.config.reminder_days, 14, "内存 config 已更新")

    mgr2 = EquipmentManager()
    assert_eq(mgr2.config.reminder_days, 14, "跨重启: config.reminder_days 仍是 14")
    assert_eq(mgr2.get_reminder_days(), 14, "跨重启: get_reminder_days() 返回 14")

    mgr2.switch_user("admin")
    ok, _ = mgr2.set_reminder_days(5)
    assert_true(ok, "第二次修改为 5 天成功")

    mgr3 = EquipmentManager()
    assert_eq(mgr3.get_reminder_days(), 5, "跨重启: 再次修改后的值仍被保留")


def test_overdue_and_due_soon_boundary():
    print("\n=== 测试30: 临期/逾期 - 边界判断 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")
    mgr.set_reminder_days(3)

    now = datetime.now()

    def _mk_record(expected_return_str, status=RecordStatus.BORROWED):
        borrower = mgr.borrowers[0]
        dev = mgr.devices[0]
        return BorrowRecord(
            device_id=dev.id, device_name=dev.name,
            borrower_id=borrower.id, borrower_name=borrower.name,
            expected_return_time=expected_return_str,
            status=status,
        )

    r_returned = _mk_record((now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"),
                            status=RecordStatus.RETURNED)
    assert_true(not mgr.is_overdue(r_returned), "已归还记录不算逾期")
    assert_true(not mgr.is_due_soon(r_returned), "已归还记录不算临期")

    r_no_exp = _mk_record("")
    assert_true(not mgr.is_overdue(r_no_exp), "无预计归还时间不算逾期")
    assert_true(not mgr.is_due_soon(r_no_exp), "无预计归还时间不算临期")

    r_overdue_1d = _mk_record((now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"))
    assert_true(mgr.is_overdue(r_overdue_1d), "超过 1 天 -> 逾期")
    assert_true(not mgr.is_due_soon(r_overdue_1d), "逾期不算临期")
    assert_eq(mgr.get_record_alert_status(r_overdue_1d), "overdue",
              "状态应为 overdue")

    r_due_1min = _mk_record((now + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"))
    assert_true(not mgr.is_overdue(r_due_1min), "1 分钟后不算逾期")
    assert_true(mgr.is_due_soon(r_due_1min), "1 分钟后（<=3天）算临期")
    assert_eq(mgr.get_record_alert_status(r_due_1min), "due_soon",
              "状态应为 due_soon")

    r_due_2d = _mk_record((now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"))
    assert_true(not mgr.is_overdue(r_due_2d), "2 天后不算逾期")
    assert_true(mgr.is_due_soon(r_due_2d), "2 天后（<=3天）算临期")

    r_due_3d = _mk_record((now + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"))
    assert_true(mgr.is_due_soon(r_due_3d), "3 天后（刚好阈值）算临期")

    r_due_4d = _mk_record((now + timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S"))
    assert_true(not mgr.is_overdue(r_due_4d), "4 天后不算逾期")
    assert_true(not mgr.is_due_soon(r_due_4d), "4 天后（>3天）不算临期")
    assert_eq(mgr.get_record_alert_status(r_due_4d), "normal",
              "状态应为 normal")

    r_due_2d_custom = _mk_record((now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"))
    assert_true(mgr.is_due_soon(r_due_2d_custom, days=3),
                "指定 days=3: 2 天后算临期")
    assert_true(not mgr.is_due_soon(r_due_2d_custom, days=1),
                "指定 days=1: 2 天后不算临期")
    r_due_05d = _mk_record((now + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S"))
    assert_true(mgr.is_due_soon(r_due_05d, days=1), "指定 days=1: 0.5 天后算临期")


def test_filter_records_by_alert():
    print("\n=== 测试31: 筛选功能 - 按临期/逾期/已归还/全部过滤 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")
    mgr.set_reminder_days(3)

    now = datetime.now()
    borrower = mgr.borrowers[0]
    dev = mgr.devices[0]

    test_records = {
        "overdue": BorrowRecord(
            id="ov01", device_id=dev.id, device_name=dev.name,
            borrower_id=borrower.id, borrower_name=borrower.name,
            expected_return_time=(now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),
            status=RecordStatus.BORROWED,
        ),
        "due_soon": BorrowRecord(
            id="ds01", device_id=dev.id, device_name=dev.name,
            borrower_id=borrower.id, borrower_name=borrower.name,
            expected_return_time=(now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
            status=RecordStatus.BORROWED,
        ),
        "returned": BorrowRecord(
            id="rt01", device_id=dev.id, device_name=dev.name,
            borrower_id=borrower.id, borrower_name=borrower.name,
            expected_return_time=(now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"),
            status=RecordStatus.RETURNED,
        ),
        "normal": BorrowRecord(
            id="nr01", device_id=dev.id, device_name=dev.name,
            borrower_id=borrower.id, borrower_name=borrower.name,
            expected_return_time=(now + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
            status=RecordStatus.BORROWED,
        ),
    }

    all_list = list(test_records.values())

    all_filtered = mgr.filter_records_by_alert(all_list, "all")
    assert_eq(len(all_filtered), 4, "all 筛选返回全部 4 条")

    overdue_filtered = mgr.filter_records_by_alert(all_list, "overdue")
    assert_eq(len(overdue_filtered), 1, "overdue 筛选返回 1 条")
    assert_eq(overdue_filtered[0].id, "ov01", "逾期记录 ID 正确")

    due_soon_filtered = mgr.filter_records_by_alert(all_list, "due_soon")
    assert_eq(len(due_soon_filtered), 1, "due_soon 筛选返回 1 条")
    assert_eq(due_soon_filtered[0].id, "ds01", "临期记录 ID 正确")

    returned_filtered = mgr.filter_records_by_alert(all_list, "returned")
    assert_eq(len(returned_filtered), 1, "returned 筛选返回 1 条")
    assert_eq(returned_filtered[0].id, "rt01", "已归还记录 ID 正确")

    empty_filtered = mgr.filter_records_by_alert([], "all")
    assert_eq(len(empty_filtered), 0, "空列表筛选返回空")
    empty_overdue = mgr.filter_records_by_alert([test_records["normal"]], "overdue")
    assert_eq(len(empty_overdue), 0, "无逾期记录时 overdue 筛选返回空")


def test_borrower_view_filter_with_alert():
    print("\n=== 测试32: 借用人视角筛选 - 只能看到自己的记录 ===")
    mgr = _fresh_manager()

    mgr.switch_user("admin")
    mgr.set_reminder_days(3)
    now = datetime.now()
    zhangsan = next(b for b in mgr.borrowers if b.name == "张三")
    lisi = next(b for b in mgr.borrowers if b.name == "李四")

    existing_for_zhangsan = [r for r in mgr.records
                             if r.borrower_id == zhangsan.id or r.borrower_name == zhangsan.name]
    for r in existing_for_zhangsan:
        if r.status in (RecordStatus.BORROWED, RecordStatus.INSPECTING):
            try:
                mgr.submit_return(r.id, accessories=r.accessories_check_out, remark="测试先归还")
                mgr.inspect_return(r.id, accessories=r.accessories_check_out,
                                   inspect_remark="测试先验收")
            except Exception:
                pass

    avail_dev = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
    r_zhangsan_overdue = mgr.borrow_device(
        device_id=avail_dev.id,
        borrower_id=zhangsan.id,
        expected_return_time=(now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
        remark="张三逾期测试",
    )

    avail_dev2 = next(d for d in mgr.devices
                      if d.status == DeviceStatus.AVAILABLE and d.id != avail_dev.id)
    r_lisi_normal = mgr.borrow_device(
        device_id=avail_dev2.id,
        borrower_id=lisi.id,
        expected_return_time=(now + timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"),
        remark="李四正常测试",
    )

    mgr.switch_user("zhangsan")
    all_for_zhangsan = mgr.get_filtered_records()
    for r in all_for_zhangsan:
        assert_true(r.borrower_name == "张三" or r.borrower_id == "zhangsan",
                    f"借用人视角只看到自己的记录: {r.borrower_name}")
    overdue_for_zhangsan = mgr.filter_records_by_alert(all_for_zhangsan, "overdue")
    assert_true(any(r.id == r_zhangsan_overdue.id for r in overdue_for_zhangsan),
                "张三视角能看到自己的那条逾期测试记录")

    mgr.switch_user("lisi")
    all_for_lisi = mgr.get_filtered_records()
    for r in all_for_lisi:
        assert_true(r.borrower_name == "李四" or r.borrower_id == "lisi",
                    f"李四视角只看到自己的记录: {r.borrower_name}")
    overdue_for_lisi = mgr.filter_records_by_alert(all_for_lisi, "overdue")
    assert_eq(len(overdue_for_lisi), 0, "李四视角无逾期记录")

    mgr.switch_user("admin")
    all_for_admin = mgr.get_filtered_records()
    assert_true(any(r.id == r_zhangsan_overdue.id for r in all_for_admin),
                "管理员能看到张三的逾期记录")
    assert_true(any(r.id == r_lisi_normal.id for r in all_for_admin),
                "管理员能看到李四的正常记录")


def test_export_with_filter_info():
    print("\n=== 测试33: 导出选中记录 - 包含筛选条件 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr.set_export_dir(tmpdir)

        r = mgr.records[0]
        filter_info = {
            "description": "逾期",
            "筛选类型": "逾期",
            "提醒天数": "3 天",
            "可见记录数": 1,
            "本次选中导出数": 1,
        }

        csv_path = os.path.join(tmpdir, "records_overdue.csv")
        ok, msg = mgr.export_selected_records([r.id], csv_path, filter_info)
        assert_true(ok, f"CSV 导出（含筛选条件）成功: {msg}")
        assert_true(os.path.exists(csv_path) and os.path.getsize(csv_path) > 0,
                    "CSV 文件存在且非空")
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            lines = list(reader)
        has_filter_meta = any("# 导出筛选条件" in str(cell) for row in lines for cell in row)
        assert_true(has_filter_meta, "CSV 包含筛选条件元数据（# 开头行）")
        has_alert_col = any("提醒状态" in str(cell) for row in lines for cell in row)
        assert_true(has_alert_col, "CSV 包含'提醒状态'列")

        json_path = os.path.join(tmpdir, "records_overdue.json")
        ok, msg = mgr.export_selected_records([r.id], json_path, filter_info)
        assert_true(ok, f"JSON 导出（含筛选条件）成功: {msg}")
        assert_true(os.path.exists(json_path) and os.path.getsize(json_path) > 0,
                    "JSON 文件存在且非空")
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert_true("filter_info" in data, "JSON 顶层包含 filter_info 字段")
        assert_eq(data["filter_info"]["筛选类型"], "逾期",
                  "JSON filter_info 中记录了筛选类型")
        assert_eq(data["filter_info"]["提醒天数"], "3 天",
                  "JSON filter_info 中记录了提醒天数")
        assert_true("records" in data, "JSON 顶层包含 records 数组")
        assert_true(len(data["records"]) >= 1, "JSON records 数组非空")
        assert_true("export_time" in data, "JSON 顶层包含 export_time")


def test_export_filter_info_empty_scenario():
    print("\n=== 测试34: 空结果场景 - 无选中/无记录时提示 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    assert_eq(mgr.config.reminder_days, 3, "默认 reminder_days 为 3")

    setup_test_env()
    mgr_empty = EquipmentManager()
    mgr_empty.switch_user("admin")
    mgr_empty.records = []
    mgr_empty.save_all()

    mgr_empty2 = EquipmentManager()
    mgr_empty2.switch_user("admin")
    base = mgr_empty2.get_filtered_records()
    filtered = mgr_empty2.filter_records_by_alert(base, "overdue")
    assert_eq(len(filtered), 0, "空记录库 overdue 筛选返回 0 条")
    filtered_all = mgr_empty2.filter_records_by_alert(base, "all")
    assert_eq(len(filtered_all), 0, "空记录库 all 筛选返回 0 条")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr_empty2.set_export_dir(tmpdir)
        csv_path = os.path.join(tmpdir, "empty.csv")
        ok, msg = mgr_empty2.export_selected_records([], csv_path,
                                                     {"筛选类型": "逾期", "提醒天数": "3 天"})
        assert_true(ok, "空记录导出仍成功（只要路径可写）")
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            lines = list(reader)
        has_header = any("记录ID" in str(cell) for row in lines for cell in row)
        assert_true(has_header, "空结果 CSV 仍包含表头")


def test_maintenance_permission_roles():
    print("\n=== 测试35: 维修/保养 - 角色权限 ===")
    mgr = _fresh_manager()

    mgr.switch_user("zhangsan")
    assert_true(not mgr.has_permission("send_to_maintenance"),
                "借用人无 send_to_maintenance 权限")
    assert_true(not mgr.has_permission("cancel_maintenance"),
                "借用人无 cancel_maintenance 权限")
    assert_true(not mgr.has_permission("view_maintenance"),
                "借用人无 view_maintenance 权限")
    assert_true(not mgr.has_permission("export_maintenance"),
                "借用人无 export_maintenance 权限")
    avail = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
    assert_raises(lambda: mgr.send_to_maintenance(avail.id, "测试", ""),
                  BusinessError, "借用人调用 send_to_maintenance 抛出权限异常")

    mgr.switch_user("wangwu")
    assert_true(not mgr.has_permission("send_to_maintenance"),
                "验收人无 send_to_maintenance 权限")
    assert_true(not mgr.has_permission("cancel_maintenance"),
                "验收人无 cancel_maintenance 权限")
    assert_true(mgr.has_permission("view_maintenance"),
                "验收人有 view_maintenance 权限")
    assert_true(mgr.has_permission("export_maintenance"),
                "验收人有 export_maintenance 权限")

    mgr.switch_user("admin")
    assert_true(mgr.has_permission("send_to_maintenance"),
                "管理员有 send_to_maintenance 权限")
    assert_true(mgr.has_permission("cancel_maintenance"),
                "管理员有 cancel_maintenance 权限")
    assert_true(mgr.has_permission("view_maintenance"),
                "管理员有 view_maintenance 权限")
    assert_true(mgr.has_permission("export_maintenance"),
                "管理员有 export_maintenance 权限")


def test_maintenance_basic_flow_and_conflict():
    print("\n=== 测试36: 维修/保养 - 基本流程与冲突 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")

    avail = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
    frozen = next(d for d in mgr.devices if d.status == DeviceStatus.FROZEN)
    borrowed = next(d for d in mgr.devices if d.status == DeviceStatus.BORROWED)

    rec, msg = mgr.send_to_maintenance(avail.id, "定期保养", "")
    assert_eq(avail.status, DeviceStatus.MAINTENANCE, "可借出设备送修后状态为维修中")
    assert_eq(rec.status, "in_progress", "维修记录状态为进行中")
    assert_true("定期保养" in msg, "返回消息包含原因")
    assert_true(any(m.id == rec.id for m in mgr.maintenance_logs),
                "维修记录已加入内存列表")
    logs = storage.load_maintenance_logs()
    assert_true(any(m.id == rec.id for m in logs), "维修记录已持久化")

    assert_raises(lambda: mgr.send_to_maintenance(avail.id, "再修一次", ""),
                  BusinessError, "维修中设备不能再次送修")

    assert_raises(lambda: mgr.send_to_maintenance(borrowed.id, "想修一下", ""),
                  BusinessError, "已借出设备不能送修（有进行中记录）")

    rec2, _ = mgr.send_to_maintenance(frozen.id, "异常后检修", "")
    assert_eq(frozen.status, DeviceStatus.MAINTENANCE, "异常冻结设备可送修")

    zhangsan = next(b for b in mgr.borrowers if b.name == "张三")
    assert_raises(lambda: mgr.borrow_device(avail.id, zhangsan.id, "", [], ""),
                  BusinessError, "维修中设备不能借出")

    assert_raises(lambda: mgr.delete_device(avail.id),
                  BusinessError, "维修中设备不能删除")

    assert_raises(lambda: mgr.send_to_maintenance(avail.id, "", ""),
                  BusinessError, "送修原因不能为空")


def test_maintenance_cancel_boundary():
    print("\n=== 测试37: 维修/保养 - 撤销边界 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")
    avail = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)

    can, _ = mgr.can_cancel_maintenance(avail.id)
    assert_true(not can, "非维修中设备 cannot cancel")

    mgr.send_to_maintenance(avail.id, "测试保养", "")
    assert_eq(avail.status, DeviceStatus.MAINTENANCE, "送修成功")
    can, _ = mgr.can_cancel_maintenance(avail.id)
    assert_true(can, "刚送修完且无变化，可撤销")

    mgr.cancel_last_maintenance(avail.id, "不需要修了")
    assert_eq(avail.status, DeviceStatus.AVAILABLE, "撤销后恢复原状态（可借出）")
    active = mgr.get_active_maintenance_for_device(avail.id)
    assert_true(active is None or active.status == "cancelled",
                "撤销后活跃维修记录状态为已撤销或不存在")

    avail2 = next(d for d in mgr.devices
                  if d.status == DeviceStatus.AVAILABLE and d.id != avail.id)
    mgr.send_to_maintenance(avail2.id, "保养", "")
    zhangsan = next(b for b in mgr.borrowers if b.name == "张三")
    other_avail = next(d for d in mgr.devices
                       if d.status == DeviceStatus.AVAILABLE and d.id != avail2.id)
    mgr.borrow_device(other_avail.id, zhangsan.id,
                      (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
                      [], "测试产生新借用")
    can2, reason2 = mgr.can_cancel_maintenance(avail2.id)
    assert_true(not can2, "有新借用后不能撤销")
    assert_true("变化" in reason2, "提示原因包含'变化'")

    mgr.switch_user("wangwu")
    assert_raises(lambda: mgr.cancel_last_maintenance(avail2.id, ""),
                  BusinessError, "验收人调用撤销抛出权限异常")


def test_maintenance_config_persistence_and_filter():
    print("\n=== 测试38: 维修/保养 - 配置持久化与记录筛选 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")
    assert_eq(mgr.get_default_maintenance_days(), 7, "默认维修天数为 7")

    ok, msg = mgr.set_default_maintenance_days(14)
    assert_true(ok, "设置 14 天成功")
    assert_eq(mgr.get_default_maintenance_days(), 14, "内存中为 14")

    mgr2 = EquipmentManager()
    mgr2.switch_user("admin")
    assert_eq(mgr2.get_default_maintenance_days(), 14, "跨重启后默认维修天数仍为 14")

    avail = next(d for d in mgr2.devices if d.status == DeviceStatus.AVAILABLE)
    avail2 = next(d for d in mgr2.devices
                  if d.status == DeviceStatus.AVAILABLE and d.id != avail.id)
    mgr2.send_to_maintenance(avail.id, "设备A送修", "")
    rec, _ = mgr2.send_to_maintenance(avail2.id, "设备B送修", "")
    mgr2.cancel_last_maintenance(avail2.id, "取消")

    all_logs = mgr2.get_maintenance_logs()
    assert_true(len(all_logs) >= 2, "至少 2 条维修记录")

    by_device = mgr2.filter_maintenance_logs(all_logs, device_id=avail.id)
    assert_eq(len(by_device), 1, "按设备筛选仅返回该设备记录")

    in_prog = mgr2.filter_maintenance_logs(all_logs, status_filter="in_progress")
    assert_true(all(m.status == "in_progress" for m in in_prog),
                "in_progress 筛选只返回进行中的")

    cancelled = mgr2.filter_maintenance_logs(all_logs, status_filter="cancelled")
    assert_eq(len(cancelled), 1, "cancelled 筛选返回 1 条")
    assert_eq(cancelled[0].id, rec.id, "是那条撤销的")

    empty = mgr2.filter_maintenance_logs([], status_filter="in_progress")
    assert_eq(len(empty), 0, "空列表筛选返回 0 条")

    flt = {"device_id": avail.id, "status_filter": "in_progress",
           "start_from": "", "start_to": ""}
    mgr2.save_maintenance_filter(flt)
    mgr3 = EquipmentManager()
    saved = mgr3.get_last_maintenance_filter()
    assert_eq(saved.get("device_id"), avail.id, "跨重启保留设备筛选条件")
    assert_eq(saved.get("status_filter"), "in_progress", "跨重启保留状态筛选条件")


def test_maintenance_import_intercept():
    print("\n=== 测试39: 维修/保养 - 批量导入拦截维修中设备 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")
    tmpdir = tempfile.mkdtemp()
    try:
        avail = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
        zhangsan = next(b for b in mgr.borrowers if b.name == "张三")
        mgr.send_to_maintenance(avail.id, "测试导入拦截", "")
        assert_eq(avail.status, DeviceStatus.MAINTENANCE, "设备已送修")

        csv_path = os.path.join(tmpdir, "maint_bad.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["device_id", "borrower_id", "borrow_time", "status"])
            writer.writerow([avail.id, zhangsan.id,
                             (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                             RecordStatus.BORROWED])
        ok, msg, summary = mgr.precheck_import_file(csv_path)
        assert_true(ok, "预检执行成功")
        assert_true(summary.device_status_conflict >= 1,
                    f"预检识别维修中状态冲突（实际 {summary.device_status_conflict}）")
        assert_true(summary.importable == 0, "无可导入记录")

        commit_ok, commit_msg, sc, fc = mgr.commit_import(csv_path)
        assert_true(not commit_ok, "提交导入返回失败")
        assert_true("整批" in commit_msg, "失败消息包含整批关键词")
        assert_eq(sc, 0, "成功导入 0 条")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_maintenance_export_with_filter_info():
    print("\n=== 测试40: 维修/保养 - 按筛选导出并写入筛选条件 ===")
    mgr = _fresh_manager()
    mgr.switch_user("admin")
    tmpdir = tempfile.mkdtemp()
    try:
        avail = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
        avail2 = next(d for d in mgr.devices
                      if d.status == DeviceStatus.AVAILABLE and d.id != avail.id)
        mgr.send_to_maintenance(avail.id, "送修A", "")
        mgr.send_to_maintenance(avail2.id, "送修B", "")
        mgr.cancel_last_maintenance(avail2.id, "不需要了")
        ok, _ = mgr.set_export_dir(tmpdir)
        assert_true(ok, "导出目录设置成功")

        all_logs = mgr.get_maintenance_logs()
        in_prog = mgr.filter_maintenance_logs(all_logs, status_filter="in_progress")
        ids = [m.id for m in in_prog]
        assert_true(len(ids) >= 1, "至少有 1 条进行中记录")
        filter_info = {"筛选类型": "进行中", "默认维修天数": "7 天",
                       "description": "维修记录（进行中）"}

        csv_path = os.path.join(tmpdir, "maint_inprog.csv")
        ok, msg = mgr.export_maintenance_logs(ids, csv_path, filter_info)
        assert_true(ok, f"CSV 导出成功: {msg}")
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            lines = list(reader)
        has_sharp = any(len(row) > 0 and str(row[0]).startswith("#") for row in lines)
        assert_true(has_sharp, "CSV 包含 # 开头的筛选条件注释行")
        has_maint_col = any("维修记录ID" in str(cell) for row in lines for cell in row)
        assert_true(has_maint_col, "CSV 包含维修记录表头")

        json_path = os.path.join(tmpdir, "maint_inprog.json")
        ok, msg = mgr.export_maintenance_logs(ids, json_path, filter_info)
        assert_true(ok, f"JSON 导出成功: {msg}")
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert_true("filter_info" in data, "JSON 顶层含 filter_info")
        assert_true("records" in data, "JSON 顶层含 records")
        assert_true("export_time" in data, "JSON 顶层含 export_time")
        assert_eq(data["filter_info"].get("筛选类型"), "进行中",
                  "JSON filter_info 包含筛选类型")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_maintenance_log_persistence_across_restart():
    print("\n=== 测试41: 维修/保养 - 日志跨重启持久化 ===")
    setup_test_env()
    mgr = EquipmentManager()
    mgr.switch_user("admin")
    avail = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
    rec, _ = mgr.send_to_maintenance(avail.id, "保养1", "")

    mgr2 = EquipmentManager()
    mgr2.switch_user("admin")
    persisted = [m for m in mgr2.maintenance_logs if m.id == rec.id]
    assert_eq(len(persisted), 1, "跨重启后维修日志仍在内存列表中（按ID精确匹配）")
    assert_eq(persisted[0].reason, "保养1", "日志原因正确")
    assert_eq(persisted[0].status, "in_progress", "日志状态为进行中")
    disk_logs = storage.load_maintenance_logs()
    assert_true(any(m.id == rec.id for m in disk_logs),
                "磁盘文件中也存在该日志")

    dev = mgr2.find_device(avail.id)
    assert_eq(dev.status, DeviceStatus.MAINTENANCE, "设备状态也正确持久化为维修中")


def test_maintenance_cancel_boundary_after_restart():
    print("\n=== 测试42: 维修/保养 - 送修后新增借用→重启→撤销失败（快照持久化边界） ===")
    setup_test_env()
    mgr = EquipmentManager()
    mgr.switch_user("admin")
    avail = next(d for d in mgr.devices if d.status == DeviceStatus.AVAILABLE)
    rec, _ = mgr.send_to_maintenance(avail.id, "正常保养", "")
    can_before, _ = mgr.can_cancel_maintenance(avail.id)
    assert_true(can_before, "刚送修后无借用变化时可以撤销")

    another_dev = next(d for d in mgr.devices
                    if d.id != avail.id and d.status == DeviceStatus.AVAILABLE)
    br = next(b for b in mgr.borrowers)
    mgr.borrow_device(another_dev.id, br.id,
                      (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                      [], "测试产生新借用")

    mgr2 = EquipmentManager()
    mgr2.switch_user("admin")
    can_after, reason_after = mgr2.can_cancel_maintenance(avail.id)
    assert_true(not can_after, "重启后仍能检测到新增借用→撤销被拦截")
    assert_true("变化" in reason_after, "错误消息含变化提示")
    try:
        mgr2.cancel_last_maintenance(avail.id, "测试撤销")
        assert_true(False, "应当抛出 BusinessError")
    except BusinessError:
        assert_true(True, "重启后依然阻止撤销")

    dev_after = mgr2.find_device(avail.id)
    assert_eq(dev_after.status, DeviceStatus.MAINTENANCE,
               "设备状态仍保持维修中，未被错误恢复")
    persisted_maint = [m for m in mgr2.maintenance_logs if m.id == rec.id]
    assert_eq(len(persisted_maint), 1, "维修记录仍为进行中，未被标记已撤销")
    assert_eq(persisted_maint[0].status, "in_progress", "记录状态为进行中")
    disk_config = storage.load_config()
    assert_true(len(disk_config.maintenance_records_snapshot) > 0,
                  "config 中保存了快照，重启后依然生效")


def test_maintenance_frozen_device_remark_history():
    print("\n=== 测试43: 维修/保养 - 异常冻结送修后 remark 含「异常冻结→维修中状态历史 ===")
    setup_test_env()
    mgr = EquipmentManager()
    mgr.switch_user("admin")
    frozen_dev = next(d for d in mgr.devices if d.status == DeviceStatus.FROZEN)
    if not frozen_dev:
        frozen_dev = Device(name="冻结设备", category="测试", status=DeviceStatus.FROZEN)
        mgr.devices.append(frozen_dev)
        mgr.save_all()
    _ = mgr.send_to_maintenance(frozen_dev.id, "冻住了需要修", "")
    dev = mgr.find_device(frozen_dev.id)
    assert_eq(dev.status, DeviceStatus.MAINTENANCE)
    assert_true("异常冻结" in dev.remark and "维修中" in dev.remark,
                 "设备 remark 中明确包含「异常冻结 → 维修中」状态变更记录")
    assert_true("送修/保养" in dev.remark and "冻住了需要修" in dev.remark,
                 "设备 remark 包含送修原因")
    active_m = mgr.get_active_maintenance_for_device(frozen_dev.id)
    assert_eq(active_m.from_status, DeviceStatus.FROZEN,
              "维修记录 from_status 为异常冻结")
    _, _ = mgr.cancel_last_maintenance(frozen_dev.id, "无需维修")
    dev2 = mgr.find_device(frozen_dev.id)
    assert_eq(dev2.status, DeviceStatus.FROZEN, "撤销后恢复为异常冻结，而非默认可借出")
    assert_true("维修中" in dev2.remark and "异常冻结" in dev2.remark,
                 "撤销 remark 也包含「维修中 → 异常冻结」状态变更")
    mgr2 = EquipmentManager()
    dev3 = mgr2.find_device(frozen_dev.id)
    assert_true("异常冻结" in dev3.remark and "维修中" in dev3.remark,
                 "重启后 remark 历史持久化保留")


def main():
    setup_test_env()
    try:
        test_basic_data_and_permissions()
        test_borrow_flow_success()
        test_borrow_fail_duplicate()
        test_borrow_fail_frozen()
        test_return_and_inspect_freeze()
        test_borrower_cannot_close_frozen()
        test_inspector_can_close_frozen()
        test_persistence()
        test_export_dir_writable()
        test_export_csv_json()
        test_borrower_view_filter()
        test_force_accept_inspection()
        test_missing_subdir_not_created_and_config_not_polluted()
        test_invalidated_dir_export_fails_no_file_and_data_intact()
        test_unwritable_dir_not_saved()
        test_valid_dir_still_works_after_failed_attempts()
        test_last_valid_dir_preserved_across_restart()
        test_import_permission_denied_for_borrower()
        test_import_admin_and_inspector_allowed()
        test_import_precheck_detects_all_issues()
        test_import_csv_and_json_success()
        test_import_rollback_on_conflict()
        test_import_config_persisted_across_restart()
        test_import_log_generated()
        test_import_rejects_mixed_csv_no_side_effects()
        test_import_rejects_mixed_json_no_side_effects()
        test_reminder_days_permission()
        test_reminder_days_validation()
        test_reminder_days_persistence_across_restart()
        test_overdue_and_due_soon_boundary()
        test_filter_records_by_alert()
        test_borrower_view_filter_with_alert()
        test_export_with_filter_info()
        test_export_filter_info_empty_scenario()
        test_maintenance_permission_roles()
        test_maintenance_basic_flow_and_conflict()
        test_maintenance_cancel_boundary()
        test_maintenance_config_persistence_and_filter()
        test_maintenance_import_intercept()
        test_maintenance_export_with_filter_info()
        test_maintenance_log_persistence_across_restart()
        test_maintenance_cancel_boundary_after_restart()
        test_maintenance_frozen_device_remark_history()
    finally:
        cleanup_test_env()

    print("\n" + "=" * 60)
    print(f"测试结果: 通过 {passed} 项, 失败 {failed} 项")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
