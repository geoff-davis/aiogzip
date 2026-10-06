"""The parked-call witness: what the gated executor records for a native call.

C0 and b1 submit aiofiles' ``partial``; the candidate submits a
``_NativeSourceCall``. Anything else must record no bytes, so the
writer-abort predicate fails closed.
"""

import asyncio
import concurrent.futures
import functools

import aiofiles
from interpreter import Gate, GatedExecutor, _native_parked

from aiogzip._source_io import _NativeSourceCall


class _Recording(concurrent.futures.ThreadPoolExecutor):
    def __init__(self):
        super().__init__(max_workers=1)
        self.submitted = []

    def submit(self, fn, /, *args, **kwargs):
        self.submitted.append(fn)
        return super().submit(fn, *args, **kwargs)


async def test_aiofiles_partial_records_method_and_bytes(tmp_path):
    executor = _Recording()
    async with aiofiles.open(tmp_path / "out", "wb", executor=executor) as f:
        await f.write(b"payload")
        await f.flush()
    executor.shutdown()
    witnesses = [_native_parked(fn) for fn in executor.submitted]
    assert {"via": "native", "method": "write", "bytes": b"payload"} in witnesses
    assert {"via": "native", "method": "flush", "bytes": None} in witnesses


async def test_native_source_call_records_method_and_bytes():
    loop = asyncio.get_running_loop()
    call = _NativeSourceCall(object(), "write", (b"payload",), loop)
    assert _native_parked(call) == {
        "via": "native",
        "method": "write",
        "bytes": b"payload",
    }
    flush = _NativeSourceCall(object(), "flush", (), loop)
    assert _native_parked(flush) == {"via": "native", "method": "flush", "bytes": None}


def test_unknown_callable_records_no_bytes():
    assert _native_parked(lambda: None) == {
        "via": "native",
        "method": None,
        "bytes": None,
    }
    # A partial whose first argument is not bytes still records no bytes.
    assert _native_parked(functools.partial(print, "text"))["bytes"] is None


async def test_gated_executor_records_the_parked_native_write(tmp_path):
    loop = asyncio.get_running_loop()
    gate = Gate()
    executor = GatedExecutor(gate, loop)
    async with aiofiles.open(tmp_path / "out", "wb", executor=executor) as f:
        gate.arm()
        write = asyncio.create_task(f.write(b"parked"))
        await asyncio.wait_for(gate.entered.wait(), 5)
        assert gate.parked == {"via": "native", "method": "write", "bytes": b"parked"}
        gate.release()
        await write
    executor.shutdown()
    assert (tmp_path / "out").read_bytes() == b"parked"


def test_a_named_function_stands_for_its_own_method():
    # The candidate opens by submitting sync_open itself; aiofiles (b1, C0)
    # submits a partial of it. Both must record the same parked method.
    sync_open = aiofiles.threadpool.sync_open
    direct = _native_parked(sync_open)
    wrapped = _native_parked(functools.partial(sync_open, "path", "rb"))
    assert direct == wrapped == {"via": "native", "method": "open", "bytes": None}


async def test_candidate_native_open_parks_as_open(tmp_path):
    import aiogzip

    (tmp_path / "f.gz").write_bytes(b"")
    loop = asyncio.get_running_loop()
    executor = _Recording()
    loop.set_default_executor(executor)
    handle = aiogzip.AsyncGzipBinaryFile(tmp_path / "f.gz", "rb")
    await handle.open()
    await handle.close()
    methods = [_native_parked(fn)["method"] for fn in executor.submitted]
    assert methods[0] == "open"
