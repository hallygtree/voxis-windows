import threading
import time

from laris.orb_state import OrbStateManager


def test_orb_state_initial_snapshot():
    state = OrbStateManager()
    snapshot = state.snapshot()
    assert snapshot.visible is False
    assert snapshot.ready is False
    assert snapshot.mode is None
    assert snapshot.serial >= 1


def test_orb_state_show_sets_visible_and_mode():
    state = OrbStateManager()
    initial_serial = state.snapshot().serial
    state.show("dictate")
    snapshot = state.snapshot()
    assert snapshot.visible is True
    assert snapshot.mode == "dictate"
    assert snapshot.serial == initial_serial + 1


def test_orb_state_show_same_mode_no_increment():
    state = OrbStateManager()
    state.show("dictate")
    serial = state.snapshot().serial
    state.show("dictate")
    assert state.snapshot().serial == serial  # No change


def test_orb_state_hide_clears_visible_and_mode():
    state = OrbStateManager()
    state.show("dictate")
    initial_serial = state.snapshot().serial
    state.hide()
    snapshot = state.snapshot()
    assert snapshot.visible is False
    assert snapshot.mode is None
    assert snapshot.serial == initial_serial + 1


def test_orb_state_hide_when_already_hidden_no_increment():
    state = OrbStateManager()
    state.hide()
    serial = state.snapshot().serial
    state.hide()
    assert state.snapshot().serial == serial  # No change


def test_orb_state_set_ready_true():
    state = OrbStateManager()
    initial_serial = state.snapshot().serial
    state.set_ready(True)
    snapshot = state.snapshot()
    assert snapshot.ready is True
    assert snapshot.serial == initial_serial + 1


def test_orb_state_set_ready_same_value_no_increment():
    state = OrbStateManager()
    state.set_ready(True)
    serial = state.snapshot().serial
    state.set_ready(True)
    assert state.snapshot().serial == serial  # No change


def test_orb_state_wait_for_change_immediate_if_different():
    state = OrbStateManager()
    state.show("dictate")
    snapshot = state.snapshot()
    result = state.wait_for_change(0, timeout=0.1)
    assert result.serial == snapshot.serial
    assert result.visible is True


def test_orb_state_wait_for_change_timeout():
    state = OrbStateManager()
    snapshot = state.snapshot()
    start = time.monotonic()
    result = state.wait_for_change(snapshot.serial, timeout=0.2)
    elapsed = time.monotonic() - start
    assert result.serial == snapshot.serial  # No change
    assert elapsed >= 0.2


def test_orb_state_wait_for_change_woken_by_show():
    state = OrbStateManager()
    initial_snapshot = state.snapshot()

    def delayed_show():
        time.sleep(0.1)
        state.show("transcribing")

    thread = threading.Thread(target=delayed_show)
    thread.start()

    start = time.monotonic()
    result = state.wait_for_change(initial_snapshot.serial, timeout=1.0)
    elapsed = time.monotonic() - start

    thread.join()

    assert result.serial > initial_snapshot.serial
    assert result.visible is True
    assert result.mode == "transcribing"
    assert elapsed < 0.5  # Should wake in ~0.1s, not timeout after 1.0s


def test_orb_state_concurrent_show_hide():
    state = OrbStateManager()
    results = []

    def toggle():
        for _ in range(5):
            state.show("dictate")
            state.hide()
            time.sleep(0.01)

    threads = [threading.Thread(target=toggle) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # No crashes, and final state should be valid
    snapshot = state.snapshot()
    assert snapshot.serial >= 1
