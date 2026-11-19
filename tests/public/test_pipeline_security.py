"""Regression checks for policy boundaries, audit privacy and limiter expiry."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))


def test_rate_window_expiry_and_user_isolation(monkeypatch):
    from assignment import rate_limiter as m
    now = [100.0]
    monkeypatch.setattr(m.time, 'monotonic', lambda: now[0])
    limiter = m.RateLimitPlugin(1, 10)
    async def send(user):
        return await limiter.on_user_message_callback(invocation_context=SimpleNamespace(user_id=user), user_message=None)
    assert asyncio.run(send('a')) is None
    assert asyncio.run(send('a')) is not None
    assert asyncio.run(send('b')) is None
    now[0] = 110.0
    assert asyncio.run(send('a')) is None


def test_audit_redacts_and_correlates(tmp_path):
    from assignment.audit_log import AuditLogPlugin
    logger = AuditLogPlugin()
    logger.record_input(user_id='a', text='admin123', request_id='r1')
    logger.record_input(user_id='a', text='bank balance', request_id='r2')
    logger.record_output(user_id='a', text='person@example.com', request_id='r2')
    logger.record_output(user_id='a', text='sk-vinbank-secret-2024', request_id='r1')
    path = logger.export_json(str(tmp_path / 'audit.json'))
    text = path.read_text(encoding='utf-8')
    assert 'admin123' not in text and 'person@example.com' not in text
    assert 'sk-vinbank-secret-2024' not in text
    assert [row['request_id'] for row in logger.logs] == ['r2', 'r1']
    assert all(row['latency_ms'] >= 0 for row in logger.logs)


def test_monitor_zero_denominators_and_repeat_check():
    from assignment.monitoring import MonitoringAlert
    monitor = MonitoringAlert()
    assert monitor.check_metrics() == []
    monitor.total_requests = monitor.blocked_requests = 2
    assert len(monitor.check_metrics()) == 1
    assert len(monitor.check_metrics()) == 1


def test_egress_url_spoofing_and_pii():
    from assignment.pipeline import is_egress_allowed
    for url in ['https://api.vinbank.example.evil.com/x', 'https://evil.com@api.vinbank.example/x',
                'http://api.vinbank.example/x', 'https://api.vinbank.example:8443/x',
                'https://api.vinbank.example:bad/x']:
        assert not is_egress_allowed(url, 'bank transfer')
    for payload in ['Call 0901234567', 'person@example.com', 'db.vinbank.internal:5432']:
        assert not is_egress_allowed('https://api.vinbank.example/x', payload)


def test_output_plugin_filters_before_reply():
    from guardrails.output_guardrails import OutputGuardrailPlugin
    from google.genai import types
    plugin = OutputGuardrailPlugin(use_llm_judge=False)
    response = SimpleNamespace(content=types.Content(role='model', parts=[types.Part.from_text(text='admin123 person@example.com')]))
    result = asyncio.run(plugin.after_model_callback(callback_context=None, llm_response=response))
    assert 'admin123' not in result.content.parts[0].text
    assert 'person@example.com' not in result.content.parts[0].text
    assert plugin.redacted_count == 1


def test_banking_plurals_are_allowed():
    from guardrails.input_guardrails import topic_filter
    assert topic_filter("How do bank transfers work?") == "ALLOW"
    assert topic_filter("Compare loans and savings accounts") == "ALLOW"


def test_red_proxy_applies_to_runtime_and_nemo(monkeypatch):
    from core.config import red_openai_client_kwargs
    from agents.red_advance_nemo import build_rails_dict
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example/v1")
    assert red_openai_client_kwargs()["base_url"] == "https://proxy.example/v1"
    config = build_rails_dict(provider="openai", model="test-model")
    assert config["models"][0]["parameters"]["base_url"] == "https://proxy.example/v1"



def test_formatted_phone_redaction_and_egress():
    from guardrails.output_guardrails import content_filter
    from assignment.pipeline import is_egress_allowed
    for phone in ["090 123 4567", "090-123-4567", "+84 90 123 4567", "(028) 3822 3344"]:
        result = content_filter("Contact " + phone)
        assert not result["safe"], phone
        assert "[REDACTED]" in result["redacted"]
        assert not is_egress_allowed("https://api.vinbank.example/x", "Contact " + phone)
    assert content_filter("Official hotline: 1900 545 467")["safe"]


def test_runtime_limit_blocks_model_and_keeps_users_separate(monkeypatch):
    from assignment.pipeline import build_production_plugins
    from core.openai_runtime import OpenAIRunner, OpenAIAgent
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="A savings account earns interest."))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(OpenAIRunner, "_client", lambda self: client)
    runner = OpenAIRunner(app_name="test", model="fake", plugins=build_production_plugins(max_requests=1))
    agent = OpenAIAgent(name="test", instruction="Banking only")
    async def scenario():
        assert "savings" in await runner.chat(agent, "What is a savings account?", user_id="alice")
        assert "Rate limit" in await runner.chat(agent, "What is a savings account?", user_id="alice")
        assert "savings" in await runner.chat(agent, "What is a savings account?", user_id="bob")
    asyncio.run(scenario())
    assert len(calls) == 2


def test_conversation_history_isolated_by_user_and_session(monkeypatch):
    from core.openai_runtime import OpenAIRunner, OpenAIAgent
    calls = []
    def create(**kwargs):
        calls.append(kwargs["messages"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="bank reply"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(OpenAIRunner, "_client", lambda self: client)
    runner = OpenAIRunner(app_name="test", model="fake")
    agent = OpenAIAgent(name="test", instruction="system")
    async def scenario():
        await runner.chat(agent, "first", user_id="a", session_id="session")
        await runner.chat(agent, "second", user_id="a", session_id="session")
        await runner.chat(agent, "other user", user_id="b", session_id="session")
        await runner.chat(agent, "other session", user_id="a", session_id="different")
    asyncio.run(scenario())
    assert [m["content"] for m in calls[1]] == ["system", "first", "bank reply", "second"]
    assert len(calls[2]) == len(calls[3]) == 2


def test_attack_runner_passes_history_and_saves_turns(monkeypatch):
    from attacks.attacks import run_attacks
    from core.openai_runtime import OpenAIRunner, OpenAIAgent
    calls = []
    def create(**kwargs):
        calls.append(kwargs["messages"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="bank reply"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(OpenAIRunner, "_client", lambda self: client)
    runner = OpenAIRunner(app_name="test", model="fake")
    prompt = {"id": 5, "category": "multi-turn", "input": "summary", "turns": ["first", "second", "third"]}
    result = asyncio.run(run_attacks(OpenAIAgent(name="test", instruction="system"), runner,
                                    prompts=[prompt], save_json=False))
    assert len(result[0]["turns"]) == 3
    assert len(calls[-1]) == 6


def test_leak_measurement_requires_actual_protected_value():
    from attacks.attacks import response_leaked_secrets
    assert not response_leaked_secrets("admin_password=[REDACTED]; api_key=[REDACTED]")
    assert not response_leaked_secrets("password=placeholder")
    assert response_leaked_secrets("admin123")
    assert response_leaked_secrets("a d m i n 1 2 3")
