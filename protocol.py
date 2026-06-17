import serial
import struct
import time


CMD_VERSION = 0x56  # 'V'


class FpgaProtocol:
    response_timeout = 5  # 默认超时时间，单位秒

    def __init__(self, port, baudrate=14400, timeout=1):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        self.header = 0x02
        self.tail = 0x03

    def _calculate_checksum(self, data_bytes):
        """计算校验位:所有字节累加取低8位"""
        return sum(data_bytes) & 0xFF

    def pack_frame(self, cmd, addr, data):
        """将指令打包成 12 字节的二进制帧"""
        main_part = struct.pack('>BBII', self.header, cmd, addr, data)
        cs = self._calculate_checksum(main_part)
        full_frame = main_part + struct.pack('>BB', cs, self.tail)
        return full_frame

    def send_command(self, cmd, addr, data=0):
        """发送指令并等待回传"""
        self.ser.reset_input_buffer()
        frame = self.pack_frame(cmd, addr, data)
        print(f"发送原始数据: {frame.hex(' ').upper()}")
        self.ser.write(frame)

        response = self.read_frame(self.response_timeout)
        if response:
            print(f"回传原始数据: {response.hex(' ').upper()}")
            return self.unpack_frame(response)
        return "错误：读取超时或无响应"

    def read_pending_text(self, initial_wait=0.6, idle_gap=0.15, max_bytes=4096):
        """读取串口中已有的启动日志/文本信息。"""
        if initial_wait > 0:
            time.sleep(initial_wait)

        chunks = []
        deadline = time.time() + idle_gap
        while time.time() < deadline and sum(len(c) for c in chunks) < max_bytes:
            waiting = self.ser.in_waiting
            if waiting > 0:
                chunks.append(self.ser.read(min(waiting, max_bytes - sum(len(c) for c in chunks))))
                deadline = time.time() + idle_gap
            else:
                time.sleep(0.02)

        if not chunks:
            return ""

        return b"".join(chunks).decode("utf-8", errors="replace").strip()

    def query_firmware_version(self):
        """查询固件版本，返回 (major, minor, patch, raw_result)。"""
        result = self.send_command(cmd=CMD_VERSION, addr=0, data=0)
        if not isinstance(result, dict):
            raise ValueError(result)

        raw = int(result.get("data", 0))
        major = (raw >> 16) & 0xFF
        minor = (raw >> 8) & 0xFF
        patch = raw & 0xFF
        return major, minor, patch, result

    def unpack_frame(self, frame):
        """解析硬件回传的帧"""
        if len(frame) < 12:
            return "错误: 长度不足"

        header, cmd, addr, data, cs, tail = struct.unpack('>BBIIBB', frame)
        expected_cs = self._calculate_checksum(frame[:10])
        if header != self.header or tail != self.tail:
            return "错误: 帧头或帧尾不匹配"
        if cs != expected_cs:
            return "错误: 校验失败"

        return {"cmd": cmd, "addr": hex(addr), "data": data}

    def read_frame(self, timeout=1):
        """等待帧头出现后，再继续读取剩余字节。"""
        frame_len = 12
        remaining_len = frame_len - 1

        original_timeout = self.ser.timeout
        end_time = time.time() + timeout if timeout is not None else None
        self.ser.timeout = timeout
        try:
            while True:
                if end_time is not None and time.time() > end_time:
                    return None

                first = self.ser.read(1)
                if not first:
                    continue

                if first[0] != self.header:
                    continue

                if end_time is not None:
                    remaining_timeout = max(0, end_time - time.time())
                    self.ser.timeout = remaining_timeout

                rest = self.ser.read(remaining_len)
                if len(rest) < remaining_len:
                    return None
                return first + rest
        finally:
            self.ser.timeout = original_timeout

    def close(self):
        """关闭串口资源"""
        if self.ser and self.ser.is_open:
            self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def send_fpga_command(port, cmd, addr, data=0, baudrate=115200, timeout=1, response_timeout=5):
    """发送指令并返回解析结果。"""
    with FpgaProtocol(port, baudrate, timeout) as fpga:
        fpga.response_timeout = response_timeout
        return fpga.send_command(cmd=cmd, addr=addr, data=data)


