"""OSC处理模块 - VRChat Avatar参数接收 + Chatbox输出"""

import asyncio
import logging
import socket
import time
from collections import deque
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
from waveform import generate_wave_100ms

logger = logging.getLogger(__name__)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """检测指定端口是否有程序在监听"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
        sock.close()
        return False  # 能绑定说明没人用
    except OSError:
        return True  # 绑定失败说明已被占用


def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    """检测端口是否可用于绑定"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
        sock.close()
        return True
    except OSError:
        return False


class OSCHandler:
    """OSC处理器，管理Avatar参数接收和Chatbox输出
    
    仅在检测到相关端口可用时才启动，避免占用端口。
    """

    def __init__(self):
        self._server = None
        self._chatbox_client = None
        self._running = False
        self._osc_active = False
        self._chatbox_active = False
        # 通道处理器
        self.channel_a = ChannelHandler("A")
        self.channel_b = ChannelHandler("B")
        # 回调
        self.on_wave_output = None  # (channel, wave_data) -> None
        # Chatbox设置
        self.chatbox_enabled = True
        self.chatbox_interval = 3
        self._last_chatbox_time = 0

    async def start(self, recv_port=9001, chatbox_port=9000):
        """启动OSC服务"""
        self._running = True

        # Chatbox是UDP客户端，直接创建（UDP无连接，不需要检测目标端口）
        self._chatbox_client = SimpleUDPClient("127.0.0.1", chatbox_port)
        self._chatbox_active = True
        logger.info(f"ChatBox 客户端已创建: 目标端口 {chatbox_port}")

        # 直接尝试启动OSC接收服务器，失败则跳过
        try:
            dispatcher = Dispatcher()
            dispatcher.set_default_handler(self._osc_handler)
            self._server = AsyncIOOSCUDPServer(
                ("0.0.0.0", recv_port), dispatcher, asyncio.get_event_loop()
            )
            await self._server.create_serve_endpoint()
            self._osc_active = True
            # 启动波形输出任务
            asyncio.create_task(self._wave_feeder())
            logger.info(f"OSC 接收服务启动: 端口 {recv_port}")
        except Exception as e:
            self._osc_active = False
            logger.warning(f"OSC 接收端口 {recv_port} 启动失败: {e}")

    async def stop(self):
        """停止OSC"""
        self._running = False
        self._osc_active = False
        self._chatbox_active = False
        self._server = None
        self._chatbox_client = None

    def configure_channel(self, channel: str, params_list: list):
        """配置通道参数
        channel: "A" 或 "B"
        params_list: [{path, type, mode, trigger_range}, ...]
        """
        handler = self.channel_a if channel == "A" else self.channel_b
        handler.set_params(params_list)

    def _osc_handler(self, address: str, *args):
        """默认OSC消息处理"""
        if not args:
            return
        value = args[0]
        if not isinstance(value, (int, float, bool)):
            return
        value = float(value)
        # 检查是否匹配通道参数
        matched = False
        for handler in [self.channel_a, self.channel_b]:
            if handler.matches(address):
                handler.update(value)
                matched = True
        if matched:
            logger.debug(f"OSC匹配: {address} = {value}")

    async def _wave_feeder(self):
        """50ms间隔的波形输出任务"""
        try:
            while self._running:
                await asyncio.sleep(0.05)
                for handler in [self.channel_a, self.channel_b]:
                    wave = handler.get_wave()
                    if wave and self.on_wave_output:
                        self.on_wave_output(handler.name, wave)
        except asyncio.CancelledError:
            pass

    def send_chatbox(self, text: str):
        """发送Chatbox消息"""
        if not self._chatbox_active or not self._chatbox_client:
            return
        try:
            self._chatbox_client.send_message("/chatbox/input", [text, True, False])
        except Exception as e:
            logger.warning(f"ChatBox 发送失败: {e}")


class ChannelHandler:
    """单通道OSC处理器，支持多参数条目"""

    def __init__(self, name: str):
        self.name = name
        self._params = []  # [{path, type, mode, trigger_range}]
        self._value = 0.0
        self._last_update = 0.0
        self._history = deque(maxlen=20)
        self._active = False
        self._cooldown_until = 0.0
        self._matched_entry = None  # 最近匹配的参数条目

    def set_params(self, params_list: list):
        """设置参数列表"""
        self._params = params_list or []

    def matches(self, address: str) -> bool:
        """检查OSC地址是否匹配本通道的任一参数条目"""
        for entry in self._params:
            path = entry.get("path", "")
            if not path:
                continue
            if path.endswith("*"):
                if address.startswith(path[:-1]):
                    self._matched_entry = entry
                    return True
            elif address == path:
                self._matched_entry = entry
                return True
        return False

    def update(self, value: float):
        """更新OSC值"""
        now = time.time()
        self._value = value
        self._last_update = now
        self._history.append((now, value))
        self._active = True

    def get_wave(self):
        """获取当前应输出的波形数据 (100ms)，无输出返回None"""
        now = time.time()
        entry = self._matched_entry
        if not entry:
            return None

        mode = entry.get("mode", "distance")
        param_type = entry.get("type", "float")
        trigger_range = entry.get("trigger_range", [0.0, 1.0])

        # 超时检测
        timeout = 0.5 if mode != "shock" else 5.0
        if now - self._last_update > timeout:
            self._active = False
            return None
        if not self._active:
            return None

        # bool 类型处理
        if param_type == "bool":
            return self._bool_wave(trigger_range, now)

        # float 类型
        if mode == "distance":
            return self._distance_wave(trigger_range)
        elif mode == "shock":
            return self._shock_wave(trigger_range, now)
        elif mode == "touch":
            return self._touch_wave()
        return None

    def _bool_wave(self, trigger_range, now):
        """布尔模式: 值匹配触发条件时触发电击"""
        if now < self._cooldown_until:
            return None
        # trigger_range[0]: 1=true触发, 0=false触发
        trigger_val = trigger_range[0] if trigger_range else 1
        if (trigger_val >= 1 and self._value >= 0.5) or \
           (trigger_val < 1 and self._value < 0.5):
            self._cooldown_until = now + 1.0
            return generate_wave_100ms(10, 100, 100)
        return None

    def _distance_wave(self, trigger_range):
        """距离模式: 值直接映射到强度"""
        low, high = trigger_range[0], trigger_range[1] if len(trigger_range) > 1 else 1.0
        if self._value < low or self._value > high:
            return None
        normalized = (self._value - low) / max(high - low, 0.001)
        intensity = int(normalized * 100)
        if intensity <= 0:
            return None
        return generate_wave_100ms(10, intensity, intensity)

    def _shock_wave(self, trigger_range, now):
        """电击模式: 超过阈值触发"""
        if now < self._cooldown_until:
            return None
        threshold = trigger_range[0] if trigger_range else 0.5
        if self._value >= threshold:
            self._cooldown_until = now + 1.0
            return generate_wave_100ms(10, 100, 100)
        return None

    def _touch_wave(self):
        """触摸模式: 基于导数的强度映射"""
        if len(self._history) < 3:
            return None
        times = [h[0] for h in self._history]
        values = [h[1] for h in self._history]
        dt = times[-1] - times[-3]
        if dt <= 0:
            return None
        derivative = abs(values[-1] - values[-3]) / dt
        intensity = int(min(derivative * 50, 100))
        if intensity <= 2:
            return None
        return generate_wave_100ms(10, intensity, intensity)
