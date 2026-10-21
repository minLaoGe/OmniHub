"""Open Windows folders through the Shell namespace, without explorer CLI handoff."""
from pathlib import Path
import os


def open_windows_path(path):
    import ctypes
    from ctypes import wintypes

    target = Path(os.path.expandvars(str(path).strip().strip('"'))).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"路径不存在：{target}")
    if target.is_dir():
        os.startfile(str(target), "explore")
        return str(target)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32")
    parse = shell.SHParseDisplayName
    parse.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    parse.restype = ctypes.c_long
    show = shell.SHOpenFolderAndSelectItems
    show.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD]
    show.restype = ctypes.c_long
    last = shell.ILFindLastID
    last.argtypes = [ctypes.c_void_p]
    last.restype = ctypes.c_void_p
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    initialized = ole.CoInitializeEx(None, 2)
    folder_id, file_id = ctypes.c_void_p(), ctypes.c_void_p()

    def check(result, operation):
        if result == -2147467260:
            raise OSError("Windows 资源管理器中止了打开请求，请在任务管理器重启 Windows 资源管理器后重试")
        if result < 0:
            raise OSError(f"{operation}失败，Windows 错误 0x{result & 0xffffffff:08X}")

    try:
        if initialized < 0 and initialized != -2147417850:
            check(initialized, "初始化系统文件管理器")
        folder = target.parent if target.is_file() else target
        check(parse(str(folder), None, ctypes.byref(folder_id), 0, None), "解析目录")
        if target.is_file():
            check(parse(str(target), None, ctypes.byref(file_id), 0, None), "解析文件")
            children = (ctypes.c_void_p * 1)(last(file_id))
            check(show(folder_id, 1, children, 0), "打开目录并选中文件")
        else:
            check(show(folder_id, 0, None, 0), "打开目录")
        return str(folder)
    finally:
        if file_id.value:
            ole.CoTaskMemFree(file_id)
        if folder_id.value:
            ole.CoTaskMemFree(folder_id)
        if initialized >= 0:
            ole.CoUninitialize()
