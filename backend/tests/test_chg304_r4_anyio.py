"""Actual subprocess lifecycle regression; no patching, fake clock or fake worker."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

import anyio
from anyio import to_process
from chg304_r4_process_work import announce_and_wait, exit_worker, noisy_identity, raise_error


def gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.worker_pids = []

    def tearDown(self):
        self.assert_reaped(self.worker_pids)
        print(json.dumps({"test": self.id(), "owned_worker_pids": self.worker_pids,
                          "all_owned_workers_reaped": True}), flush=True)

    def run_async(self, function):
        # Observe genuine event-loop callback failures, which unittest otherwise
        # only prints while incorrectly returning OK. Do not suppress the error.
        errors = []
        def loop_factory():
            loop = asyncio.new_event_loop()
            def record(loop, context):
                errors.append(type(context.get("exception")).__name__)
                loop.default_exception_handler(context)
            loop.set_exception_handler(record)
            return loop
        result = anyio.run(function, backend_options={"loop_factory": loop_factory})
        self.assertEqual(errors, [], "real process-pool shutdown callback failed")
        return result

    def assert_reaped(self, pids):
        deadline = time.monotonic() + 3
        while not all(gone(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(all(gone(pid) for pid in pids), "owned_worker_survived")

    def test_pool_reuse_exception_stdout_protocol_and_shutdown(self):
        pids = self.worker_pids
        before = os.fstat(2)
        async def main():
            with anyio.fail_after(8):
                for _ in range(5):
                    pid, count = await to_process.run_sync(noisy_identity)
                    pids.append(pid)
                    self.assertEqual(count, 1024 * 1024)
                with self.assertRaisesRegex(ValueError, "chg304-r4-worker-exception"):
                    await to_process.run_sync(raise_error)
                pid, _ = await to_process.run_sync(noisy_identity)
                self.assertEqual(pid, pids[0])
        self.run_async(main)
        self.assertEqual(len(set(pids)), 1)
        after = os.fstat(2)
        self.assertEqual((before.st_dev, before.st_ino, before.st_mode), (after.st_dev, after.st_ino, after.st_mode))
        self.assert_reaped(pids)

    def test_cancel_kills_and_reaps_then_replaces_worker(self):
        pids = self.worker_pids
        with tempfile.TemporaryDirectory(prefix="chg304-r4-cancel-") as directory:
            marker = Path(directory) / "owned-pid"
            async def main():
                with anyio.fail_after(8):
                    async with anyio.create_task_group() as tasks:
                        async def work():
                            await to_process.run_sync(announce_and_wait, str(marker), cancellable=True)
                        tasks.start_soon(work)
                        while not marker.exists():
                            await anyio.sleep(0.01)
                        pids.append(int(marker.read_text()))
                        tasks.cancel_scope.cancel()
                    self.assertTrue(gone(pids[0]), "cancelled_worker_not_reaped")
                    pid, count = await to_process.run_sync(noisy_identity)
                    pids.append(pid)
                    self.assertNotEqual(pids[0], pid)
                    self.assertEqual(count, 1024 * 1024)
            self.run_async(main)
        self.assert_reaped(pids)
        self.assertFalse(Path(directory).exists())

    def test_unexpected_exit_is_reported_and_pool_recovers(self):
        pids = self.worker_pids
        async def main():
            with anyio.fail_after(8):
                pid, _ = await to_process.run_sync(noisy_identity)
                pids.append(pid)
                with self.assertRaises(anyio.BrokenWorkerProcess):
                    await to_process.run_sync(exit_worker)
                self.assertTrue(gone(pid))
                replacement, count = await to_process.run_sync(noisy_identity)
                pids.append(replacement)
                self.assertNotEqual(pid, replacement)
                self.assertEqual(count, 1024 * 1024)
        self.run_async(main)
        self.assert_reaped(pids)

    def test_general_subprocess_stderr_and_parent_stderr_unchanged(self):
        async def main():
            with anyio.fail_after(5):
                result = await anyio.run_process([sys.executable, "-c", "import os;os.write(1,b'out');os.write(2,b'err')"])
                self.assertEqual(result.stdout, b"out")
                self.assertEqual(result.stderr, b"err")
        self.run_async(main)
        os.write(2, b"CHG304_R4_PARENT_STDERR_INTACT\n")


if __name__ == "__main__":
    unittest.main()
