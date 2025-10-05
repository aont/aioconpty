"""Example script demonstrating how to run a command through AsyncConPTY."""

import sys
import asyncio

from aioconpty import AsyncConPTY

async def run():
    # 単発コマンドで終了させたいなら cmd /c を使う
    cmd = ["cmd", "/c", "dir"]

    async with AsyncConPTY(cols=120, rows=30) as pty:
        # もし文字化け対策で chcp を入れているなら ensure_utf8_codepage() を呼ぶ
        # await pty.ensure_utf8_codepage()

        proc = await pty.spawn(cmd)

        # 子プロセスが終了するまで待ち、その後残りを全部読み切る方法（確実）
        # 先に子の終了を待つ
        rc_task = asyncio.create_task(proc.wait())

        # 同時に出力を読み続けるタスク
        async def drain_output():
            # readline ループでも良いが、最後に残るバッファを確実に取るなら read() で全部取るのが簡単
            while True:
                line = await pty.readline()
                if not line:
                    break
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()

        drain_task = asyncio.create_task(drain_output())

        rc = await rc_task  # 子プロセスの終了待ち
        # 子が終了したら writer/transport を閉じて EOF を発生させる（必要なら）
        try:
            # transport を閉じることで ConPTY に EOF を送ることがある
            if pty.writer:
                pty.writer.close()
                # writer.wait_closed はある実装でのみ存在するので安全に await する
                wait_closed = getattr(pty.writer, "wait_closed", None)
                if wait_closed:
                    await wait_closed()
        except Exception:
            pass

        # 残りの出力を読み切る（drain_task が終わるのを待つ）
        await drain_task

        print("child exit code:", rc)
        return rc

if __name__ == "__main__":
    try:
        rc = asyncio.run(run())
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)
