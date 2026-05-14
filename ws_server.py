"""WebSocket服务器 - 基于pydglab-ws库与DG-LAB APP通信"""

import asyncio
import logging
import socket
import io
import base64
from typing import Optional, List, Tuple

import qrcode
from pydglab_ws import (
    DGLabWSServer,
    DGLabLocalClient,
    StrengthData,
    RetCode,
    Channel,
    StrengthOperationType,
    FeedbackButton,
)
from pydglab_ws.typing import PulseOperation
from pydglab_ws.utils import PULSE_DATA_MAX_LENGTH

logger = logging.getLogger(__name__)


def hex_to_pulse(hex_str: str) -> PulseOperation:
    """将16字符HEX字符串转换为PulseOperation元组
    
    格式: FFFFIIII (4字节频率 + 4字节强度)
    频率范围 [10, 240], 强度范围 [0, 100]
    """
    freq = tuple(
        max(10, min(240, int(hex_str[i*2:i*2+2], 16)))
        for i in range(4)
    )
    # 注意: HEX中强度是0-200(0x00-0xC8), pydglab-ws要求0-100
    strength = tuple(
        max(0, min(100, int(hex_str[8+i*2:8+i*2+2], 16) * 100 // 200))
        for i in range(4)
    )
    return (freq, strength)


def hex_list_to_pulses(hex_list: List[str]) -> List[PulseOperation]:
    """批量转换HEX波形数据为PulseOperation列表"""
    result = []
    for h in hex_list:
        if len(h) >= 16:
            try:
                result.append(hex_to_pulse(h))
            except (ValueError, IndexError):
                continue
    return result


class WSServer:
    """DG-LAB WebSocket服务器封装
    
    使用pydglab-ws库实现完整的DG-LAB v2协议，
    包含优雅的连接/断开处理和自动重绑定。
    """

    def __init__(self):
        self._server: Optional[DGLabWSServer] = None
        self._client: Optional[DGLabLocalClient] = None
        self._running = False
        self._bound = False
        self._host = "0.0.0.0"
        self._port = 9999
        self._data_task: Optional[asyncio.Task] = None
        self._bind_task: Optional[asyncio.Task] = None
        # 状态回调
        self.on_connected = None      # () -> None
        self.on_disconnected = None   # () -> None
        self.on_strength_update = None  # (a, b, a_limit, b_limit) -> None
        # 当前强度
        self.strength_a = 0
        self.strength_b = 0
        self.strength_a_limit = 200
        self.strength_b_limit = 200

    @property
    def connected(self) -> bool:
        return self._bound and self._client is not None and not self._client.not_bind

    @property
    def qrcode_url(self) -> Optional[str]:
        if self._client is None or self._client.not_registered:
            return None
        host = self._get_local_ip()
        uri = f"ws://{host}:{self._port}"
        return self._client.get_qrcode(uri)

    def get_qrcode_base64(self) -> str:
        """生成二维码的base64编码PNG图片"""
        url = self.qrcode_url
        if not url:
            return ""
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    async def start(self, host="0.0.0.0", port=9999):
        """启动WebSocket服务器并等待绑定"""
        self._host = host
        self._port = port
        self._running = True
        self._bound = False

        # 创建服务器 (带心跳)
        self._server = DGLabWSServer(host, port, heartbeat_interval=60)
        await self._server.__aenter__()

        # 创建本地客户端
        self._client = self._server.new_local_client()

        # 注册断开回调
        self._server.add_connection_callback("disconnect", self._on_ws_disconnect)

        logger.info(f"WebSocket 服务器启动: ws://{host}:{port}")
        logger.info(f"二维码 URL: {self.qrcode_url}")

        # 启动绑定等待任务
        self._bind_task = asyncio.create_task(self._bind_loop())

    async def stop(self):
        """优雅停止服务器"""
        self._running = False
        self._bound = False

        # 取消任务
        if self._data_task:
            self._data_task.cancel()
            try:
                await self._data_task
            except asyncio.CancelledError:
                pass
            self._data_task = None

        if self._bind_task:
            self._bind_task.cancel()
            try:
                await self._bind_task
            except asyncio.CancelledError:
                pass
            self._bind_task = None

        # 移除本地客户端
        if self._server and self._client:
            await self._server.remove_local_client(self._client.client_id)

        # 关闭服务器
        if self._server:
            await self._server.__aexit__(None, None, None)
            self._server = None

        self._client = None
        logger.info("WebSocket 服务器已优雅停止")

    async def _bind_loop(self):
        """等待APP绑定的循环，支持断开后重新绑定"""
        try:
            while self._running:
                if self._client.not_bind:
                    logger.info("等待 DG-LAB APP 扫码连接...")
                    ret = await self._client.bind()
                    if ret == RetCode.SUCCESS:
                        self._bound = True
                        logger.info("DG-LAB APP 已绑定")
                        if self.on_connected:
                            self.on_connected()
                        # 启动数据接收
                        self._data_task = asyncio.create_task(self._data_receiver())
                    else:
                        logger.warning(f"绑定失败: {ret}")
                        await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"绑定循环异常: {e}")

    async def _data_receiver(self):
        """接收APP数据 (强度更新、反馈、断开通知)"""
        try:
            async for data in self._client.data_generator():
                if isinstance(data, StrengthData):
                    self.strength_a = data.a
                    self.strength_b = data.b
                    self.strength_a_limit = data.a_limit
                    self.strength_b_limit = data.b_limit
                    if self.on_strength_update:
                        self.on_strength_update(data.a, data.b, data.a_limit, data.b_limit)

                elif data == RetCode.CLIENT_DISCONNECTED:
                    logger.info("DG-LAB APP 已断开连接")
                    self._bound = False
                    if self.on_disconnected:
                        self.on_disconnected()
                    # 重新等待绑定
                    if self._running:
                        logger.info("等待重新连接...")
                        ret = await self._client.rebind()
                        if ret == RetCode.SUCCESS:
                            self._bound = True
                            logger.info("DG-LAB APP 已重新绑定")
                            if self.on_connected:
                                self.on_connected()

                elif isinstance(data, FeedbackButton):
                    logger.debug(f"收到 APP 反馈按钮: {data}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"数据接收异常: {e}")
            self._bound = False
            if self.on_disconnected:
                self.on_disconnected()

    async def _on_ws_disconnect(self, uuid, websocket):
        """WebSocket连接断开回调"""
        logger.debug(f"WebSocket 连接断开: {uuid}")

    # ===== 公开控制API =====

    async def set_strength(self, channel: int, value: int):
        """设置通道强度
        channel: 1=A, 2=B
        value: 0-200
        """
        if not self.connected:
            return
        value = max(0, min(200, value))
        ch = Channel.A if channel == 1 else Channel.B
        try:
            await self._client.set_strength(ch, StrengthOperationType.SET_TO, value)
        except Exception as e:
            logger.warning(f"设置强度失败: {e}")

    async def send_waveform(self, channel: str, data: List[str]):
        """发送波形数据到指定通道
        channel: "A" 或 "B"
        data: HEX字符串列表 (每条16字符)
        """
        if not self.connected or not data:
            return
        ch = Channel.A if channel == "A" else Channel.B
        pulses = hex_list_to_pulses(data)
        if not pulses:
            return
        # 分块发送，每次最多PULSE_DATA_MAX_LENGTH(86)条
        try:
            for i in range(0, len(pulses), PULSE_DATA_MAX_LENGTH):
                chunk = pulses[i:i + PULSE_DATA_MAX_LENGTH]
                await self._client.add_pulses(ch, *chunk)
        except Exception as e:
            logger.warning(f"发送波形失败: {e}")

    async def clear_waveform(self, channel: int):
        """清除通道波形队列 (channel: 1=A, 2=B)"""
        if not self.connected:
            return
        ch = Channel.A if channel == 1 else Channel.B
        try:
            await self._client.clear_pulses(ch)
        except Exception as e:
            logger.warning(f"清除波形失败: {e}")

    async def stop_waveform(self):
        """停止所有通道波形"""
        await self.clear_waveform(1)
        await self.clear_waveform(2)

    @staticmethod
    def _get_local_ip() -> str:
        """获取本机局域网IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
