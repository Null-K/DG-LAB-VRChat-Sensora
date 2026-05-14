"""核心控制器 - 协调所有模块"""

import asyncio
import logging
import time
from collections import deque
from settings import Settings
from ws_server import WSServer
from osc_handler import OSCHandler
from http_server import HttpServer
from waveform import generate_waveform
from waveform_library import get_names, get_preset, loop_waveform, scale_waveform
from constants import (
    APP_VERSION, SAFETY_WINDOW_SECONDS, SAFETY_MAX_PER_WINDOW,
    SAFETY_MAX_TOTAL, WAVEFORM_FEED_INTERVAL
)

logger = logging.getLogger(__name__)


class App:
    """应用核心控制器"""

    def __init__(self):
        self.settings = Settings()
        self.ws = WSServer()
        self.osc = OSCHandler()
        self.http = HttpServer()
        # 状态
        self._running = False
        self._waveform_task = None
        self._chatbox_task = None
        self._remaining_a = 0.0
        self._remaining_b = 0.0
        self._current_wave_a = []
        self._current_wave_b = []
        self._wave_name_a = ""
        self._wave_name_b = ""
        self._wave_generation = 0
        # 波形监视 (最近发送的波形数据用于前端绘制)
        self._wave_monitor_a = []  # 最近的强度值列表 (0-100)
        self._wave_monitor_b = []
        # 日志收集
        self._logs = []  # [{time, level, message}]
        self._max_logs = 500
        # 安全计时
        self._shock_history = deque()
        # 速率限制状态
        self._last_strength_a = 0
        self._last_strength_b = 0
        self._last_strength_time = time.time()
        # UI通知回调
        self.on_state_change = None  # () -> None
        # 安装日志处理器
        self._install_log_handler()

    async def start(self):
        """启动所有服务"""
        self._running = True
        # 设置回调
        self.ws.on_connected = self._on_device_connected
        self.ws.on_disconnected = self._on_device_disconnected
        self.ws.on_strength_update = self._on_strength_update
        self.osc.on_wave_output = self._on_osc_wave
        self.http.on_shock = self._on_http_shock
        self.http.on_sendwave = self._on_http_sendwave
        self.http.get_status = self.get_status

        # 启动服务
        try:
            await self.ws.start(port=self.settings.get("ws_port"))
        except Exception as e:
            logger.error(f"WebSocket 启动失败: {e}")

        try:
            await self.osc.start(
                recv_port=self.settings.get("osc_recv_port"),
                chatbox_port=self.settings.get("chatbox_port")
            )
            # 配置OSC通道
            self._configure_osc_channels()
        except Exception as e:
            logger.error(f"OSC 启动失败: {e}")

        try:
            await self.http.start(port=self.settings.get("http_port"))
        except Exception as e:
            logger.error(f"HTTP 启动失败: {e}")

        # 应用强度设置
        await self._apply_strength()
        # 启动Chatbox定时发送任务
        self._chatbox_task = asyncio.create_task(self._chatbox_loop())
        logger.info("所有服务已启动")

    async def stop(self):
        """停止所有服务"""
        self._running = False
        if self._waveform_task:
            self._waveform_task.cancel()
        if self._chatbox_task:
            self._chatbox_task.cancel()
        await self.ws.stop()
        await self.osc.stop()
        await self.http.stop()
        logger.info("所有服务已停止")

    # ===== 公开API (供前端调用) =====

    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "connected": self.ws.connected,
            "strength_a": self.ws.strength_a,
            "strength_b": self.ws.strength_b,
            "strength_a_max": self.ws.strength_a_limit,
            "strength_b_max": self.ws.strength_b_limit,
            "a_limit": self.settings.get("a_limit"),
            "b_limit": self.settings.get("b_limit"),
            "remaining_a": round(self._remaining_a, 1),
            "remaining_b": round(self._remaining_b, 1),
            "wave_name_a": self._wave_name_a,
            "wave_name_b": self._wave_name_b,
            "osc_active": self.osc._osc_active,
            "chatbox_active": self.osc._chatbox_active,
            "version": APP_VERSION
        }

    def get_qrcode(self) -> str:
        """获取二维码base64"""
        return self.ws.get_qrcode_base64()

    def get_waveform_names(self) -> list:
        """获取波形预设名称列表"""
        return get_names()

    def get_wave_monitor(self) -> dict:
        """获取波形监视数据"""
        return {
            "a": self._wave_monitor_a[-50:],  # 最近50个点
            "b": self._wave_monitor_b[-50:]
        }

    def get_osc_values(self) -> dict:
        """获取OSC通道当前参数值"""
        return {
            "a_value": round(self.osc.channel_a._value, 4),
            "b_value": round(self.osc.channel_b._value, 4),
            "a_active": self.osc.channel_a._active,
            "b_active": self.osc.channel_b._active
        }

    def get_logs(self, level: str = "all") -> list:
        """获取日志列表"""
        if level == "all":
            return self._logs[-200:]
        return [l for l in self._logs if l["level"] == level][-200:]

    def clear_logs(self):
        """清空日志"""
        self._logs.clear()

    def get_settings(self) -> dict:
        """获取所有设置"""
        return self.settings.get_all()

    async def update_settings(self, data: dict):
        """更新设置"""
        self.settings.update(data)
        # 重新配置OSC通道
        self._configure_osc_channels()
        self.osc.chatbox_enabled = self.settings.get("chatbox_enabled")
        self.osc.chatbox_interval = self.settings.get("chatbox_interval")
        # 应用强度
        await self._apply_strength()
        self._notify_state()

    async def set_strength(self, channel: str, value: int):
        """设置通道强度限制，不超过设备上报的上限，支持速率限制"""
        if channel == "A":
            max_val = self.ws.strength_a_limit if self.ws.connected else 200
            value = max(0, min(max_val, value))
            value = self._apply_rate_limit("A", value)
            self.settings.set("a_limit", value)
            await self.ws.set_strength(1, value)
        else:
            max_val = self.ws.strength_b_limit if self.ws.connected else 200
            value = max(0, min(max_val, value))
            value = self._apply_rate_limit("B", value)
            self.settings.set("b_limit", value)
            await self.ws.set_strength(2, value)
        self._notify_state()

    async def fire_waveform(self, channel: str, seconds: int,
                            mode: str = None, custom: str = None):
        """触发波形
        channel: "A", "B", "all"
        seconds: 1-10
        """
        seconds = max(1, min(10, seconds))
        # 安全检查
        seconds = self._apply_safety(seconds)
        if seconds <= 0:
            return

        if mode is None:
            mode = self.settings.get("waveform_mode")
        if custom is None:
            custom = self.settings.get("custom_waveform")

        if channel in ("A", "all"):
            limit = self.settings.get("a_limit")
            max_val = self.ws.strength_a_limit if self.ws.connected else 200
            intensity = min(limit, max_val)
            wave, name = generate_waveform(seconds, intensity, mode, custom)
            self._current_wave_a = wave
            self._wave_name_a = name
            self._remaining_a = seconds

        if channel in ("B", "all"):
            limit = self.settings.get("b_limit")
            max_val = self.ws.strength_b_limit if self.ws.connected else 200
            intensity = min(limit, max_val)
            wave, name = generate_waveform(seconds, intensity, mode, custom)
            self._current_wave_b = wave
            self._wave_name_b = name
            self._remaining_b = seconds

        # 启动波形喂食
        self._wave_generation += 1
        if self._waveform_task:
            self._waveform_task.cancel()
        self._waveform_task = asyncio.create_task(
            self._waveform_feeder(self._wave_generation)
        )
        self._notify_state()

    async def stop_waveform(self):
        """停止波形"""
        self._remaining_a = 0
        self._remaining_b = 0
        self._wave_name_a = ""
        self._wave_name_b = ""
        if self._waveform_task:
            self._waveform_task.cancel()
            self._waveform_task = None
        await self.ws.stop_waveform()
        self._notify_state()

    # ===== 内部方法 =====

    def _configure_osc_channels(self):
        """配置OSC通道"""
        ch_a = self.settings.get("avatar_channel_a")
        ch_b = self.settings.get("avatar_channel_b")
        if ch_a:
            self.osc.configure_channel("A", ch_a)
        if ch_b:
            self.osc.configure_channel("B", ch_b)

    async def _apply_strength(self):
        """应用强度设置到设备"""
        if self.ws.connected:
            await self.ws.set_strength(1, self.settings.get("a_limit"))
            await self.ws.set_strength(2, self.settings.get("b_limit"))

    def _apply_safety(self, seconds: int) -> int:
        """安全限制检查"""
        now = time.time()
        # 清理过期记录
        while self._shock_history and (now - self._shock_history[0]) > SAFETY_WINDOW_SECONDS:
            self._shock_history.popleft()
        # 窗口内累计
        window_total = len(self._shock_history)
        if window_total >= SAFETY_MAX_PER_WINDOW:
            return 0
        # 总剩余限制
        total_remaining = self._remaining_a + self._remaining_b
        if total_remaining >= SAFETY_MAX_TOTAL:
            return 0
        # 允许的最大秒数
        allowed = min(seconds, SAFETY_MAX_TOTAL - int(total_remaining))
        # 记录
        for _ in range(allowed):
            self._shock_history.append(now)
        return max(0, allowed)

    def _apply_rate_limit(self, channel: str, target: int) -> int:
        """应用强度变化速率限制
        
        如果启用了速率限制，每次调用只允许变化 rate_limit_value 以内的幅度。
        """
        if not self.settings.get("rate_limit_enabled"):
            # 未启用，直接更新记录并返回
            if channel == "A":
                self._last_strength_a = target
            else:
                self._last_strength_b = target
            return target

        rate = self.settings.get("rate_limit_value") or 50
        now = time.time()
        dt = now - self._last_strength_time
        self._last_strength_time = now
        # 允许的最大变化量 = 速率 * 时间差 (至少允许变化1)
        max_delta = max(1, int(rate * max(dt, 0.05)))

        if channel == "A":
            current = self._last_strength_a
            delta = target - current
            if abs(delta) > max_delta:
                target = current + max_delta if delta > 0 else current - max_delta
            target = max(0, target)
            self._last_strength_a = target
        else:
            current = self._last_strength_b
            delta = target - current
            if abs(delta) > max_delta:
                target = current + max_delta if delta > 0 else current - max_delta
            target = max(0, target)
            self._last_strength_b = target

        return target

    async def _waveform_feeder(self, generation: int):
        """波形喂食循环"""
        try:
            wave_idx_a = 0
            wave_idx_b = 0
            while self._running and generation == self._wave_generation:
                # 设备断开时停止
                if not self.ws.connected:
                    logger.info("设备断开，波形喂食停止")
                    break

                # 计算本次发送量 (0.5秒 = 5条)
                feed_count = 5

                if self._remaining_a > 0 and self._current_wave_a:
                    chunk = self._current_wave_a[wave_idx_a:wave_idx_a + feed_count]
                    if not chunk:
                        wave_idx_a = 0
                        chunk = self._current_wave_a[:feed_count]
                    await self.ws.send_waveform("A", chunk)
                    self._update_wave_monitor("A", chunk)
                    wave_idx_a += feed_count
                    self._remaining_a -= WAVEFORM_FEED_INTERVAL
                    if self._remaining_a <= 0:
                        self._remaining_a = 0
                        self._wave_name_a = ""
                        await self.ws.clear_waveform(1)

                if self._remaining_b > 0 and self._current_wave_b:
                    chunk = self._current_wave_b[wave_idx_b:wave_idx_b + feed_count]
                    if not chunk:
                        wave_idx_b = 0
                        chunk = self._current_wave_b[:feed_count]
                    await self.ws.send_waveform("B", chunk)
                    self._update_wave_monitor("B", chunk)
                    wave_idx_b += feed_count
                    self._remaining_b -= WAVEFORM_FEED_INTERVAL
                    if self._remaining_b <= 0:
                        self._remaining_b = 0
                        self._wave_name_b = ""
                        await self.ws.clear_waveform(2)

                self._notify_state()

                # 两个通道都结束
                if self._remaining_a <= 0 and self._remaining_b <= 0:
                    break

                await asyncio.sleep(WAVEFORM_FEED_INTERVAL)
        except asyncio.CancelledError:
            pass

    def _on_device_connected(self):
        """设备连接回调"""
        logger.info("DG-LAB 设备已连接")
        # 连接后自动应用强度设置
        asyncio.create_task(self._apply_strength())
        self._notify_state()

    def _on_device_disconnected(self):
        """设备断开回调"""
        logger.info("DG-LAB 设备已断开")
        # 停止所有波形活动
        self._remaining_a = 0
        self._remaining_b = 0
        self._wave_name_a = ""
        self._wave_name_b = ""
        self._current_wave_a = []
        self._current_wave_b = []
        if self._waveform_task:
            self._waveform_task.cancel()
            self._waveform_task = None
        self._notify_state()

    def _on_strength_update(self, a, b, a_max, b_max):
        """强度更新回调"""
        self._notify_state()

    async def _chatbox_loop(self):
        """独立的Chatbox定时发送循环"""
        try:
            while self._running:
                interval = self.settings.get("chatbox_interval") or 3
                await asyncio.sleep(interval)
                if self._running and self.osc.chatbox_enabled:
                    self._send_chatbox_update()
        except asyncio.CancelledError:
            pass

    def _send_chatbox_update(self):
        """生成并发送Chatbox消息"""
        if not self.osc._chatbox_active:
            return
        custom_text = self.settings.get("custom_chatbox_text")
        if custom_text:
            text = custom_text \
                .replace("{a}", str(self.ws.strength_a)) \
                .replace("{b}", str(self.ws.strength_b)) \
                .replace("{a_max}", str(self.ws.strength_a_limit)) \
                .replace("{b_max}", str(self.ws.strength_b_limit)) \
                .replace("{wave}", self._wave_name_a or self._wave_name_b or "-")
        else:
            parts = []
            parts.append(f"A:{self.ws.strength_a}/{self.ws.strength_a_limit}")
            parts.append(f"B:{self.ws.strength_b}/{self.ws.strength_b_limit}")
            if self._wave_name_a or self._wave_name_b:
                wave = self._wave_name_a or self._wave_name_b
                remain = max(self._remaining_a, self._remaining_b)
                parts.append(f"{wave} {remain:.0f}s")
            text = " | ".join(parts)
        self.osc.send_chatbox(text[:144])

    def _on_osc_wave(self, channel: str, wave_data: str):
        """OSC波形输出回调"""
        if not self.ws.connected:
            return
        self._update_wave_monitor(channel, [wave_data])
        asyncio.create_task(self.ws.send_waveform(channel, [wave_data]))

    def _on_http_shock(self, channel: str, seconds: int):
        """HTTP电击请求回调"""
        ch = channel.upper()
        if ch == "ALL":
            ch = "all"
        elif ch not in ("A", "B"):
            ch = "A"
        asyncio.create_task(self.fire_waveform(ch, seconds))

    def _on_http_sendwave(self, channel: str, repeat: int, data: str):
        """HTTP波形发送回调"""
        try:
            wave_list = data.split(",") if "," in data else [data]
            if repeat > 1:
                wave_list = wave_list * repeat
            ch = channel.upper() if channel.upper() in ("A", "B") else "A"
            asyncio.create_task(self.ws.send_waveform(ch, wave_list))
        except Exception as e:
            logger.warning(f"HTTP 波形发送失败: {e}")

    def _notify_state(self):
        """通知前端状态变化"""
        if self.on_state_change:
            self.on_state_change()

    def _install_log_handler(self):
        """安装自定义日志处理器，收集日志到内存"""
        handler = _AppLogHandler(self)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(handler)

    def _add_log(self, level: str, message: str):
        """添加日志条目"""
        import datetime
        entry = {
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message
        }
        self._logs.append(entry)
        if len(self._logs) > self._max_logs:
            self._logs = self._logs[-self._max_logs:]

    def _update_wave_monitor(self, channel: str, data: list):
        """更新波形监视数据"""
        # 从HEX数据中提取强度值 (取每条的第一个强度字节)
        values = []
        for entry in data:
            if len(entry) >= 16:
                try:
                    val = int(entry[8:10], 16)  # 第一个强度字节
                    values.append(val * 100 // 200)  # 归一化到0-100
                except ValueError:
                    values.append(0)
        if channel == "A":
            self._wave_monitor_a.extend(values)
            self._wave_monitor_a = self._wave_monitor_a[-100:]
        else:
            self._wave_monitor_b.extend(values)
            self._wave_monitor_b = self._wave_monitor_b[-100:]


class _AppLogHandler(logging.Handler):
    """自定义日志处理器，将日志转发到App实例"""

    def __init__(self, app: App):
        super().__init__()
        self._app = app

    def emit(self, record):
        try:
            level = record.levelname.lower()
            if level == "warning":
                level = "warning"
            elif level == "error" or level == "critical":
                level = "error"
            else:
                level = "info"
            self._app._add_log(level, self.format(record))
        except Exception:
            pass
