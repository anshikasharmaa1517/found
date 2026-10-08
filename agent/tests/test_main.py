import main
from found_agent.app import app


def test_main_exposes_the_runtime_app():
    assert main.app is app
    assert "main" in app.handlers
