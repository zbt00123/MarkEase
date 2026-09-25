// MarkEase 缩放控制（阶段 12 收尾 修订 5）
// - step=10%
// - 单击轨道靠近 100% 时吸附到 100
// - 拖动不吸附
(function () {
    'use strict';

    const MIN = 10;
    const MAX = 500;
    const STEP = 10;
    const DEFAULT = 100;
    const PRESETS = [50, 75, 100, 125, 150, 200, 300, 400, 500];

    const SNAP_TARGET = 100;
    const SNAP_LOW = 90;
    const SNAP_HIGH = 110;

    let _initialPct = DEFAULT;
    let _changeCallback = null;

    let _display = null;
    let _slider = null;
    let _tick100 = null;
    let _menuEl = null;

    // 单击/拖动判定
    let _pointerDownAt = 0;
    let _inputCount = 0;

    function clamp(v) {
        v = parseInt(v, 10);
        if (!Number.isFinite(v)) v = DEFAULT;
        return Math.max(MIN, Math.min(MAX, v));
    }

    function init(options) {
        const opts = options || {};
        _initialPct = clamp(opts.initialPct);
        _changeCallback = (typeof opts.onChange === 'function') ? opts.onChange : null;

        _display = document.getElementById('zoom-display');
        _slider = document.getElementById('zoom-slider');
        _tick100 = document.getElementById('zoom-tick-100');

        if (!_slider || !_display) {
            console.warn('[zoom] 缺少 #zoom-display 或 #zoom-slider');
            return;
        }

        _slider.min = String(MIN);
        _slider.max = String(MAX);
        _slider.step = String(STEP);
        _slider.value = String(_initialPct);

        // 指针按下：准备判定单击
        _slider.addEventListener('pointerdown', () => {
            _pointerDownAt = Date.now();
            _inputCount = 0;
        });

        // 值变化：立即反映到 UI，不做吸附
        _slider.addEventListener('input', () => {
            _inputCount++;
            const v = clamp(_slider.value);
            _updateDisplay(v);
            _emit(v);
        });

        // 指针松开：若为单击，则尝试吸附
        _slider.addEventListener('pointerup', () => {
            const duration = Date.now() - _pointerDownAt;
            // 单击判定：时间短 且 input 事件少
            if (duration < 400 && _inputCount <= 2) {
                const v = clamp(_slider.value);
                if (v !== SNAP_TARGET && v >= SNAP_LOW && v <= SNAP_HIGH) {
                    setValue(SNAP_TARGET);
                }
            }
            _inputCount = 0;
        });

        // 显示区点击 → 预设菜单
        _display.addEventListener('click', (e) => {
            e.stopPropagation();
            if (_menuEl) _closePresetMenu();
            else _openPresetMenu();
        });

        // 刻度线语义备份（pointer-events: none 不会真正触发）
        if (_tick100) {
            _tick100.addEventListener('click', (e) => {
                e.stopPropagation();
                setValue(DEFAULT);
            });
        }

        document.addEventListener('click', () => _closePresetMenu());
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') _closePresetMenu();
        });

        _updateDisplay(_initialPct);
    }

    function _updateDisplay(v) {
        if (_display) _display.textContent = v + '%';
    }

    function _emit(v) {
        if (_changeCallback) {
            try { _changeCallback(v); } catch (e) { console.warn('[zoom onChange]', e); }
        }
    }

    function setValue(v) {
        v = clamp(v);
        // 对齐到 step
        v = Math.round(v / STEP) * STEP;
        if (v < MIN) v = MIN;
        if (v > MAX) v = MAX;
        if (_slider) _slider.value = String(v);
        _updateDisplay(v);
        _emit(v);
    }

    function getValue() {
        if (_slider) return clamp(_slider.value);
        return _initialPct;
    }

    function _openPresetMenu() {
        _closePresetMenu();
        const rect = _display.getBoundingClientRect();
        const menu = document.createElement('div');
        menu.className = 'zoom-preset-menu';

        const menuWidth = 88;
        let left = rect.left;
        if (left + menuWidth > window.innerWidth - 6) {
            left = window.innerWidth - menuWidth - 6;
        }
        menu.style.left = Math.max(6, left) + 'px';
        menu.style.bottom = (window.innerHeight - rect.top + 4) + 'px';

        const cur = getValue();
        PRESETS.forEach(p => {
            const item = document.createElement('div');
            item.className = 'zoom-preset-item' + (p === cur ? ' active' : '');
            item.textContent = p + '%';
            item.addEventListener('click', (ev) => {
                ev.stopPropagation();
                setValue(p);
                _closePresetMenu();
            });
            menu.appendChild(item);
        });

        document.body.appendChild(menu);
        _menuEl = menu;
    }

    function _closePresetMenu() {
        if (_menuEl && _menuEl.parentNode) {
            _menuEl.parentNode.removeChild(_menuEl);
        }
        _menuEl = null;
    }

    window.ZoomBar = {
        init: init,
        setValue: setValue,
        getValue: getValue,
    };
})();