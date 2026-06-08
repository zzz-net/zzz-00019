import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (
    Device, Borrower, BorrowRecord, Accessory, User,
    DeviceStatus, RecordStatus, UserRole
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
    finally:
        cleanup_test_env()

    print("\n" + "=" * 60)
    print(f"测试结果: 通过 {passed} 项, 失败 {failed} 项")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
