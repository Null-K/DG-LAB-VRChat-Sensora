/**
 * DG-LAB Coyote - 前端逻辑
 */

// 状态轮询定时器
let pollTimer = null;

/** 动态获取pywebview API引用 */
function getApi() {
    return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

// ===== 初始化 =====

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initControls();
    // 等待pywebview就绪
    if (window.pywebview && window.pywebview.api) {
        onReady();
    } else {
        window.addEventListener('pywebviewready', onReady);
    }
});

function onReady() {
    loadQRCode();
    loadSettings();
    loadWaveforms();
    startPolling();
    startWaveMonitor();
    startLogPolling();
    startChatboxPreview();
}

// ===== 导航 =====

function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            navItems.forEach(n => n.classList.remove('active'));
            item.classList.add('active');
            const page = item.dataset.page;
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById(`page-${page}`).classList.add('active');
        });
    });
}

// ===== 控制绑定 =====

function initControls() {
    const sliderA = document.getElementById('sliderA');
    const sliderB = document.getElementById('sliderB');

    sliderA.addEventListener('change', () => {
        const api = getApi();
        if (api) api.set_strength('A', parseInt(sliderA.value));
    });
    sliderB.addEventListener('change', () => {
        const api = getApi();
        if (api) api.set_strength('B', parseInt(sliderB.value));
    });

    sliderA.addEventListener('input', () => {
        document.getElementById('limitA').textContent = sliderA.value;
    });
    sliderB.addEventListener('input', () => {
        document.getElementById('limitB').textContent = sliderB.value;
    });

    // 强度预设按钮
    document.querySelectorAll('.preset-btns').forEach(group => {
        const channel = group.dataset.channel;
        group.querySelectorAll('.btn-preset').forEach(btn => {
            btn.addEventListener('click', () => {
                const api = getApi();
                if (!api) return;
                const pct = parseInt(btn.dataset.pct);
                const slider = document.getElementById(channel === 'A' ? 'sliderA' : 'sliderB');
                const max = parseInt(slider.max) || 200;
                const value = Math.round(max * pct / 100);
                slider.value = value;
                document.getElementById(channel === 'A' ? 'limitA' : 'limitB').textContent = value;
                api.set_strength(channel, value);
            });
        });
    });

    // 强度速率限制
    document.getElementById('rateLimitEnabled').addEventListener('change', (e) => {
        const api = getApi();
        if (api) api.update_settings({ rate_limit_enabled: e.target.checked });
    });
    document.getElementById('strengthRateLimit').addEventListener('change', (e) => {
        const api = getApi();
        const val = parseInt(e.target.value) || 50;
        if (api) api.update_settings({ rate_limit_value: val });
    });

    // 触发/停止按钮
    document.getElementById('btnFire').addEventListener('click', () => {
        const api = getApi();
        if (!api) return;
        const channel = document.getElementById('fireChannel').value;
        const seconds = parseInt(document.getElementById('fireSeconds').value);
        api.fire_waveform(channel, seconds);
    });

    document.getElementById('btnStop').addEventListener('click', () => {
        const api = getApi();
        if (api) api.stop_waveform();
    });

    // 保存设置
    document.getElementById('btnSaveSettings').addEventListener('click', saveSettings);

    // 刷新二维码
    document.getElementById('btnRefreshQR').addEventListener('click', loadQRCode);

    // Chatbox开关即时生效
    document.getElementById('chatboxEnabled').addEventListener('change', (e) => {
        const api = getApi();
        if (api) api.update_settings({ chatbox_enabled: e.target.checked });
    });

    // Chatbox自定义文本字数统计和即时保存
    const chatboxTextarea = document.getElementById('customChatbox');
    chatboxTextarea.addEventListener('input', () => {
        const len = chatboxTextarea.value.length;
        document.getElementById('chatboxCharCount').textContent = len;
        // 超过144裁切
        if (len > 144) {
            chatboxTextarea.value = chatboxTextarea.value.substring(0, 144);
            document.getElementById('chatboxCharCount').textContent = 144;
        }
    });
    chatboxTextarea.addEventListener('change', () => {
        const api = getApi();
        if (api) api.update_settings({ custom_chatbox_text: chatboxTextarea.value });
    });

    // Chatbox发送间隔即时保存
    document.getElementById('chatboxInterval').addEventListener('change', (e) => {
        const api = getApi();
        if (api) api.update_settings({ chatbox_interval: parseInt(e.target.value) || 3 });
    });

    // OSC参数添加按钮
    document.getElementById('btnAddParamA').addEventListener('click', () => addParamRow('A'));
    document.getElementById('btnAddParamB').addEventListener('click', () => addParamRow('B'));

    // 波形模式切换时即时保存
    document.getElementById('waveformMode').addEventListener('change', (e) => {
        const customGroup = document.getElementById('customWaveGroup');
        customGroup.style.display = e.target.value === 'custom' ? 'block' : 'none';
        const api = getApi();
        if (api) api.update_settings({ waveform_mode: e.target.value });
    });

    document.getElementById('customWaveform').addEventListener('change', (e) => {
        const api = getApi();
        if (api) api.update_settings({ custom_waveform: e.target.value });
    });

    // 日志清空
    document.getElementById('btnClearLog').addEventListener('click', () => {
        const api = getApi();
        if (api) api.clear_logs();
        document.getElementById('logList').innerHTML = '<div class="log-empty">暂无日志</div>';
    });

    // 日志复制
    document.getElementById('btnCopyLog').addEventListener('click', () => {
        const api = getApi();
        if (!api) return;
        const filter = document.getElementById('logFilter').value;
        api.get_logs(filter).then(logs => {
            if (!logs || !logs.length) return;
            const text = logs.map(l => `[${l.time}] [${l.level.toUpperCase()}] ${l.message}`).join('\n');
            navigator.clipboard.writeText(text).then(() => {
                showToast('日志已复制到剪贴板');
            }).catch(() => {
                // fallback
                const ta = document.createElement('textarea');
                ta.value = text;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                showToast('日志已复制到剪贴板');
            });
        });
    });

    // 日志筛选
    document.getElementById('logFilter').addEventListener('change', () => {
        refreshLogs();
    });
}

