import csv
import os
import re

import serial.tools.list_ports


APP_VERSION = "V1.2.0"


def _clean_csv_text(text):
    return str(text).replace("\ufeff", "").replace("\r", "").replace("\n", "").strip()


def _parse_hex_token(token):
    t = _clean_csv_text(token)
    if not t:
        return None
    while t and t[-1] in {"u", "U", "l", "L"}:
        t = t[:-1]
    return int(t, 16)


def _parse_base_addresses(base_text):
    raw = _clean_csv_text(base_text)
    if not raw:
        return []

    addrs = []
    parts = [_clean_csv_text(p) for p in raw.split("/") if _clean_csv_text(p)]
    if not parts:
        return []

    first = parts[0]
    for part in parts:
        p = _clean_csv_text(part)
        if not p:
            continue

        if len(p) < len(first):
            p = first[: len(first) - len(p)] + p

        value = int(p, 16)
        if len(p) <= 5:
            value <<= 12
        addrs.append(value)
    return addrs


def _get_isp_csv_candidates():
    return [os.path.join(os.path.dirname(__file__), "ISP.csv")]


def _find_isp_csv_path():
    candidates = _get_isp_csv_candidates()
    return next((p for p in candidates if os.path.exists(p)), None)


def _read_csv_rows_with_fallback(csv_path, encodings=None):
    if encodings is None:
        encodings = ["utf-8-sig", "gb18030", "gbk", "utf-8"]

    last_exc = None
    for enc in encodings:
        try:
            with open(csv_path, "r", newline="", encoding=enc) as f:
                return list(csv.reader(f)), enc
        except UnicodeDecodeError as exc:
            last_exc = exc
            continue
        except Exception as exc:
            last_exc = exc
            break

    if last_exc is None:
        raise ValueError("未知错误：CSV 读取失败")
    raise last_exc


def _parse_bits_range(bits_text):
    text = _clean_csv_text(bits_text).replace(" ", "")
    if not text:
        return None, None
    if ":" in text:
        left, right = text.split(":", 1)
        try:
            msb = int(left, 10)
            lsb = int(right, 10)
            if msb < lsb:
                msb, lsb = lsb, msb
            return msb, lsb
        except Exception:
            return None, None

    try:
        bit = int(text, 10)
        return bit, bit
    except Exception:
        return None, None


def _parse_enum_options_from_desc(desc_text, width):
    if not desc_text:
        return []

    max_value = (1 << width) - 1 if width > 0 else 0
    options = []
    seen = set()

    for m in re.finditer(r"(?m)^\s*(\d{1,3})\s*[:：]\s*([^\r\n]+)", desc_text):
        raw_val = int(m.group(1), 10)
        if raw_val < 0 or raw_val > max_value:
            continue
        label = _clean_csv_text(m.group(2))
        if not label:
            label = str(raw_val)
        key = (raw_val, label)
        if key in seen:
            continue
        seen.add(key)
        options.append((raw_val, label))

    return options


def _load_isp_function_fields_from_csv():
    csv_path = _find_isp_csv_path()
    if not csv_path:
        return {}, [], "未找到 ISP.csv，功能配置页不可用"

    module_fields = {}
    flat_fields = []

    cur_module = ""
    cur_bases = []
    cur_offset = None
    cur_offset_name = ""
    cur_reg_name = ""

    try:
        rows, used_encoding = _read_csv_rows_with_fallback(csv_path)
        for row in rows:
            if not row:
                continue

            cells = list(row) + [""] * (11 - len(row))
            (
                module_raw,
                base_raw,
                offset_raw,
                offset_name_raw,
                reg_name_raw,
                bits_raw,
                field_raw,
                access_raw,
                _active_raw,
                desc_raw,
                _default_raw,
            ) = cells[:11]

            module_text = _clean_csv_text(module_raw)
            base_text = _clean_csv_text(base_raw)
            offset_text = _clean_csv_text(offset_raw)
            offset_name = _clean_csv_text(offset_name_raw)
            reg_name = _clean_csv_text(reg_name_raw)
            bits_text = _clean_csv_text(bits_raw)
            field_name = _clean_csv_text(field_raw)
            access = _clean_csv_text(access_raw).upper() or "RW"
            desc = _clean_csv_text(desc_raw)

            if module_text.lower() == "module":
                continue

            if module_text:
                cur_module = module_text
            if base_text:
                parsed_bases = _parse_base_addresses(base_text)
                if parsed_bases:
                    cur_bases = parsed_bases

            if offset_text:
                try:
                    cur_offset = _parse_hex_token(offset_text)
                except Exception:
                    cur_offset = None
            if offset_name:
                cur_offset_name = offset_name
            if reg_name:
                cur_reg_name = reg_name

            if not cur_module or not cur_bases or cur_offset is None:
                continue
            if not bits_text or not field_name:
                continue

            msb, lsb = _parse_bits_range(bits_text)
            if msb is None or lsb is None:
                continue

            width = msb - lsb + 1
            enum_options = _parse_enum_options_from_desc(desc, width)
            if width == 1 and not enum_options:
                enum_options = [(0, "关闭/0"), (1, "开启/1")]

            is_lr = (
                len(cur_bases) == 2
                and sorted(cur_bases) == sorted([0x4001B000, 0x4001D000])
            )

            if is_lr:
                base_l = 0x4001B000
                base_r = 0x4001D000
                addr = None
            else:
                base_l = None
                base_r = None
                addr = cur_bases[0] + cur_offset

            item = {
                "module": cur_module,
                "offset_name": cur_offset_name or f"reg_{cur_offset:03X}",
                "reg_name": cur_reg_name or f"reg_{cur_offset:03X}",
                "field_name": field_name,
                "access": access,
                "description": desc,
                "msb": msb,
                "lsb": lsb,
                "width": width,
                "offset": cur_offset,
                "is_lr": is_lr,
                "base_l": base_l,
                "base_r": base_r,
                "addr": addr,
                "options": enum_options,
            }

            module_fields.setdefault(cur_module, []).append(item)
            flat_fields.append(item)
    except Exception as exc:
        return {}, [], f"ISP.csv 功能字段解析失败: {exc}"

    return module_fields, flat_fields, f"已加载 {len(flat_fields)} 个功能字段（编码: {used_encoding}）"


