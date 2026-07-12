from types import SimpleNamespace


def _fake_osascript(monkeypatch, current_volume, calls):
    from laris import ducking

    def fake_run(argv, **kwargs):
        calls.append(argv[-1])
        if "get volume settings" in argv[-1]:
            return SimpleNamespace(returncode=0, stdout=f"{current_volume}\n".encode())
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(ducking.subprocess, "run", fake_run)


def test_duck_lowers_volume_and_restore_brings_it_back(monkeypatch):
    from laris.ducking import AudioDucker, DUCK_VOLUME

    calls = []
    _fake_osascript(monkeypatch, current_volume=87, calls=calls)

    ducker = AudioDucker()
    ducker.duck()
    ducker.restore()

    assert f"set volume output volume {DUCK_VOLUME}" in calls
    assert "set volume output volume 87" in calls


def test_duck_is_noop_when_volume_already_low(monkeypatch):
    from laris.ducking import AudioDucker

    calls = []
    _fake_osascript(monkeypatch, current_volume=10, calls=calls)

    ducker = AudioDucker()
    ducker.duck()
    ducker.restore()

    assert not any(c.startswith("set volume") for c in calls)


def test_duck_twice_keeps_the_original_volume(monkeypatch):
    """Re-entrant duck (hands-free start + PTT) must not save the ducked
    level as the value to restore."""
    from laris import ducking
    from laris.ducking import AudioDucker

    calls = []
    volumes = iter([80, ducking.DUCK_VOLUME])

    def fake_run(argv, **kwargs):
        calls.append(argv[-1])
        if "get volume settings" in argv[-1]:
            return SimpleNamespace(returncode=0, stdout=f"{next(volumes)}\n".encode())
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(ducking.subprocess, "run", fake_run)

    ducker = AudioDucker()
    ducker.duck()
    ducker.duck()
    ducker.restore()

    assert "set volume output volume 80" in calls


def test_restore_without_duck_is_noop(monkeypatch):
    from laris.ducking import AudioDucker

    calls = []
    _fake_osascript(monkeypatch, current_volume=50, calls=calls)

    AudioDucker().restore()

    assert calls == []


def test_osascript_failure_never_raises(monkeypatch):
    from laris import ducking
    from laris.ducking import AudioDucker

    def exploding_run(argv, **kwargs):
        raise OSError("no osascript")

    monkeypatch.setattr(ducking.subprocess, "run", exploding_run)

    ducker = AudioDucker()
    ducker.duck()  # must not raise
    ducker.restore()  # must not raise