// ===== 数据加载 =====

function loadQRCode() {
    const api = getApi();
    if (!api) return;
    api.get_qrcode().then(base64 => {
        if (base64) {
            document.getElementById('qrContainer').innerHTML =
                `<img src="data:image/png;base64,${base64}" alt="QR Code">`;
        }
    }).catch(e => {
        console.error('加载二维码失败:', e);
    });
}

function loadSettings() {
    const api = getApi();
    if (!api) return;
    api.get_settings().then(settings => {
        if (!settings) return;

        document.getElementById('sliderA').value = settings.a_limit || 0;
        document.getElementById('sliderB').value = settings.b_limit || 0;
        document.getElementById('limitA').textContent = settings.a_limit || 0;
        document.getElementById('limitB').textContent = settings.b_limit || 0;
        document.getElementById('waveformMode').value = settings.waveform_mode || 'library';
        document.getElementById('chatboxEnabled').checked = settings.chatbox_enabled !== false;
        document.getElementById('chatboxInterval').value = settings.chatbox_interval || 3;
        document.getElementById('customChatbox').value = settings.custom_chatbox_text || '';
        document.getElementById('chatboxCharCount').textContent = (settings.custom_chatbox_text || '').length;
        document.getElementById('wsPort').value = settings.ws_port || 9999;
        document.getElementById('httpPort').value = settings.http_port || 8800;
        document.getElementById('oscRecvPort').value = settings.osc_recv_port || 9001;
        document.getElementById('chatboxPort').value = settings.chatbox_port || 9000;

        // OSC通道参数列表
        renderParamList('A', settings.avatar_channel_a || []);
        renderParamList('B', settings.avatar_channel_b || []);

        // 波形模式显示
        const customGroup = document.getElementById('customWaveGroup');
        customGroup.style.display = settings.waveform_mode === 'custom' ? 'block' : 'none';

        // 速率限制
        document.getElementById('rateLimitEnabled').checked = settings.rate_limit_enabled || false;
        document.getElementById('strengthRateLimit').value = settings.rate_limit_value || 50;
    }).catch(e => {
        console.error('加载设置失败:', e);
    });
}

