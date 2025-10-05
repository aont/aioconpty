#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
async_conpty.py
汎用的な asyncio ConPTY ラッパー

- ConPTY(擬似コンソール)の生成/破棄/サイズ変更
- asyncio.StreamReader/StreamWriter 経由での非同期入出力
- CreateProcessW + STARTUPINFOEX で ConPTY に子プロセスを接続
- 可能な限り元コードの仕様/挙動を踏襲

要件: Windows 10 1809+ / Python 3.8+
"""

import os
import sys
import ctypes
import ctypes.wintypes
import asyncio
import _winapi
import asyncio.windows_utils

# ===== 定数 =====
FILE_SHARE_READ   = 0x00000001
FILE_SHARE_WRITE  = 0x00000002
FILE_ATTRIBUTE_NORMAL = 0x00000080

STD_INPUT_HANDLE  = -10
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE  = -12

INVALID_HANDLE_VALUE = ctypes.wintypes.HANDLE(-1).value

S_OK = 0

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016

ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
STARTF_USESTDHANDLES = 0x0100

INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0x00000000

GENERIC_READ  = _winapi.GENERIC_READ
GENERIC_WRITE = _winapi.GENERIC_WRITE
OPEN_EXISTING = _winapi.OPEN_EXISTING

# ===== 型エイリアス =====
PVOID  = ctypes.wintypes.LPVOID
SIZE_T = ctypes.c_size_t
HPCON  = ctypes.wintypes.HANDLE


# ===== エラーチェック =====
def _errcheck_bool(value, func, args):
    if not value:
        raise ctypes.WinError()
    return args

def _errcheck_handle(value, func, args):
    if value == 0 or value == INVALID_HANDLE_VALUE:
        raise ctypes.WinError()
    return value


# ===== 構造体 =====
class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.wintypes.SHORT),
                ("Y", ctypes.wintypes.SHORT)]

class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", ctypes.wintypes.DWORD),
                ("lpReserved", ctypes.c_void_p),
                ("lpDesktop", ctypes.c_void_p),
                ("lpTitle", ctypes.c_void_p),
                ("dwX", ctypes.wintypes.DWORD),
                ("dwY", ctypes.wintypes.DWORD),
                ("dwXSize", ctypes.wintypes.DWORD),
                ("dwYSize", ctypes.wintypes.DWORD),
                ("dwXCountChars", ctypes.wintypes.DWORD),
                ("dwYCountChars", ctypes.wintypes.DWORD),
                ("dwFillAttribute", ctypes.wintypes.DWORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("wShowWindow", ctypes.wintypes.WORD),
                ("cbReserved2", ctypes.wintypes.WORD),
                ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", ctypes.wintypes.HANDLE),
                ("hStdOutput", ctypes.wintypes.HANDLE),
                ("hStdError", ctypes.wintypes.HANDLE)]

class STARTUPINFOEX(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFO),
                ("lpAttributeList", ctypes.c_void_p)]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", ctypes.wintypes.HANDLE),
                ("hThread", ctypes.wintypes.HANDLE),
                ("dwProcessId", ctypes.wintypes.DWORD),
                ("dwThreadId", ctypes.wintypes.DWORD)]

class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", ctypes.wintypes.WORD),
        ("srWindow", ctypes.wintypes.SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    ]


# ===== WinAPI =====
kernel32 = ctypes.windll.kernel32

SetLastError = kernel32.SetLastError
SetLastError.argtypes = [ctypes.wintypes.DWORD]

GetStdHandle = kernel32.GetStdHandle
GetStdHandle.argtypes = [ctypes.wintypes.DWORD]
GetStdHandle.restype  = ctypes.wintypes.HANDLE

CreateFileW = kernel32.CreateFileW
CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
                        ctypes.c_void_p, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
                        ctypes.wintypes.HANDLE]
CreateFileW.restype  = ctypes.wintypes.HANDLE
CreateFileW.errcheck = _errcheck_handle

GetConsoleMode = kernel32.GetConsoleMode
GetConsoleMode.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD)]
GetConsoleMode.restype  = ctypes.wintypes.BOOL

SetConsoleMode = kernel32.SetConsoleMode
SetConsoleMode.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
SetConsoleMode.restype  = ctypes.wintypes.BOOL
SetConsoleMode.errcheck = _errcheck_bool

GetConsoleScreenBufferInfo = kernel32.GetConsoleScreenBufferInfo
GetConsoleScreenBufferInfo.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO)]
GetConsoleScreenBufferInfo.restype  = ctypes.wintypes.BOOL
GetConsoleScreenBufferInfo.errcheck = _errcheck_bool

CreatePseudoConsole = kernel32.CreatePseudoConsole
CreatePseudoConsole.argtypes = [COORD, ctypes.wintypes.HANDLE, ctypes.wintypes.HANDLE,
                                ctypes.wintypes.DWORD, ctypes.POINTER(HPCON)]
CreatePseudoConsole.restype  = ctypes.HRESULT

ResizePseudoConsole = kernel32.ResizePseudoConsole
ResizePseudoConsole.argtypes = [HPCON, COORD]
ResizePseudoConsole.restype  = ctypes.HRESULT

ClosePseudoConsole = kernel32.ClosePseudoConsole
ClosePseudoConsole.argtypes = [HPCON]

InitializeProcThreadAttributeList = kernel32.InitializeProcThreadAttributeList
InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, ctypes.wintypes.DWORD,
                                              ctypes.wintypes.DWORD, ctypes.POINTER(SIZE_T)]
InitializeProcThreadAttributeList.restype  = ctypes.wintypes.BOOL

UpdateProcThreadAttribute = kernel32.UpdateProcThreadAttribute
UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, ctypes.wintypes.DWORD, SIZE_T,
                                      ctypes.c_void_p, SIZE_T, ctypes.c_void_p,
                                      ctypes.POINTER(SIZE_T)]
UpdateProcThreadAttribute.restype  = ctypes.wintypes.BOOL

DeleteProcThreadAttributeList = kernel32.DeleteProcThreadAttributeList
DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]

CreateProcessW = kernel32.CreateProcessW
CreateProcessW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p,
                           ctypes.wintypes.BOOL, ctypes.wintypes.DWORD, ctypes.c_void_p,
                           ctypes.c_wchar_p, ctypes.POINTER(STARTUPINFO),
                           ctypes.POINTER(PROCESS_INFORMATION)]
CreateProcessW.restype  = ctypes.wintypes.BOOL
CreateProcessW.errcheck = _errcheck_bool

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
CloseHandle.restype  = ctypes.wintypes.BOOL
CloseHandle.errcheck = _errcheck_bool

WaitForSingleObject = kernel32.WaitForSingleObject
WaitForSingleObject.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
WaitForSingleObject.restype  = ctypes.wintypes.DWORD

GetExitCodeProcess = kernel32.GetExitCodeProcess
GetExitCodeProcess.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD)]
GetExitCodeProcess.restype  = ctypes.wintypes.BOOL
GetExitCodeProcess.errcheck = _errcheck_bool


# ===== ユーティリティ =====
def _enable_host_console_vt_if_possible():
    """
    親側のコンソールで VT シーケンスを有効化（なくても動くが、親側でのカラー表示などに便利）
    IDE などから起動していてコンソールがない場合は失敗しても握りつぶす。
    """
    try:
        h_console = CreateFileW("CONOUT$", GENERIC_READ | GENERIC_WRITE,
                                FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
        mode = ctypes.wintypes.DWORD(0)
        if GetConsoleMode(h_console, ctypes.byref(mode)):
            SetConsoleMode(h_console, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        CloseHandle(h_console)
    except Exception:
        pass  # 非コンソール環境や古い Windows など


def _get_host_console_size_fallback(cols=80, rows=25):
    """
    親側コンソールのサイズを取得。失敗したら既定値を返す。
    """
    try:
        h_console = CreateFileW("CONOUT$", GENERIC_READ | GENERIC_WRITE,
                                FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
        csbi = CONSOLE_SCREEN_BUFFER_INFO()
        GetConsoleScreenBufferInfo(h_console, ctypes.byref(csbi))
        CloseHandle(h_console)
        x = csbi.srWindow.Right - csbi.srWindow.Left + 1
        y = csbi.srWindow.Bottom - csbi.srWindow.Top + 1
        return x, y
    except Exception:
        return cols, rows


def _list2cmdline(cmd):
    """['ping', 'localhost'] -> 'ping localhost' / 文字列ならそのまま"""
    if isinstance(cmd, (list, tuple)):
        import subprocess
        return subprocess.list2cmdline(list(cmd))
    return str(cmd)


def _make_stream_writer(transport, protocol):
    """
    Python バージョン差異を吸収して StreamWriter を生成
    """
    try:
        return asyncio.StreamWriter(transport, protocol, None, asyncio.get_running_loop())
    except TypeError:
        # 3.12 以降など
        return asyncio.StreamWriter(transport, protocol)


# ===== メインクラス =====
class AsyncConPTY:
    """
    ConPTY(擬似コンソール)を asyncio で扱う薄いラッパー。

    使い方:
        async with AsyncConPTY(cols=120, rows=30) as pty:
            await pty.ensure_utf8_codepage()   # 任意（元コード互換）
            proc = await pty.spawn("ping localhost")
            async for chunk in pty.read_chunks():
                sys.stdout.buffer.write(chunk)
            rc = await proc.wait()
    """

    def __init__(self, cols: int = None, rows: int = None):
        if sys.platform != "win32":
            raise RuntimeError("AsyncConPTY は Windows 専用です。")
        _enable_host_console_vt_if_possible()

        if cols is None or rows is None:
            cols2, rows2 = _get_host_console_size_fallback()
            cols = cols or cols2
            rows = rows or rows2

        self._cols = int(cols)
        self._rows = int(rows)

        self.hPC = HPCON()
        self._hPipeIn = None   # ConPTY->親（親が読む）
        self._hPipeOut = None  # 親->ConPTY（親が書く）

        self._reader = None    # asyncio.StreamReader
        self._writer = None    # asyncio.StreamWriter

        self._attr_mem = None  # attribute list backing buffer
        self._si_ex = None     # STARTUPINFOEX

        self._loop = None
        self._transport_read = None
        self._transport_write = None

        self._closed = False

    # ---- 初期化/破棄 ----
    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def open(self):
        if self._reader or self._writer:
            return  # 既にオープン済

        self._loop = asyncio.get_running_loop()

        # (1) 親側が読むパイプ (ConPTY の出力)
        #     overlapped: 親(read)=True / ConPTY(write)=False
        hPipeIn, hPipePTYOut = asyncio.windows_utils.pipe(overlapped=(True, False), duplex=False)
        # (2) 親側が書くパイプ (ConPTY の入力)
        #     overlapped: ConPTY(read)=False / 親(write)=True
        hPipePTYIn, hPipeOut = asyncio.windows_utils.pipe(overlapped=(False, True), duplex=False)

        # ConPTY 生成
        size = COORD(self._cols, self._rows)
        hr = CreatePseudoConsole(size, hPipePTYIn, hPipePTYOut, 0, ctypes.byref(self.hPC))
        if hr != S_OK:
            # 後片付け
            CloseHandle(hPipePTYIn)
            CloseHandle(hPipePTYOut)
            CloseHandle(hPipeIn)
            CloseHandle(hPipeOut)
            raise OSError(f"CreatePseudoConsole failed: HRESULT=0x{hr:08X}")

        # ConPTY 側のパイプ終端は不要なのでクローズ
        CloseHandle(hPipePTYIn)
        CloseHandle(hPipePTYOut)

        self._hPipeIn = hPipeIn
        self._hPipeOut = hPipeOut

        # asyncio のパイプハンドルへ
        pipe_in_ph = asyncio.windows_utils.PipeHandle(self._hPipeIn)
        pipe_out_ph = asyncio.windows_utils.PipeHandle(self._hPipeOut)

        # 重要: PipeHandle に所有権を渡したため、ここで内部保持を破棄する
        # こうすることで二重 CloseHandle を防ぐ（PipeHandle.__del__ が CloseHandle を呼ぶ）
        self._hPipeIn = None
        self._hPipeOut = None

        # Reader のセットアップ（通常の connect_read_pipe を使う）
        reader = asyncio.StreamReader()
        proto_r = asyncio.StreamReaderProtocol(reader)
        transport_r, _ = await self._loop.connect_read_pipe(lambda: proto_r, pipe_in_ph)

        # Writer 用プロトコル: FlowControlMixin を先に継承して MRO を安定させる
        class _WriteProto(asyncio.streams.FlowControlMixin, asyncio.Protocol):
            def __init__(self):
                # FlowControlMixin.__init__ のシグネチャは Python バージョンで異なるため安全に初期化
                try:
                    asyncio.streams.FlowControlMixin.__init__(self, loop=asyncio.get_running_loop())
                except TypeError:
                    try:
                        asyncio.streams.FlowControlMixin.__init__(self)
                    except Exception:
                        pass

        proto_w = _WriteProto()

        # ---- ここがポイント ----
        # connect_write_pipe() が内部でパイプを読み取りしようとして PermissionError を出す環境があるため、
        # 元スクリプトで使っていたように Proactor の内部クラスで書き込みトランスポートを直接作る。
        # 互換のために proactor_events の非公開クラスを使う（Python の実装依存）。
        from asyncio import proactor_events
        # _ProactorBaseWritePipeTransport の呼び出しシグネチャはバージョン差があるため
        # (loop, sock, protocol, waiter, extra) の順で渡す。waiter は None。
        waiter = None
        transport_w = proactor_events._ProactorBaseWritePipeTransport(self._loop, pipe_out_ph, proto_w, waiter, None)

        # StreamWriter を作る（バージョン差を吸収）
        writer = _make_stream_writer(transport_w, proto_w)

        # 保存
        self._reader = reader
        self._writer = writer
        self._transport_read = transport_r
        self._transport_write = transport_w

        # STARTUPINFOEX を構築して ConPTY を属性にアタッチ
        self._si_ex = STARTUPINFOEX()
        self._si_ex.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEX)

        # InitializeProcThreadAttributeList(第一次呼び出し: サイズ取得)
        size_bytes = SIZE_T(0)
        if not InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size_bytes)):
            # ここは必ずエラー 122 (ERROR_INSUFFICIENT_BUFFER) になる想定
            # なので明示的にエラーをクリア
            SetLastError(0)

        # バッファ確保
        mem = (ctypes.c_char * size_bytes.value)()
        self._attr_mem = mem
        self._si_ex.lpAttributeList = ctypes.cast(mem, ctypes.c_void_p)

        ok = InitializeProcThreadAttributeList(self._si_ex.lpAttributeList, 1, 0, ctypes.byref(size_bytes))
        if not ok:
            raise ctypes.WinError()

        # 擬似コンソール属性を設定
        ok = UpdateProcThreadAttribute(
            self._si_ex.lpAttributeList,
            0,
            PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
            self.hPC, ctypes.sizeof(self.hPC),
            None, None
        )
        if not ok:
            raise ctypes.WinError()

    async def close(self):
        if self._closed:
            return

        # transports -> close & wait_closed() を待つ (存在すれば)
        try:
            if self._transport_write is not None:
                try:
                    self._transport_write.close()
                    wait_closed = getattr(self._transport_write, "wait_closed", None)
                    if wait_closed is not None:
                        try:
                            await asyncio.wait_for(wait_closed(), timeout=1.0)
                        except asyncio.TimeoutError:
                            pass
                except Exception:
                    pass
                finally:
                    self._transport_write = None
        except Exception:
            pass

        try:
            if self._transport_read is not None:
                try:
                    self._transport_read.close()
                    wait_closed = getattr(self._transport_read, "wait_closed", None)
                    if wait_closed is not None:
                        try:
                            await asyncio.wait_for(wait_closed(), timeout=1.0)
                        except asyncio.TimeoutError:
                            pass
                except Exception:
                    pass
                finally:
                    self._transport_read = None
        except Exception:
            pass

        # Stream とハンドル参照を切る
        self._writer = None
        self._reader = None

        # パイプハンドル (もしまだ内部に残っていれば閉じる)
        # ただし PipeHandle に渡していれば self._hPipeOut/_hPipeIn は None になっているはず
        for attr_name in ("_hPipeOut", "_hPipeIn"):
            h = getattr(self, attr_name, None)
            if h is not None:
                try:
                    CloseHandle(h)
                except Exception:
                    pass
                finally:
                    setattr(self, attr_name, None)

        # 属性リスト削除（存在すれば）
        try:
            if self._si_ex and self._si_ex.lpAttributeList:
                try:
                    DeleteProcThreadAttributeList(self._si_ex.lpAttributeList)
                except Exception:
                    pass
                self._si_ex = None
                self._attr_mem = None
        except Exception:
            pass

        # ConPTY を閉じる
        try:
            if self.hPC:
                try:
                    ClosePseudoConsole(self.hPC)
                except Exception:
                    pass
                self.hPC = HPCON()
        except Exception:
            pass

        self._closed = True

    # ---- I/O ----
    @property
    def reader(self) -> asyncio.StreamReader:
        return self._reader

    @property
    def writer(self) -> asyncio.StreamWriter:
        return self._writer

    async def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return await self._reader.read()
        return await self._reader.read(n)

    async def readline(self) -> bytes:
        return await self._reader.readline()

    async def read_chunks(self, chunk_size: int = 4096):
        """
        非同期ジェネレータ: 出力が EOF になるまで chunk を返す
        """
        while True:
            data = await self._reader.read(chunk_size)
            if not data:
                break
            yield data

    async def write(self, data: bytes):
        """
        親->ConPTY へ書き込み
        """
        if isinstance(data, str):
            data = data.encode("utf-8", "replace")
        self._writer.write(data)
        await self._writer.drain()

    async def writeline(self, line: str):
        await self.write(line + "\r\n")

    # ---- サイズ変更 ----
    def resize(self, cols: int, rows: int):
        size = COORD(int(cols), int(rows))
        hr = ResizePseudoConsole(self.hPC, size)
        if hr != S_OK:
            raise OSError(f"ResizePseudoConsole failed: HRESULT=0x{hr:08X}")
        self._cols, self._rows = int(cols), int(rows)

    # ---- プロセス起動 ----
    async def ensure_utf8_codepage(self, codepage: int = 65001):
        """
        元コード互換: 起動直後に chcp.com でコードページを UTF-8 にする（任意）
        """
        await self.spawn(f"chcp.com {codepage}", wait_thread=True, close_thread=True, quiet=True)

    async def spawn(self, cmd, *, cwd: str = None, wait_thread: bool = True,
                    close_thread: bool = True, quiet: bool = False):
        """
        ConPTY に接続されたプロセスを起動。

        Parameters
        ----------
        cmd : str | list[str]
            実行コマンド（'ping localhost' か ['ping', 'localhost']）
        cwd : str | None
            作業ディレクトリ
        wait_thread : bool
            生成スレッド(hThread)のシグナルを待つ（起動安定化のため推奨）
        close_thread : bool
            待機後に hThread を閉じる
        quiet : bool
            失敗時の詳細を出さない

        Returns
        -------
        AsyncConPTYProcess
            wait() でプロセス終了待ちができるハンドルラッパ
        """
        if not self._si_ex:
            raise RuntimeError("ConPTY 未初期化。まず open()/__aenter__() を呼んでください。")

        lp_pi = PROCESS_INFORMATION()
        # lpCommandLine は書き換えられる可能性があるため可変バッファを渡す
        cmdline = _list2cmdline(cmd)
        buf = ctypes.create_unicode_buffer(cmdline)

        try:
            CreateProcessW(
                None, buf,
                None, None,
                False,
                EXTENDED_STARTUPINFO_PRESENT,
                None,
                cwd,
                ctypes.byref(self._si_ex.StartupInfo),
                ctypes.byref(lp_pi)
            )
        except Exception:
            if quiet:
                # 失敗しても呼び出し側に投げない設定
                return AsyncConPTYProcess(None, None, 0)
            raise

        # 起動スレッドのシグナルを待つ（短時間）
        if wait_thread:
            # Proactor の wait_for_handle（非公開属性）を使うとノンブロッキングで待てる
            loop = self._loop or asyncio.get_running_loop()
            proactor = getattr(loop, "_proactor", None)
            if proactor is not None:
                await proactor.wait_for_handle(int(lp_pi.hThread), None)
            else:
                # 念のためブロッキング API で最低限の同期
                WaitForSingleObject(lp_pi.hThread, 2000)

        if close_thread and lp_pi.hThread:
            try:
                CloseHandle(lp_pi.hThread)
            except Exception:
                pass
            lp_pi.hThread = None

        return AsyncConPTYProcess(lp_pi.hProcess, lp_pi.dwProcessId, exit_code=None)


class AsyncConPTYProcess:
    """
    ConPTY にぶら下がっている子プロセスの簡易ハンドラ
    """
    def __init__(self, hProcess, pid: int, exit_code: int | None):
        self.hProcess = hProcess
        self.pid = int(pid) if pid else 0
        self._exit_code = exit_code

    async def wait(self, timeout: float | None = None) -> int:
        """
        プロセス終了待ち。戻り値は return code
        """
        if not self.hProcess:
            return 0
        loop = asyncio.get_running_loop()
        proactor = getattr(loop, "_proactor", None)
        if proactor is not None:
            # タイムアウト付き待機（ms 指定）
            if timeout is None:
                await proactor.wait_for_handle(int(self.hProcess), None)
            else:
                try:
                    await asyncio.wait_for(proactor.wait_for_handle(int(self.hProcess), None), timeout)
                except asyncio.TimeoutError:
                    return None  # タイムアウト
        else:
            # 同期版フォールバック
            ms = INFINITE if timeout is None else int(timeout * 1000)
            WaitForSingleObject(self.hProcess, ms)

        # 返り値取得
        code = ctypes.wintypes.DWORD(0)
        GetExitCodeProcess(self.hProcess, ctypes.byref(code))
        self._exit_code = int(code.value)
        return self._exit_code

    def poll(self) -> int | None:
        """
        非同期でなく現在の終了コードを返す。未終了なら None。
        """
        if not self.hProcess:
            return 0
        code = ctypes.wintypes.DWORD(0)
        GetExitCodeProcess(self.hProcess, ctypes.byref(code))
        if code.value == 259:  # STILL_ACTIVE
            return None
        return int(code.value)

    def close_handle(self):
        try:
            if self.hProcess:
                CloseHandle(self.hProcess)
        finally:
            self.hProcess = None


# ===== サンプル（スクリプト実行時） =====
async def _demo(argv: list[str]) -> int:
    """
    例:
        python async_conpty.py             -> ping localhost を実行
        python async_conpty.py cmd /c dir -> 任意コマンド
    """
    cmd = argv or ["ping", "localhost"]
    async with AsyncConPTY() as pty:
        # 元コード互換: 文字化け防止に UTF-8 に変更（任意）
        await pty.ensure_utf8_codepage()

        proc = await pty.spawn(cmd)

        # 出力を行単位で受け取り標準出力へ中継
        while True:
            line = await pty.readline()
            if not line:
                break
            # （必要ならエスケープ処理を入れる）
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()

        rc = await proc.wait()
        proc.close_handle()
        return rc if rc is not None else 1


def main():
    if sys.platform != "win32":
        print("Windows 上でのみ動作します。", file=sys.stderr)
        sys.exit(1)
    try:
        rc = asyncio.run(_demo(sys.argv[1:]))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
