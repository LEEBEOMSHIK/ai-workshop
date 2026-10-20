"""Create unexecuted D layout candidates from approved synthetic capture/result exports."""

import argparse
import json
from pathlib import Path

from ai_workshop.labs.rag.evaluation.offline_input_artifacts import load_records
from ai_workshop.labs.rag.evaluation.offline_input_diagnosis import parse_object
from ai_workshop.labs.rag.evaluation.offline_layout_report import write_layout_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--classification', choices=['public_synthetic'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = load_records(parse_object(args.captures.read_text(encoding='utf-8')),
                           parse_object(args.results.read_text(encoding='utf-8')),
                           kind='actual_capture')
    write_layout_report(tuple(r.capture for r in records), args.output)
    print(json.dumps({'report': str(args.output / 'index.html'), 'attempts': len(records),
                      'execution_status': 'not_run', 'model_calls': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