def _build_fallback_registers():
    eye_bases = [
        (0x4001B000, "L"),
        (0x4001D000, "R"),
    ]
    eye_templates = [
        ("ISP_CTRL", 0x000, "c_ctrl", "31:0"),
        ("isp_inform", 0x010, "c_acq_h_size", "31:0"),
        ("isp_inform", 0x014, "c_acq_v_size", "31:0"),
        ("isp_outform", 0x17C, "c_out_hsize", "31:0"),
        ("isp_outform", 0x180, "c_out_vsize", "31:0"),
        ("NLM", 0x400, "c_nlm_ctrl", "31:0"),
        ("REC", 0x124, "c_rec_h00", "31:0"),
        ("REC", 0x128, "c_rec_h01", "31:0"),
        ("REC", 0x12C, "c_rec_h02", "31:0"),
        ("REC", 0x130, "c_rec_h10", "31:0"),
        ("REC", 0x134, "c_rec_h11", "31:0"),
        ("REC", 0x138, "c_rec_h12", "31:0"),
        ("REC", 0x13C, "c_rec_h20", "31:0"),
        ("REC", 0x140, "c_rec_h21", "31:0"),
        ("REC", 0x144, "c_rec_h22", "31:0"),
        ("REC", 0x148, "c_rec_k12", "31:0"),
        ("REC", 0x14C, "c_rec_fxy0", "31:0"),
    ]
    non_eye = [
        ("TOP", 0x4001C05C, "top_para_3", "31:0"),
        ("TOP", 0x4001C064, "top_para_5", "31:0"),
        ("Stereo", 0x4001E260, "c_stereo_res", "31:0"),
        ("Stereo", 0x4001E264, "c_stereo_res_new", "31:0"),
        ("Stereo", 0x4001E268, "c_stereo_range_p1p2", "31:0"),
        ("Stereo", 0x4001E26C, "c_stere_post_sel", "31:0"),
        ("Stereo", 0x4001E270, "c_stereo_camera", "31:0"),
        ("Stereo", 0x4001E274, "c_stereo_crop_size", "31:0"),
        ("Stereo", 0x4001E278, "c_stereo_disp_clip", "31:0"),
        ("Stereo", 0x4001E27C, "c_stereo_shift_sel", "31:0"),
        ("Stereo", 0x4001E280, "nr3d_control", "31:0"),
    ]

    registers = []
    for module, offset, name, bits in eye_templates:
        registers.append(
            {
                "module": module,
                "name": name,
                "bits": bits,
                "is_lr": True,
                "base_l": eye_bases[0][0],
                "base_r": eye_bases[1][0],
                "offset": offset,
                "addr": None,
            }
        )
    for module, addr, name, bits in non_eye:
        registers.append(
            {
                "module": module,
                "name": name,
                "bits": bits,
                "is_lr": False,
                "base_l": None,
                "base_r": None,
                "offset": None,
                "addr": addr,
            }
        )

    groups = {}
    for item in registers:
        groups.setdefault(item["module"], []).append(item)
    return groups, registers


