from pathlib import Path
import json
import urllib.error
import pytest
from langgraph.types import Command
from report_agent.workflow import load_csv, open_workflow, model_plan

ROWS = [{'day': '2026-11-01', 'channel': 'a', 'visits': 100, 'conversions': 10},
        {'day': '2026-11-02', 'channel': 'a', 'visits': 50, 'conversions': 10}]
CONFIG = {'configurable': {'thread_id': 'thread-a'}, 'recursion_limit': 12}


def initial(question='按渠道分析'):
    return {'question': question, 'rows': ROWS, 'trace': []}


def test_pause_restart_resume_without_rerunning_tools(tmp_path):
    database = tmp_path / 'state.sqlite'
    with open_workflow(database) as graph:
        result = graph.invoke(initial(), CONFIG)
        assert result['__interrupt__']
        assert graph.get_state(CONFIG).next == ('review',)
    with open_workflow(database) as graph:
        result = graph.invoke(Command(resume={'approve': True}), CONFIG)
        assert result['approved'] and '13.33%' in result['report']
        assert result['trace'] == ['plan', 'execute', 'review', 'approved']
        assert not graph.get_state(CONFIG).next


def test_reject_does_not_publish(tmp_path):
    with open_workflow(tmp_path/'state') as graph:
        graph.invoke(initial(), CONFIG)
        result = graph.invoke(Command(resume={'approve': False}), CONFIG)
        assert result['report'] == '' and result['trace'][-1] == 'rejected'


def test_thread_isolation(tmp_path):
    other = {'configurable': {'thread_id': 'thread-b'}}
    with open_workflow(tmp_path/'state') as graph:
        graph.invoke(initial(), CONFIG)
        graph.invoke(initial('daily'), other)
        assert graph.get_state(CONFIG).values['plan'] == ['channel_summary']
        assert graph.get_state(other).values['plan'] == ['daily_summary']


@pytest.mark.parametrize('plan', [{'tools': ['eval']}, {'tools': ['daily_summary']*3}, {'tools': 'daily_summary'}, {}, None])
def test_tool_allowlist_and_limit(tmp_path, plan):
    with open_workflow(tmp_path/'state', lambda _: plan) as graph:
        with pytest.raises(ValueError):
            graph.invoke(initial(), CONFIG)


def test_two_tools_and_online_mode_stub(tmp_path):
    with open_workflow(tmp_path/'state', lambda _: {'tools': ['daily_summary', 'channel_summary']}) as graph:
        result = graph.invoke(initial(), CONFIG)
        assert len(result['results']) == 2 and result['mode'] == 'compatible-model'


@pytest.mark.parametrize('decision', [{'approve': 'false'}, True])
def test_human_decision_is_boolean(tmp_path, decision):
    with open_workflow(tmp_path/'state') as graph:
        graph.invoke(initial(), CONFIG)
        with pytest.raises(ValueError):
            graph.invoke(Command(resume=decision), CONFIG)


def test_empty_resume_stays_paused(tmp_path):
    with open_workflow(tmp_path/'state') as graph:
        graph.invoke(initial(), CONFIG)
        graph.invoke(Command(resume={}), CONFIG)
        snapshot = graph.get_state(CONFIG)
        assert snapshot.next == ('review',)
        assert not snapshot.values.get('report')


def test_csv_validation(tmp_path):
    file = tmp_path/'bad.csv'
    file.write_text('day,channel,visits,conversions\n2026-11-01,a,10,11\n')
    with pytest.raises(ValueError):
        load_csv(file)


def test_model_gateway_http_retry(monkeypatch):
    for key, value in [('LLM_BASE_URL', 'http://127.0.0.1:9999/v1'), ('LLM_MODEL', 'test-stub'), ('LLM_API_KEY', 'local-stub-not-a-real-key')]:
        monkeypatch.setenv(key, value)
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, *_):
            return json.dumps({'choices': [{'message': {'content': '{"tools":["daily_summary"]}'}}]}).encode()
    def fake(request, **_):
        calls.append(json.loads(request.data))
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 503, 'temporary', {}, None)
        return Response()
    monkeypatch.setattr('urllib.request.urlopen', fake)
    assert model_plan('daily')['tools'] == ['daily_summary']
    assert len(calls) == 2 and 'rows' not in str(calls)


def test_ui_human_gate_and_persistence(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('REPORT_CHECKPOINT_DB', str(tmp_path/'ui.sqlite'))
    app = AppTest.from_file('portfolio_app.py', default_timeout=30).run()
    app.button[0].click().run()
    assert not app.exception
    assert any('等待人工审核' in item.value for item in app.info)
    assert not any('Operations report' in item.value for item in app.markdown)
    next(b for b in app.button if b.label == '审核通过').click().run()
    assert not app.exception
    assert any('Operations report' in item.value for item in app.markdown)
    reopened = AppTest.from_file('portfolio_app.py', default_timeout=30).run()
    assert any('Operations report' in item.value for item in reopened.markdown)
