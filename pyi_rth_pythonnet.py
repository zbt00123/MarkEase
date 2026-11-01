# -*- coding: utf-8 -*-
import os
import sys

if sys.platform == "win32":
    _base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    _runtime_dir = os.path.join(_base, "pythonnet", "runtime")
    
    # 1. 强制指定使用 .NET Framework 运行时
    os.environ["PYTHONNET_RUNTIME"] = "netfx"

    # 2. 定位 Python.Runtime.dll 并尝试解除 MOTW 锁定
    _runtime_dll = os.path.join(_runtime_dir, "Python.Runtime.dll")
    
    def _unblock_file(_path):
        try:
            os.remove(f"{_path}:Zone.Identifier")
        except OSError:
            pass

    if os.path.isfile(_runtime_dll):
        _unblock_file(_runtime_dll)

    # 3. 将 runtime 目录加入 DLL 搜索路径
    _search_dirs = [_base, _runtime_dir]
    os.environ["PATH"] = os.pathsep.join(
        _search_dirs + [p for p in os.environ.get("PATH", "").split(os.pathsep) if p and p not in _search_dirs]
    )
    
    # 4. 使用 Python 3.8+ 的 add_dll_directory 注册目录
    if hasattr(os, "add_dll_directory"):
        for _path in _search_dirs:
            try:
                os.add_dll_directory(_path)
            except (FileNotFoundError, OSError):
                pass