function loadWaveforms() {
    const api = getApi();
    if (!api) return;
    api.get_waveform_names().then(names => {
        if (!names || !names.length) return;

        // 填充波形网格
        const grid = document.getElementById('waveformGrid');
        grid.innerHTML = names.map(name =>
            `<div class="waveform-item" data-name="${name}">${name}</div>`
        ).join('');

        // 填充自定义波形下拉
        const select = document.getElementById('customWaveform');
        select.innerHTML = names.map(name =>
            `<option value="${name}">${name}</option>`
        ).join('');

        // 点击波形项触发
        grid.querySelectorAll('.waveform-item').forEach(item => {
            item.addEventListener('click', () => {
                const api2 = getApi();
                const name = item.dataset.name;
                if (api2) api2.fire_waveform('all', 3, 'custom', name);
                grid.querySelectorAll('.waveform-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
            });
        });
    }).catch(e => {
        console.error('加载波形失败:', e);
    });
}

// ===== 状态更新 =====

function startPolling() {
    pollTimer = setInterval(updateStatus, 500);
}

function updateStatus() {
    const api = getApi();
    if (!api) return;
    api.get_status().then(status => {
        if (!status) return;

        // 连接状态
        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        const connStatus = document.getElementById('connStatus');

        if (status.connected) {
            dot.className = 'status-dot connected';
            text.textContent = '已连接';
            connStatus.textContent = '已连接';
            connStatus.style.color = '#22c55e';
        } else {
            dot.className = 'status-dot disconnected';
            text.textContent = '未连接';
            connStatus.textContent = '等待连接';
            connStatus.style.color = '';
        }

        // 强度显示
        document.getElementById('strengthA').textContent = status.strength_a;
        document.getElementById('strengthB').textContent = status.strength_b;
        document.getElementById('strengthAMax').textContent = status.strength_a_max;
        document.getElementById('strengthBMax').textContent = status.strength_b_max;

        // 连接后动态调整滑块最大值为设备上报的通道上限
        if (status.connected && status.strength_a_max > 0) {
            const sliderA = document.getElementById('sliderA');
            const sliderB = document.getElementById('sliderB');
            if (parseInt(sliderA.max) !== status.strength_a_max) {
                sliderA.max = status.strength_a_max;
                document.getElementById('sliderAMax').textContent = status.strength_a_max;
            }
            if (parseInt(sliderB.max) !== status.strength_b_max) {
                sliderB.max = status.strength_b_max;
                document.getElementById('sliderBMax').textContent = status.strength_b_max;
            }
        }

        // 剩余时间
        document.getElementById('remainA').textContent = status.remaining_a;
        document.getElementById('remainB').textContent = status.remaining_b;

        // 波形名
        const waveText = [status.wave_name_a, status.wave_name_b]
            .filter(n => n).join(' / ') || '-';
        document.getElementById('waveName').textContent = waveText;

        // 服务状态指示
        const oscDot = document.getElementById('svcOscDot');
        const chatboxDot = document.getElementById('svcChatboxDot');
        const httpDot = document.getElementById('svcHttpDot');
        if (oscDot) {
            oscDot.className = status.osc_active ? 'service-dot connected' : 'service-dot inactive';
            document.getElementById('svcOscInfo').textContent = status.osc_active ? '运行中' : '未启动';
        }
        if (chatboxDot) {
            chatboxDot.className = status.chatbox_active ? 'service-dot connected' : 'service-dot inactive';
            document.getElementById('svcChatboxInfo').textContent = status.chatbox_active ? '已连接' : '未检测到 VRChat';
        }
        if (httpDot) {
            httpDot.className = 'service-dot connected';
        }
    }).catch(() => {
        // 静默处理
    });
}

// 后端主动通知状态变化
window.onStateChange = function() {
    updateStatus();
};

// ===== 设置保存 =====

function saveOscChannels() {
    const api = getApi();
    if (!api) return;
    api.update_settings({
        avatar_channel_a: collectParamList('A'),
        avatar_channel_b: collectParamList('B')
    });
}

function saveSettings() {
    const api = getApi();
    if (!api) return;

    const data = {
        waveform_mode: document.getElementById('waveformMode').value,
        custom_waveform: document.getElementById('customWaveform').value,
        chatbox_enabled: document.getElementById('chatboxEnabled').checked,
        chatbox_interval: parseInt(document.getElementById('chatboxInterval').value) || 3,
        custom_chatbox_text: document.getElementById('customChatbox').value,
        ws_port: parseInt(document.getElementById('wsPort').value) || 9999,
        http_port: parseInt(document.getElementById('httpPort').value) || 8800,
        osc_recv_port: parseInt(document.getElementById('oscRecvPort').value) || 9001,
        chatbox_port: parseInt(document.getElementById('chatboxPort').value) || 9000,
        avatar_channel_a: collectParamList('A'),
        avatar_channel_b: collectParamList('B')
    };

    api.update_settings(data).then(() => {
        showToast('设置已保存');
    }).catch(e => {
        console.error('保存设置失败:', e);
    });
}

// ===== 工具函数 =====

function showToast(message) {
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed; bottom: 20px; right: 20px;
        background: #FFE99D; color: #121212;
        padding: 10px 20px; border-radius: 8px;
        font-size: 13px; font-weight: 500; z-index: 9999;
        animation: fadeIn 0.2s ease;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2000);
}