def _load_isp_registers_from_csv():
    csv_path = _find_isp_csv_path()
    if not csv_path:
        return None, None, "fallback", "未找到 ISP.csv，使用内置寄存器表"

    groups = {}
    flat = []
    seen = set()

    cur_module = ""
    cur_bases = []

    try:
        rows, used_encoding = _read_csv_rows_with_fallback(csv_path)
        for row in rows:
            if not row:
                continue

            cells = list(row) + [""] * (6 - len(row))
            module_raw, base_raw, offset_raw, offset_name, reg_name, bits_raw = cells[:6]

            module_text = _clean_csv_text(module_raw)
            base_text = _clean_csv_text(base_raw)
            offset_text = _clean_csv_text(offset_raw)

            if module_text.lower() == "module":
                continue

            if module_text:
                cur_module = module_text
            if base_text:
                parsed_bases = _parse_base_addresses(base_text)
                if parsed_bases:
                    cur_bases = parsed_bases

            if not offset_text or not cur_module or not cur_bases:
                continue

            try:
                offset_val = _parse_hex_token(offset_text)
            except Exception:
                continue

            if offset_val is None:
                continue

            name = _clean_csv_text(offset_name) or _clean_csv_text(reg_name) or f"reg_{offset_text}"
            bits = _clean_csv_text(bits_raw) or "31:0"

            is_lr_pair = (
                len(cur_bases) == 2
                and sorted(cur_bases) == sorted([0x4001B000, 0x4001D000])
            )

            if is_lr_pair:
                base_l = 0x4001B000
                base_r = 0x4001D000
                item_key = (cur_module, name, offset_val, base_l, base_r, True)
                if item_key in seen:
                    continue
                seen.add(item_key)

                item = {
                    "module": cur_module,
                    "name": name,
                    "bits": bits,
                    "is_lr": True,
                    "base_l": base_l,
                    "base_r": base_r,
                    "offset": offset_val,
                    "addr": None,
                }
                groups.setdefault(cur_module, []).append(item)
                flat.append(item)
                continue

            for base in cur_bases:
                addr = base + offset_val
                item_key = (cur_module, name, addr, False)
                if item_key in seen:
                    continue
                seen.add(item_key)
                item = {
                    "module": cur_module,
                    "name": name,
                    "bits": bits,
                    "is_lr": False,
                    "base_l": None,
                    "base_r": None,
                    "offset": None,
                    "addr": addr,
                }
                groups.setdefault(cur_module, []).append(item)
                flat.append(item)
    except Exception as exc:
        return None, None, "fallback", f"ISP.csv 解析失败，使用内置寄存器表（{exc}）"

    if not flat:
        return None, None, "fallback", "ISP.csv 无有效寄存器条目，使用内置寄存器表"

    return groups, flat, "csv", f"已从 ISP.csv 加载 {len(flat)} 个寄存器条目（编码: {used_encoding}）"


_groups, _registers, _source, _msg = _load_isp_registers_from_csv()
if _groups is None or _registers is None:
    FIXED_REGISTER_GROUPS, FIXED_REGISTERS = _build_fallback_registers()
    FIXED_REG_SOURCE = "fallback"
    FIXED_REG_SOURCE_MSG = _msg
else:
    FIXED_REGISTER_GROUPS, FIXED_REGISTERS = _groups, _registers
    FIXED_REG_SOURCE = _source
    FIXED_REG_SOURCE_MSG = _msg


ISP_FUNCTION_MODULES, ISP_FUNCTION_FIELDS, ISP_FUNCTION_MSG = _load_isp_function_fields_from_csv()


PAD_MUX_ADDR = 0x4001C030
PAD_MUX_MAC_OPTIONS = [
    (0, "sync_in_l"),
    (1, "sync_in_r"),
    (2, "sync_in_all"),
    (3, "gray_out_all"),
    (4, "Disp"),
    (5, "Depth"),
    (6, "DVP_image"),
    (7, "DVP_stereo"),
    (8, "isp3_in"),
    (9, "ISP_3"),
]

PRIORITY_ISP_MODULES = ["ISP_CTRL", "isp_inform", "isp_outform", "REC", "NLM"]
AUTO_CARD_FIELD_LIMIT = 8

MODULE_FIELD_CARDS = {
    "ISP_CTRL": ["CNR_EN", "ISP_GAMMA_OUT_ENABLE", "ISP_AWB_ENABLE", "ISP_GAMMA_IN_ENABLE", "ISP_INFORM_ENABLE", "ISP_MODE", "ISP_CFG_UPD"],
    "isp_inform": ["HSYNC_POL", "VSYNC_POL", "INPUT_SELECTION", "FIELD_SELECTION", "FIELD_INV", "BAYER_PAT", "ACQ_H_SIZE", "ACQ_V_SIZE"],
    "isp_outform": ["ISP_OUT_H_OFFS", "ISP_OUT_V_OFFS", "ISP_OUT_H_SIZE", "ISP_OUT_V_SIZE"],
    "REC": ["rec_bypass_control", "rec_cx", "rec_cy", "rec_k1", "rec_k2"],
    "NLM": ["nlm_bypass_control", "nlm_regs_bay_pat", "nlm_en_exp", "nlm_upgrade_exp"],
}


def list_serial_ports():
    return [port.device for port in serial.tools.list_ports.comports()]


def parse_int(text):
    text = text.strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text, 10)


def parse_int_flexible(text):
    """支持地址/数据尾部带 U/L 后缀（如 0x4001D000UL）"""
    t = text.strip().rstrip(",;")
    while t and t[-1] in {"u", "U", "l", "L"}:
        t = t[:-1]
    return parse_int(t)