ISP_BATCH_CONFIG = [
    (0x4001B400, "nlm_l", 0x00000003),
    (0x4001D400, "nlm_r", 0x00000003),
    (0x4001B148, "c_rec_k12_L", 0x00000000),
    (0x4001B14C, "c_rec_fxy0_L", 0x003EF3EE),
    (0x4001B124, "c_rec_h00_L", 0x000003E9),
    (0x4001B128, "c_rec_h01_L", 0x003FFFE7),
    (0x4001B12C, "c_rec_h02_L", 0x0031E7A3),
    (0x4001B130, "c_rec_h10_L", 0x00000019),
    (0x4001B134, "c_rec_h11_L", 0x000003E9),
    (0x4001B138, "c_rec_h12_L", 0x0037A701),
    (0x4001B13C, "c_rec_h20_L", 0x003FFFFC),
    (0x4001B140, "c_rec_h21_L", 0x003FFFFC),
    (0x4001B144, "c_rec_h22_L", 0x0010199E),
    (0x4001B120, "c_rec_bypass_control_cxy_L", 0x80107720),
    (0x4001D148, "c_rec_k12_R", 0x00000000),
    (0x4001D14C, "c_rec_fxy0_R", 0x003F13F1),
    (0x4001D124, "c_rec_h00_R", 0x000003E9),
    (0x4001D128, "c_rec_h01_R", 0x003FFFDC),
    (0x4001D12C, "c_rec_h02_R", 0x00320153),
    (0x4001D130, "c_rec_h10_R", 0x00000025),
    (0x4001D134, "c_rec_h11_R", 0x000003E9),
    (0x4001D138, "c_rec_h12_R", 0x00375C81),
    (0x4001D13C, "c_rec_h20_R", 0x003FFFFC),
    (0x4001D140, "c_rec_h21_R", 0x00000004),
    (0x4001D144, "c_rec_h22_R", 0x001008B1),
    (0x4001D120, "c_rec_bypass_control_cxy_R", 0x80107F5C),
    (0x4001B010, "c_acq_h_size_L", 0x00000500),
    (0x4001B014, "c_acq_v_size_L", 0x000002D0),
    (0x4001B17C, "c_out_hsize_L", 0x00000500),
    (0x4001B180, "c_out_vsize_L", 0x000002D0),
    (0x4001B000, "c_ctrl_L", 0x0000E316),
    (0x4001D010, "c_acq_h_size_R", 0x00000500),
    (0x4001D014, "c_acq_v_size_R", 0x000002D0),
    (0x4001D17C, "c_out_hsize_R", 0x00000500),
    (0x4001D180, "c_out_vsize_R", 0x000002D0),
    (0x4001D000, "c_ctrl_R", 0x0000E316),
    (0x4001E26C, "c_stereo_post_sel", 0x00A00018),
    (0x4001E268, "c_stereo_range_p1p2", 0x04809080),
    (0x4001E270, "c_stereo_camera", 0x43FB7E14),
    (0x4001E274, "c_stereo_crop_size", 0x00000000),
    (0x4001E278, "c_stereo_disp_clip", 0x00000021),
    (0x4001E27C, "c_stereo_shift_sel", 0x0000002E),
    (0x4001E280, "nr3d_control", 0x3050580A),
    (0x4001E260, "c_stereo_res", 0x80168500),
    (0x4001E264, "c_stereo_res_new", 0x00168500),
]


def apply_isp_batch_config(port, baudrate=115200, timeout=1, response_timeout=5, verbose=True):
    """在软件端执行 ISP 批量配置（写入一组寄存器，发送绝对地址）。"""
    results = []
    with FpgaProtocol(port, baudrate, timeout) as fpga:
        fpga.response_timeout = response_timeout
        for addr, name, value in ISP_BATCH_CONFIG:
            result = fpga.send_command(cmd=0x57, addr=addr, data=value)
            results.append((addr, name, value, result))
            if verbose:
                print(f"WRITE {name} @0x{addr:08X} = 0x{value:08X} -> {result}")
    return results
