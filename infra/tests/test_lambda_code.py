from stacks import lambda_code


class _Result:
    def __init__(self, code):
        self.returncode = code


def test_local_bundling_installs_wheels_and_copies_packages(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        lambda_code.subprocess, "run", lambda cmd, check: calls.append(cmd) or _Result(0)
    )
    assert lambda_code._LocalBundling().try_bundle(str(tmp_path), None) is True
    cmd = calls[0]
    assert cmd[cmd.index("--platform") + 1] == "manylinux2014_aarch64"
    assert "--only-binary=:all:" in cmd
    assert (tmp_path / "found_core" / "services" / "ingest.py").exists()
    assert (tmp_path / "handlers" / "api.py").exists()
    assert not list(tmp_path.rglob("__pycache__"))


def test_local_bundling_falls_back_when_pip_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(lambda_code.subprocess, "run", lambda cmd, check: _Result(1))
    assert lambda_code._LocalBundling().try_bundle(str(tmp_path), None) is False
    assert not (tmp_path / "found_core").exists()


def test_agent_bundle_holds_the_package_and_entry_point(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        lambda_code.subprocess, "run", lambda cmd, check: calls.append(cmd) or _Result(0)
    )
    local = lambda_code._LocalBundling(
        lambda_code.AGENT, "requirements.txt", lambda_code.AGENT_PACKAGES, lambda_code.AGENT_FILES
    )
    assert local.try_bundle(str(tmp_path), None) is True
    cmd = calls[0]
    assert cmd[cmd.index("-r") + 1].endswith("requirements.txt")
    assert cmd[cmd.index("--platform") + 1] == "manylinux2014_aarch64"
    assert (tmp_path / "main.py").exists()
    assert (tmp_path / "found_agent" / "app.py").exists()
    assert not (tmp_path / "tests").exists()


def test_agent_layer_installs_under_python(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        lambda_code.subprocess, "run", lambda cmd, check: calls.append(cmd) or _Result(0)
    )
    local = lambda_code._LocalBundling(
        lambda_code.AGENT, "requirements-lambda.txt", lambda_code.AGENT_PACKAGES, subdir="python"
    )
    assert local.try_bundle(str(tmp_path), None) is True
    cmd = calls[0]
    assert cmd[cmd.index("--target") + 1] == str(tmp_path / "python")
    assert (tmp_path / "python" / "found_agent" / "run.py").exists()
