"""The replay must not run while any key (Shift!) is physically held."""
import asyncio

from relayout.input_listener import wait_for_quiet


def run(coro):
    return asyncio.run(coro)


def test_waits_for_shift_release_then_proceeds():
    async def scenario():
        held = {"KEY_LEFTSHIFT"}
        task = asyncio.create_task(
            wait_for_quiet(held, lambda: 0, 0, max_wait=0.5, settle=0.005)
        )
        await asyncio.sleep(0.05)
        assert not task.done()      # still held: must not fire yet
        held.clear()                # the second tap ends
        return await task
    assert run(scenario()) is True


def test_drops_when_shift_never_released():
    held = {"KEY_LEFTSHIFT"}
    assert run(wait_for_quiet(held, lambda: 0, 0, max_wait=0.05, settle=0.005)) is False


def test_drops_when_user_types_meanwhile():
    async def scenario():
        epoch = [0]
        held = {"KEY_LEFTSHIFT"}
        task = asyncio.create_task(
            wait_for_quiet(held, lambda: epoch[0], 0, max_wait=0.5, settle=0.005)
        )
        await asyncio.sleep(0.03)
        epoch[0] = 1                # another key was typed
        held.clear()
        return await task
    assert run(scenario()) is False


def test_drops_when_key_pressed_during_settle():
    async def scenario():
        held = set()
        task = asyncio.create_task(
            wait_for_quiet(held, lambda: 0, 0, max_wait=0.5, settle=0.05)
        )
        await asyncio.sleep(0.02)
        held.add("KEY_A")           # pressed while settling
        return await task
    assert run(scenario()) is False


def test_nothing_held_fires_after_settle():
    assert run(wait_for_quiet(set(), lambda: 3, 3, max_wait=0.5, settle=0.005)) is True