// ===== 波形监视 =====

let waveMonitorTimer = null;

function startWaveMonitor() {
    waveMonitorTimer = setInterval(updateWaveMonitor, 200);
}

function updateWaveMonitor() {
    const api = getApi();
    if (!api) return;
    api.get_wave_monitor().then(data => {
        if (!data) return;
        drawWaveform('waveCanvasA', data.a || []);
        drawWaveform('waveCanvasB', data.b || []);
    }).catch(() => {});
}

function drawWaveform(canvasId, values) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;

    ctx.clearRect(0, 0, w, h);

    if (!values.length) {
        // 画一条中线
        ctx.strokeStyle = '#333333';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, h / 2);
        ctx.lineTo(w, h / 2);
        ctx.stroke();
        return;
    }

    // 画波形
    const step = w / Math.max(values.length - 1, 1);
    ctx.strokeStyle = '#FFE99D';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.beginPath();

    for (let i = 0; i < values.length; i++) {
        const x = i * step;
        const y = h - (values[i] / 100) * (h - 4) - 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // 填充区域
    ctx.lineTo((values.length - 1) * step, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    ctx.fillStyle = 'rgba(255, 233, 157, 0.1)';
    ctx.fill();
}

// ===== 日志 =====

let logPollTimer = null;

function startLogPolling() {
    logPollTimer = setInterval(refreshLogs, 2000);
}

function refreshLogs() {
    const api = getApi();
    if (!api) return;
    const filter = document.getElementById('logFilter').value;
    api.get_logs(filter).then(logs => {
        if (!logs) return;
        const list = document.getElementById('logList');
        if (!logs.length) {
            list.innerHTML = '<div class="log-empty">暂无日志</div>';
            return;
        }
        // 只渲染最近200条
        const html = logs.slice(-200).map(entry => {
            const levelClass = entry.level || 'info';
            return `<div class="log-entry"><span class="log-time">${entry.time}</span><span class="log-level ${levelClass}">${levelClass.toUpperCase()}</span>${escapeHtml(entry.message)}</div>`;
        }).join('');
        list.innerHTML = html;
        // 自动滚动到底部
        list.scrollTop = list.scrollHeight;
    }).catch(() => {});
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ===== Chatbox 预览 =====

function startChatboxPreview() {
    // 输入变化时更新预览
    document.getElementById('customChatbox').addEventListener('input', updateChatboxPreview);
    // 初始更新
    setInterval(updateChatboxPreview, 1000);
    // OSC参数值轮询
    setInterval(updateOscValues, 200);
}

function updateChatboxPreview() {
    const template = document.getElementById('customChatbox').value;
    const preview = document.getElementById('chatboxPreview');
    if (!template) {
        preview.textContent = '(未设置自定义文本)';
        return;
    }
    const api = getApi();
    if (!api) {
        preview.textContent = template;
        return;
    }
    api.get_status().then(status => {
        if (!status) return;
        let text = template
            .replace(/\{a\}/g, status.strength_a || 0)
            .replace(/\{b\}/g, status.strength_b || 0)
            .replace(/\{a_max\}/g, status.strength_a_max || 200)
            .replace(/\{b_max\}/g, status.strength_b_max || 200)
            .replace(/\{wave\}/g, status.wave_name_a || status.wave_name_b || '-');
        preview.textContent = text;
    }).catch(() => {
        preview.textContent = template;
    });
}

// ===== OSC 参数监视 =====

function updateOscValues() {
    const api = getApi();
    if (!api) return;
    api.get_osc_values().then(data => {
        if (!data) return;
        const valA = document.getElementById('oscValueA');
        const valB = document.getElementById('oscValueB');
        const barA = document.getElementById('oscBarA');
        const barB = document.getElementById('oscBarB');

        if (data.a_active) {
            valA.textContent = data.a_value.toFixed(3);
            barA.style.width = (Math.min(Math.abs(data.a_value), 1) * 100) + '%';
        } else {
            valA.textContent = '-';
            barA.style.width = '0%';
        }

        if (data.b_active) {
            valB.textContent = data.b_value.toFixed(3);
            barB.style.width = (Math.min(Math.abs(data.b_value), 1) * 100) + '%';
        } else {
            valB.textContent = '-';
            barB.style.width = '0%';
        }
    }).catch(() => {});
}

// ===== OSC 参数列表管理 =====

function renderParamList(channel, params) {
    const list = document.getElementById('paramList' + channel);
    if (!params || !params.length) {
        list.innerHTML = '<div class="param-empty">暂无参数，点击添加</div>';
        return;
    }
    list.innerHTML = params.map((p, i) => createParamRowHtml(channel, i, p)).join('');
    // 绑定事件
    list.querySelectorAll('.param-row').forEach(row => {
        row.querySelectorAll('input, select').forEach(el => {
            el.addEventListener('change', saveOscChannels);
        });
        row.querySelector('.btn-remove').addEventListener('click', () => {
            row.remove();
            if (!list.querySelector('.param-row')) {
                list.innerHTML = '<div class="param-empty">暂无参数，点击添加</div>';
            }
            saveOscChannels();
        });
    });
}

function createParamRowHtml(channel, index, param) {
    const path = param.path || '';
    const type = param.type || 'float';
    const mode = param.mode || 'distance';
    const rangeA = param.trigger_range ? param.trigger_range[0] : 0;
    const rangeB = param.trigger_range ? param.trigger_range[1] : 1;

    return `<div class="param-row" data-channel="${channel}">
        <input type="text" class="param-path" value="${path}" placeholder="/avatar/parameters/...">
        <select class="param-type">
            <option value="float" ${type === 'float' ? 'selected' : ''}>Float</option>
            <option value="bool" ${type === 'bool' ? 'selected' : ''}>Bool</option>
        </select>
        <select class="param-mode">
            <option value="distance" ${mode === 'distance' ? 'selected' : ''}>距离</option>
            <option value="shock" ${mode === 'shock' ? 'selected' : ''}>电击</option>
            <option value="touch" ${mode === 'touch' ? 'selected' : ''}>触摸</option>
        </select>
        <input type="number" class="param-range-min" value="${rangeA}" step="0.1" min="0" max="1" title="触发最小值">
        <input type="number" class="param-range-max" value="${rangeB}" step="0.1" min="0" max="1" title="触发最大值">
        <button class="btn-remove" title="删除">x</button>
    </div>`;
}

function addParamRow(channel) {
    const list = document.getElementById('paramList' + channel);
    // 清除空提示
    const empty = list.querySelector('.param-empty');
    if (empty) empty.remove();

    const newParam = { path: '', type: 'float', mode: 'distance', trigger_range: [0, 1] };
    const div = document.createElement('div');
    div.innerHTML = createParamRowHtml(channel, 0, newParam);
    const row = div.firstElementChild;
    list.appendChild(row);

    // 绑定事件
    row.querySelectorAll('input, select').forEach(el => {
        el.addEventListener('change', saveOscChannels);
    });
    row.querySelector('.btn-remove').addEventListener('click', () => {
        row.remove();
        if (!list.querySelector('.param-row')) {
            list.innerHTML = '<div class="param-empty">暂无参数，点击添加</div>';
        }
        saveOscChannels();
    });

    // 聚焦到路径输入框
    row.querySelector('.param-path').focus();
}

function collectParamList(channel) {
    const list = document.getElementById('paramList' + channel);
    const rows = list.querySelectorAll('.param-row');
    const result = [];
    rows.forEach(row => {
        const path = row.querySelector('.param-path').value.trim();
        if (!path) return;
        result.push({
            path: path,
            type: row.querySelector('.param-type').value,
            mode: row.querySelector('.param-mode').value,
            trigger_range: [
                parseFloat(row.querySelector('.param-range-min').value) || 0,
                parseFloat(row.querySelector('.param-range-max').value) || 1
            ]
        });
    });
    return result;
}
