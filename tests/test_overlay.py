from unittest.mock import MagicMock


def _fake_popen_factory(spawned):
    def factory(*args, **kwargs):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.args = args[0] if args else kwargs.get("args")
        proc.spawn_kwargs = kwargs
        spawned.append(proc)
        return proc
    return factory


def test_child_receives_orb_url_via_env(monkeypatch):
    from laris import overlay

    spawned = []
    monkeypatch.setattr(overlay.subprocess, "Popen", _fake_popen_factory(spawned))

    handle = overlay.Overlay(url="http://127.0.0.1:8420/overlay?token=abc")
    handle.show("dictate")

    assert spawned[0].spawn_kwargs["env"]["OVERLAY_URL"] == (
        "http://127.0.0.1:8420/overlay?token=abc"
    )


def test_show_spawns_child_once_and_writes_command(monkeypatch):
    from laris import overlay

    spawned = []
    monkeypatch.setattr(overlay.subprocess, "Popen", _fake_popen_factory(spawned))

    handle = overlay.Overlay()
    handle.show("dictate")
    handle.show("transcribing")
    handle.hide()

    assert len(spawned) == 1
    writes = [call.args[0] for call in spawned[0].stdin.write.call_args_list]
    assert writes == [b"show dictate\n", b"show transcribing\n", b"hide\n"]


def test_dead_child_is_respawned_on_next_send(monkeypatch):
    from laris import overlay

    spawned = []
    monkeypatch.setattr(overlay.subprocess, "Popen", _fake_popen_factory(spawned))

    handle = overlay.Overlay()
    handle.show("dictate")
    spawned[0].poll.return_value = 1  # child died

    handle.show("command")

    assert len(spawned) == 2
    assert spawned[1].stdin.write.call_args.args[0] == b"show command\n"


def test_broken_pipe_never_raises_into_the_voice_loop(monkeypatch):
    from laris import overlay

    spawned = []
    monkeypatch.setattr(overlay.subprocess, "Popen", _fake_popen_factory(spawned))

    handle = overlay.Overlay()
    handle.show("dictate")
    spawned[0].stdin.write.side_effect = BrokenPipeError

    handle.hide()  # must not raise

    handle.show("dictate")  # and next send respawns
    assert len(spawned) == 2
