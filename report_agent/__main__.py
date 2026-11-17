import argparse
import json
from pathlib import Path
from langgraph.types import Command
from .workflow import load_csv, model_plan, open_workflow


def main():
    parser = argparse.ArgumentParser(description='Checkpointed reporting workflow with mandatory human review')
    parser.add_argument('--database', type=Path, default=Path('.data/checkpoints.sqlite'))
    sub = parser.add_subparsers(dest='action', required=True)
    start = sub.add_parser('start')
    start.add_argument('--csv', type=Path, default=Path('examples/channel_events.csv'))
    start.add_argument('--question', default='按渠道汇总转化')
    start.add_argument('--online', action='store_true')
    for command in [start, sub.add_parser('show'), sub.add_parser('review')]:
        command.add_argument('--thread', required=True)
        if command.prog.endswith('review'):
            command.add_argument('--approve', required=True, choices=['yes', 'no'])
    args = parser.parse_args()
    config = {'configurable': {'thread_id': args.thread}, 'recursion_limit': 12}
    planner = model_plan if getattr(args, 'online', False) else None
    with open_workflow(args.database, planner) as graph:
        snapshot = graph.get_state(config)
        if args.action == 'start':
            if snapshot.values:
                parser.error('Thread already exists; use a new thread or show/review')
            graph.invoke({'question': args.question, 'rows': load_csv(args.csv), 'trace': []}, config)
        elif args.action == 'review':
            if not snapshot.next:
                parser.error('No pending review for this thread')
            graph.invoke(Command(resume={'approve': args.approve == 'yes'}), config)
        snapshot = graph.get_state(config)
        # Public CLI output excludes raw input rows and model configuration.
        print(json.dumps({'thread': args.thread, 'next': list(snapshot.next),
                          **{k: v for k, v in snapshot.values.items() if k != 'rows'}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
