from laris.project_matcher import resolve_project_dir


def test_resolve_project_dir_exact_match(tmp_path):
    project = tmp_path / "claude-code-ops"
    project.mkdir()

    assert resolve_project_dir("claude code ops", roots=[tmp_path]) == (
        "claude-code-ops",
        str(project),
    )


def test_resolve_project_dir_tolerates_fuzzy_match(tmp_path):
    project = tmp_path / "lina"
    project.mkdir()

    assert resolve_project_dir("linha", roots=[tmp_path]) == ("lina", str(project))


def test_resolve_project_dir_returns_none_without_match(tmp_path):
    (tmp_path / "lina").mkdir()

    assert resolve_project_dir("xerox", roots=[tmp_path]) is None


def test_resolve_project_dir_searches_all_roots(tmp_path):
    code = tmp_path / "code"
    dev = tmp_path / "dev"
    code.mkdir()
    dev.mkdir()
    project = dev / "axon"
    project.mkdir()

    assert resolve_project_dir("axon", roots=[code, dev]) == ("axon", str(project))


def test_resolve_project_dir_first_root_wins_on_name_collision(tmp_path):
    code = tmp_path / "code"
    dev = tmp_path / "dev"
    (code / "lina").mkdir(parents=True)
    (dev / "lina").mkdir(parents=True)

    assert resolve_project_dir("lina", roots=[code, dev]) == (
        "lina",
        str(code / "lina"),
    )


def test_resolve_project_dir_skips_missing_roots(tmp_path):
    dev = tmp_path / "dev"
    project = dev / "lume"
    project.mkdir(parents=True)

    missing = tmp_path / "does-not-exist"
    assert resolve_project_dir("lume", roots=[missing, dev]) == ("lume", str(project))


def test_resolve_project_dir_returns_none_when_no_root_exists(tmp_path):
    assert resolve_project_dir("lina", roots=[tmp_path / "nope"]) is None
