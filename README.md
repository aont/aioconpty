# aioconpty

`aioconpty` is an asyncio-friendly wrapper around the Windows [ConPTY](https://learn.microsoft.com/windows/console/creating-a-pseudoconsole-session) API. It provides a convenient way to spawn processes connected to a pseudo console and interact with them using familiar `asyncio` primitives.

> **Note**
> ConPTY is only available on Windows 10 build 1809 or later. The examples in this repository must be executed on a compatible Windows machine with Python 3.8+.

## Features

- Create, resize, and close ConPTY instances from Python.
- Asynchronous read/write support through `asyncio.StreamReader` and `asyncio.StreamWriter`.
- Attach new child processes to the pseudo console using `CreateProcessW` and `STARTUPINFOEX`.
- Context-manager support to ensure handles are released properly.

## Installation

The project is packaged as a standard Python distribution. To install it into your current environment, clone the repository and run:

```bash
pip install .
```

This will install the `aioconpty` package so it can be imported from any project on the machine.

## Usage

The `AsyncConPTY` class offers an asynchronous context manager for creating and working with pseudo consoles. A minimal example is provided in [`main.py`](./main.py):

```python
import asyncio
from aioconpty import AsyncConPTY

async def run():
    async with AsyncConPTY(cols=120, rows=30) as pty:
        proc = await pty.spawn(["cmd", "/c", "dir"])
        await proc.wait()

if __name__ == "__main__":
    asyncio.run(run())
```

Refer to the inline documentation within [`src/aioconpty/conpty.py`](./src/aioconpty/conpty.py) for additional details on the available methods.

## Development

To work on the project locally:

1. Create and activate a virtual environment.
2. Install the project in editable mode along with development dependencies (if any).
3. Run or adapt the example script in `main.py` to validate your changes.

Pull requests and contributions that improve the documentation, testing, or Windows compatibility are welcome.
