"""设置管理模块"""

import json
import os
import tempfile
from constants import (
    DEFAULT_WS_PORT, DEFAULT_HTTP_PORT, DEFAULT_OSC_RECV_PORT,
    DEFAULT_CHATBOX_PORT, MAX_INTENSITY
)

SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "ws_port": DEFAULT_WS_PORT,
    "http_port": DEFAULT_HTTP_PORT,
    "osc_recv_port": DEFAULT_OSC_RECV_PORT,
    "chatbox_port": DEFAULT_CHATBOX_PORT,
    "a_limit": 0,
    "b_limit": 0,
    "waveform_mode": "library",
    "custom_waveform": "",
    "chatbox_enabled": True,
    "chatbox_interval": 3,
    "chatbox_toggles": {
        "title": True,
        "strength": True,
        "time": True,
        "waveform": True,
        "custom": False
    },
    "custom_chatbox_text": "DGLAB - Sensora\n\n波形: {wave}\nA: {a}/{a_max}  B: {b}/{b_max}",
    "avatar_channel_a": [
        {
            "path": "/avatar/parameters/Shock/TouchAreaA",
            "type": "float",
            "mode": "distance",
            "trigger_range": [0.4, 1.0]
        }
    ],
    "avatar_channel_b": [
        {
            "path": "/avatar/parameters/Shock/TouchAreaB",
            "type": "float",
            "mode": "distance",
            "trigger_range": [0.4, 1.0]
        }
    ],
    "rate_limit_enabled": True,
    "rate_limit_value": 20
}


class Settings:
    """设置管理器，支持JSON持久化"""

    def __init__(self, path=None):
        self._path = path or SETTINGS_FILE
        self._data = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self):
        """从文件加载设置，缺失键用默认值补全"""
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._data = self._merge(DEFAULT_SETTINGS, saved)
            except (json.JSONDecodeError, IOError):
                self._data = dict(DEFAULT_SETTINGS)
        self._validate()

    def save(self):
        """原子写入设置到文件"""
        self._validate()
        dir_name = os.path.dirname(os.path.abspath(self._path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self._validate()
        self.save()

    def get_all(self):
        return dict(self._data)

    def update(self, data: dict):
        self._data.update(data)
        self._validate()
        self.save()

    def _validate(self):
        """验证并修正设置值"""
        self._data["ws_port"] = self._clamp(self._data["ws_port"], 1, 65535)
        self._data["http_port"] = self._clamp(self._data["http_port"], 1, 65535)
        self._data["osc_recv_port"] = self._clamp(self._data["osc_recv_port"], 1, 65535)
        self._data["chatbox_port"] = self._clamp(self._data["chatbox_port"], 1, 65535)
        self._data["a_limit"] = self._clamp(self._data["a_limit"], 0, MAX_INTENSITY)
        self._data["b_limit"] = self._clamp(self._data["b_limit"], 0, MAX_INTENSITY)
        self._data["chatbox_interval"] = self._clamp(self._data["chatbox_interval"], 1, 60)

    @staticmethod
    def _clamp(value, min_val, max_val):
        try:
            return max(min_val, min(int(value), max_val))
        except (TypeError, ValueError):
            return min_val

    @staticmethod
    def _merge(defaults, saved):
        """递归合并，保留saved中的值，补全缺失键"""
        result = dict(defaults)
        for key, value in saved.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Settings._merge(result[key], value)
            else:
                result[key] = value
        return result
