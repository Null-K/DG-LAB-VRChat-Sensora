"""DG-LAB Coyote - 主入口"""

import asyncio
import logging
import os
import sys
import threading
import webview
from app import App

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


def get_base_dir():
    """获取程序运行目录（exe所在目录，用于settings.json等用户文件）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_dir():
    """获取资源文件目录，兼容Nuitka onefile打包
    
    Nuitka onefile 运行时会将数据文件解压到临时目录，
    此时 __file__ 指向临时目录中的 main.py 位置。
    """
    candidates = [
        # Nuitka onefile: __file__ 所在目录（临时解压目录）
        os.path.dirname(os.path.abspath(__file__)),
        # 开发模式 / standalone: 脚本同目录
        os.path.dirname(os.path.abspath(sys.argv[0])),
        # exe 所在目录
        os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else None,
    ]
    for d in candidates:
        if d and os.path.isfile(os.path.join(d, "web", "index.html")):
            return d
    # fallback
    return os.path.dirname(os.path.abspath(__file__))


class WebAPI:
    """pywebview JS-Python桥接API"""

    def __init__(self, app: App):
        self._app = app
        self._loop = None
        self._window = None

    def set_loop(self, loop):
        self._loop = loop

    def set_window(self, window):
        self._window = window

    def _run_async(self, coro):
        """在asyncio事件循环中运行协程"""
        if self._loop:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result(timeout=10)

    # ===== 前端调用的API =====

    def get_status(self):
        return self._app.get_status()

    def get_qrcode(self):
        return self._app.get_qrcode()

    def get_waveform_names(self):
        return self._app.get_waveform_names()

    def get_settings(self):
        return self._app.get_settings()

    def update_settings(self, data):
        self._run_async(self._app.update_settings(data))

    def set_strength(self, channel, value):
        self._run_async(self._app.set_strength(channel, value))

    def fire_waveform(self, channel, seconds, mode=None, custom=None):
        self._run_async(self._app.fire_waveform(channel, seconds, mode, custom))

    def stop_waveform(self):
        self._run_async(self._app.stop_waveform())

    def get_wave_monitor(self):
        return self._app.get_wave_monitor()

    def get_osc_values(self):
        return self._app.get_osc_values()

    def get_logs(self, level="all"):
        return self._app.get_logs(level)

    def clear_logs(self):
        self._app.clear_logs()


def run_async_loop(app: App, api: WebAPI, shutdown_event: threading.Event):
    """在独立线程中运行asyncio事件循环"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    api.set_loop(loop)

    async def main():
        await app.start()
        # 保持运行直到收到关闭信号
        while not shutdown_event.is_set():
            await asyncio.sleep(0.5)
        # 优雅关闭
        await app.stop()

    try:
        loop.run_until_complete(main())
    except Exception as e:
        logger.error(f"异步循环异常: {e}")
    finally:
        loop.close()


def on_window_loaded(window, app, api):
    """窗口加载完成回调"""
    # 设置状态变化通知
    def notify():
        if window:
            window.evaluate_js("window.onStateChange && window.onStateChange()")

    app.on_state_change = notify


def main():
    """主函数"""
    base_dir = get_base_dir()
    resource_dir = get_resource_dir()

    # 工作目录设为exe所在目录（settings.json保存在这里）
    os.chdir(base_dir)

    app = App()
    api = WebAPI(app)
    shutdown_event = threading.Event()

    # 启动asyncio线程
    async_thread = threading.Thread(
        target=run_async_loop, args=(app, api, shutdown_event), daemon=True
    )
    async_thread.start()

    # 等待事件循环就绪
    import time
    time.sleep(0.5)

    # 创建pywebview窗口
    web_dir = os.path.join(resource_dir, "web")
    index_path = os.path.join(web_dir, "index.html")

    # 确保路径存在
    if not os.path.exists(index_path):
        logger.error(f"Cannot find web/index.html at: {index_path}")
        logger.error(f"base_dir={base_dir}, resource_dir={resource_dir}")
        return

    window = webview.create_window(
        "DG-LAB Sensora",
        url=index_path,
        js_api=api,
        width=900,
        height=870,
        resizable=False,
        maximized=False
    )
    api.set_window(window)
    window.events.loaded += lambda: on_window_loaded(window, app, api)

    # 启动GUI (阻塞)
    webview.start(debug=False)

    # 窗口关闭后，通知后端优雅停止
    logger.info("窗口关闭，正在停止服务...")
    shutdown_event.set()
    async_thread.join(timeout=5)
    logger.info("应用退出")


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
