from strands.models import BedrockModel
from strands.models.openai import OpenAIModel

from found_agent.config import AgentConfig
from found_agent.models import build_model, mantle_base_url, read_api_key


def config(**overrides):
    return AgentConfig(
        model_id="nvidia.nemotron-nano-3-30b", gateway_url="", region="ap-south-1", **overrides
    )


def test_without_a_key_the_bedrock_provider_is_used():
    assert isinstance(build_model(config(), 512), BedrockModel)


def test_with_a_key_calls_go_through_bedrock_mantle():
    model = build_model(config(api_key="ABSKexample"), 512)
    assert isinstance(model, OpenAIModel)
    assert model.client_args["base_url"] == "https://bedrock-mantle.ap-south-1.api.aws/v1"
    assert model.client_args["api_key"] == "ABSKexample"
    assert model.get_config()["model_id"] == "nvidia.nemotron-nano-3-30b"
    assert model.get_config()["params"] == {"max_tokens": 512, "temperature": 0.0}


def test_mantle_paths_follow_the_model_line():
    assert mantle_base_url("ap-south-1", "openai.gpt-oss-20b").endswith(".api.aws/v1")
    assert mantle_base_url("us-east-1", "openai.gpt-6-luna").endswith(".api.aws/openai/v1")


def test_key_comes_from_env_then_file_and_never_shows(tmp_path, monkeypatch):
    monkeypatch.delenv("BEDROCK_API_KEY", raising=False)
    missing = tmp_path / "none"
    assert read_api_key(missing) is None
    key_file = tmp_path / "key"
    key_file.write_text("<ABSKfromfile>\n", encoding="utf-8")
    assert read_api_key(key_file) == "ABSKfromfile"
    monkeypatch.setenv("BEDROCK_API_KEY", "ABSKfromenv")
    assert read_api_key(key_file) == "ABSKfromenv"
    assert "ABSK" not in repr(config(api_key="ABSKsecret"))


def test_config_reads_the_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "m")
    monkeypatch.setenv("GATEWAY_URL", "g")
    monkeypatch.setenv("BEDROCK_API_KEY", "ABSKk")
    assert AgentConfig.from_env().api_key == "ABSKk"
