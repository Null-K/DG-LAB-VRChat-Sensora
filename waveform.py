"""波形生成模块"""

import math
from waveform_library import (
    get_preset, get_random_for_second, get_random,
    scale_waveform, loop_waveform
)


def generate_waveform(seconds: int, intensity: int, mode: str = "library",
                      custom_waveform: str = "") -> tuple:
    """生成波形数据
    
    Args:
        seconds: 持续秒数 (1-10)
        intensity: 目标强度 (0-200)
        mode: 波形模式 (library/custom/instant/gradual)
        custom_waveform: 自定义波形名称 (mode=custom时使用)
    
    Returns:
        (wave_data: list[str], wave_name: str)
    """
    target_count = seconds * 10  # 每秒10条(100ms/条)

    if mode == "instant":
        return _generate_instant(target_count, intensity), "恒定"

    elif mode == "gradual":
        return _generate_gradual(target_count, intensity), "渐强"

    elif mode == "custom":
        data = get_preset(custom_waveform)
        if data:
            scaled = scale_waveform(data, intensity)
            looped = loop_waveform(scaled, target_count)
            return looped, custom_waveform
        # 找不到自定义波形，回退到随机
        return _generate_from_library(seconds, target_count, intensity)

    else:  # library
        return _generate_from_library(seconds, target_count, intensity)


def _generate_from_library(seconds, target_count, intensity):
    """从波形库随机选取并生成"""
    name, data = get_random_for_second(min(seconds, 10))
    scaled = scale_waveform(data, intensity)
    looped = loop_waveform(scaled, target_count)
    return looped, name


def _generate_instant(count, intensity):
    """生成恒定强度波形"""
    hex_val = f"{min(intensity, 200):02X}"
    entry = f"0A0A0A0A{hex_val}{hex_val}{hex_val}{hex_val}"
    return [entry] * count


def _generate_gradual(count, intensity):
    """生成余弦渐强波形"""
    result = []
    for i in range(count):
        progress = i / max(count - 1, 1)
        # 余弦渐强: 0 -> intensity
        val = int(intensity * (1 - math.cos(progress * math.pi)) / 2)
        val = min(val, 200)
        hex_val = f"{val:02X}"
        result.append(f"0A0A0A0A{hex_val}{hex_val}{hex_val}{hex_val}")
    return result


def generate_wave_100ms(freq: int, from_val: int, to_val: int) -> str:
    """生成单条100ms波形 (用于OSC实时输出)
    
    Args:
        freq: 频率值 (0-255)
        from_val: 起始强度 (0-200)
        to_val: 结束强度 (0-200)
    
    Returns:
        16字符HEX字符串
    """
    freq = max(0, min(255, freq))
    from_val = max(0, min(200, from_val))
    to_val = max(0, min(200, to_val))
    freq_hex = f"{freq:02X}" * 4
    # 4字节强度: 线性插值
    i1 = from_val
    i2 = from_val + (to_val - from_val) // 3
    i3 = from_val + 2 * (to_val - from_val) // 3
    i4 = to_val
    inten_hex = f"{i1:02X}{i2:02X}{i3:02X}{i4:02X}"
    return freq_hex + inten_hex
