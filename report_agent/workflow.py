from __future__ import annotations
from contextlib import contextmanager
import csv
from datetime import date
import json
import os
from pathlib import Path
from typing import Annotated, TypedDict
import urllib.error
import urllib.request
import time
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt

ALLOWED = ('daily_summary', 'channel_summary')


class State(TypedDict, total=False):
    question: str
    rows: list[dict]
    plan: list[str]
    mode: str
    results: dict
    approved: bool
    report: str
    trace: Annotated[list[str], lambda before, after: before + after]


def load_csv(path: Path) -> list[dict]:
    path = Path(path)
    if path.stat().st_size > 5_000_000:
        raise ValueError('CSV exceeds 5 MB')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {'day', 'channel', 'visits', 'conversions'}.issubset(reader.fieldnames):
            raise ValueError('Missing required CSV fields')
        result = []
        for row in reader:
            day = date.fromisoformat(row['day']).isoformat()
            channel = row['channel'].strip()
            visits, conversions = int(row['visits']), int(row['conversions'])
            if not channel or len(channel) > 80 or not 0 <= conversions <= visits:
                raise ValueError('Invalid channel or event counts')
            result.append(dict(day=day, channel=channel, visits=visits, conversions=conversions))
            if len(result) > 50_000:
                raise ValueError('Too many records')
    if not result:
        raise ValueError('Empty dataset')
    return result


def aggregate(rows, field):
    groups = {}
    for row in rows:
        acc = groups.setdefault(row[field], [0, 0])
        acc[0] += row['visits']
        acc[1] += row['conversions']
    return [{'group': key, 'visits': values[0], 'conversions': values[1],
             'conversion_rate': values[1]/values[0] if values[0] else None}
            for key, values in sorted(groups.items())]


def model_plan(question: str) -> dict:
    """Optional compatible endpoint. No credentials or request body enter checkpoints."""
    url = os.environ.get('LLM_BASE_URL', '').rstrip('/')
    model = os.environ.get('LLM_MODEL', '')
    key = os.environ.get('LLM_API_KEY', '')
    if not all((url, model, key)) or not url.startswith(('https://', 'http://127.0.0.1:', 'http://localhost:')):
        raise ValueError('Configure compatible base URL, model and API key')
    payload = {'model': model, 'messages': [
        {'role': 'system', 'content': 'Select one or two tools from daily_summary, channel_summary. Return only JSON: {"tools": ["daily_summary"]}. Do not generate code.'},
        {'role': 'user', 'content': question}], 'response_format': {'type': 'json_object'}}
    request = urllib.request.Request(url+'/chat/completions', data=json.dumps(payload).encode(),
                                     headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read(100_000))
            return json.loads(body['choices'][0]['message']['content'])
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise ValueError(f'Model HTTP error {exc.code}') from None
            time.sleep(0.1*(attempt+1))
        except (KeyError, TypeError, json.JSONDecodeError, OSError):
            raise ValueError('Model response unavailable or invalid') from None


def build(checkpointer, planner=None):
    # Adapted from the upstream StateGraph plan/execute/refine/finalize pattern.
    def plan(state):
        question = state.get('question', '').strip()
        if not question or len(question) > 1000 or not state.get('rows'):
            raise ValueError('Supply a short question and validated data')
        if planner:
            output = planner(question)
            tools = output.get('tools') if isinstance(output, dict) else None
            mode = 'compatible-model'
        else:
            tools = ['channel_summary'] if any(w in question.lower() for w in ('渠道', 'channel')) else ['daily_summary']
            mode = 'offline-rule-demo'
        if not isinstance(tools, list) or not 1 <= len(tools) <= 2 or any(not isinstance(t, str) or t not in ALLOWED for t in tools):
            raise ValueError('Planner returned an unsupported tool or exceeded the plan limit')
        return {'plan': list(dict.fromkeys(tools)), 'mode': mode, 'trace': ['plan']}

    def execute(state):
        results = {tool: aggregate(state['rows'], 'day' if tool == 'daily_summary' else 'channel') for tool in state['plan']}
        return {'results': results, 'trace': ['execute']}

    def review(state):
        decision = interrupt({'type': 'human_review', 'mode': state['mode'], 'results': state['results'],
                              'instruction': 'Resume with {"approve": true} or {"approve": false}'})
        if not isinstance(decision, dict) or type(decision.get('approve')) is not bool:
            raise ValueError('Review requires a boolean approve value')
        return {'approved': decision['approve'], 'trace': ['review']}

    def finish(state):
        if not state['approved']:
            return {'report': '', 'trace': ['rejected']}
        lines = ['# Operations report', '', 'Mode: '+state['mode'], '', 'Question: '+state['question']]
        for tool, groups in state['results'].items():
            lines.extend(['', '## '+tool, '', '| Group | Visits | Conversions | Rate |', '|---|---:|---:|---:|'])
            for row in groups:
                safe = str(row['group']).replace('|', '\\|').replace('\n', ' ')
                rate = f"{row['conversion_rate']:.2%}" if row['conversion_rate'] is not None else 'N/A'
                lines.append(f"| {safe} | {row['visits']} | {row['conversions']} | {rate} |")
        return {'report': '\n'.join(lines), 'trace': ['approved']}

    graph = StateGraph(State)
    for name, node in [('plan', plan), ('execute', execute), ('review', review), ('finish', finish)]:
        graph.add_node(name, node)
    graph.add_edge(START, 'plan')
    graph.add_edge('plan', 'execute')
    graph.add_edge('execute', 'review')
    graph.add_edge('review', 'finish')
    graph.add_edge('finish', END)
    return graph.compile(checkpointer=checkpointer)


@contextmanager
def open_workflow(database: Path, planner=None):
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(database)) as saver:
        yield build(saver, planner)
