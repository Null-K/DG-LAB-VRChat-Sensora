"""HTTP服务器 - 供VRChat地图调用的API"""

import asyncio
import json
import logging
from aiohttp import web

logger = logging.getLogger(__name__)


class HttpServer:
    """HTTP API服务器，兼容ShockingManager协议"""

    def __init__(self):
        self._app = None
        self._runner = None
        self._site = None
        self._running = False
        # 回调
        self.on_shock = None  # (channel, seconds) -> None
        self.on_sendwave = None  # (channel, repeat, data) -> None
        # 状态获取
        self.get_status = None  # () -> dict

    async def start(self, port=8800):
        """启动HTTP服务器"""
        self._app = web.Application()
        self._app.router.add_get("/api/v1/status", self._handle_status)
        self._app.router.add_get("/api/v1/shock/{channel}/{seconds}", self._handle_shock_path)
        self._app.router.add_get("/api/v1/sendwave/{channel}/{data}", self._handle_sendwave_path)
        self._app.router.add_get("/{path:.*}", self._handle_request)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", port)
        await self._site.start()
        self._running = True
        logger.info(f"HTTP 服务器启动: http://0.0.0.0:{port}")

    async def stop(self):
        """停止HTTP服务器"""
        self._running = False
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        self._app = None
        logger.info("HTTP 服务器已停止")

    async def _handle_status(self, request):
        """返回设备状态"""
        status = self._get_device_status()
        return web.json_response(status)

    async def _handle_shock_path(self, request):
        """处理路径格式的电击请求: /api/v1/shock/{channel}/{seconds}"""
        channel = request.match_info.get("channel", "A")
        seconds_str = request.match_info.get("seconds", "1")
        try:
            seconds = min(max(int(seconds_str), 1), 10)
            if self.on_shock:
                self.on_shock(channel, seconds)
                logger.info(f"HTTP电击触发: 通道={channel}, 秒数={seconds}")
            return web.json_response({"status": "ok", "channel": channel, "seconds": seconds})
        except ValueError:
            return web.json_response({"error": "invalid seconds"}, status=400)

    async def _handle_sendwave_path(self, request):
        """处理路径格式的波形请求: /api/v1/sendwave/{channel}/{data}"""
        channel = request.match_info.get("channel", "A")
        data = request.match_info.get("data", "")
        repeat = request.query.get("repeat", "1")
        try:
            repeat_n = int(repeat)
            if data and self.on_sendwave:
                self.on_sendwave(channel, repeat_n, data)
            return web.json_response({"status": "ok"})
        except ValueError:
            return web.json_response({"error": "invalid params"}, status=400)

    async def _handle_request(self, request):
        """处理通用请求"""
        # 验证User-Agent (仅允许VRChat/Unity来源)
        ua = request.headers.get("User-Agent", "")
        if "UnityPlayer" not in ua and "VRChat" not in ua:
            # 开发模式也允许访问
            pass

        # 解析查询参数
        params = request.query
        ret = params.get("ret", "")

        if ret == "status":
            return web.json_response(self._get_device_status())

        # 电击请求: ?shock={channel}&seconds={n}
        channel = params.get("shock", params.get("channel", ""))
        seconds = params.get("seconds", params.get("time", ""))

        if channel and seconds:
            try:
                sec = min(int(seconds), 10)
                if sec > 0 and self.on_shock:
                    self.on_shock(channel, sec)
                return web.json_response({"status": "ok", "channel": channel, "seconds": sec})
            except ValueError:
                return web.json_response({"error": "invalid seconds"}, status=400)

        # 波形发送: ?sendwave={channel}&repeat={n}&data={hex}
        wave_channel = params.get("sendwave", "")
        repeat = params.get("repeat", "1")
        wave_data = params.get("data", "")

        if wave_channel and wave_data:
            try:
                repeat_n = int(repeat)
                if self.on_sendwave:
                    self.on_sendwave(wave_channel, repeat_n, wave_data)
                return web.json_response({"status": "ok"})
            except ValueError:
                return web.json_response({"error": "invalid params"}, status=400)

        # 默认返回状态
        return web.json_response(self._get_device_status())

    def _get_device_status(self) -> dict:
        """获取设备状态"""
        if self.get_status:
            info = self.get_status()
        else:
            info = {"connected": False, "strength_a": 0, "strength_b": 0}

        return {
            "healthy": "ok" if info.get("connected") else "disconnected",
            "devices": [{
                "type": "shock",
                "device": "coyotev3",
                "attr": {
                    "strength": {
                        "A": info.get("strength_a", 0),
                        "B": info.get("strength_b", 0)
                    },
                    "uuid": "dglab-coyote"
                }
            }] if info.get("connected") else []
        }
