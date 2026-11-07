"""Run all four unmodified lifecycle assertions with the real installed uvloop."""
import unittest
import anyio
import uvloop
from test_chg304_r4_anyio import Lifecycle


class UvloopLifecycle(Lifecycle):
    def run_async(self, function):
        errors = []
        def loop_factory():
            loop = uvloop.new_event_loop()
            def record(loop, context):
                errors.append(type(context.get("exception")).__name__)
                loop.default_exception_handler(context)
            loop.set_exception_handler(record)
            return loop
        result = anyio.run(function, backend_options={"loop_factory": loop_factory})
        self.assertEqual(errors, [], "real uvloop process shutdown callback failed")
        return result


if __name__ == "__main__":
    unittest.main(defaultTest="UvloopLifecycle")
