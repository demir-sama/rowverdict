"""Reproducible deterministic-core proof. Does NOT simulate a human Hermes approval."""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import Engine, Refusal, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', help='New or empty disposable directory; never a real CSV inbox')
    args = parser.parse_args()
    work = Path(args.workspace).resolve() if args.workspace else Path(tempfile.mkdtemp(prefix='rowverdict-demo-'))
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        parser.error('workspace must be empty, to avoid overwriting anything')
    inbox = work / 'inbox'; inbox.mkdir()
    source = inbox / 'orders.csv'
    shutil.copyfile(ROOT / 'demo/orders-worldwide.csv', source)
    app = Engine(work / 'state', [str(inbox)])
    contract = json.loads((ROOT / 'demo/contract.json').read_text())
    initial_hash = digest(source.read_bytes())
    print('ROWVERDICT / deterministic core demonstration')
    print('Offline QA only. Native human approval is tested separately.')
    inspected = app.inspect(str(source))
    print(f"INSPECT  {inspected['input_rows']:,} records / {len(inspected['columns'])} columns / full scan")
    run = app.plan(str(source), contract)
    s = run['summary']
    print(f"PLAN     {s['clean_rows']:,} clean + {s['quarantined_rows']:,} quarantine = {s['input_rows']:,} input")
    print('ISSUES   ' + ', '.join(f'{k}={v}' for k,v in s['issue_counts'].items()))
    print('REPAIRS  ' + ', '.join(f'{k}={v}' for k,v in s['changed_clean_cells'].items()))
    print('POLICY   ID strings kept; DD/MM dates -> ISO; no guessed values')
    receipt = app.export(run['id'])
    assert digest(source.read_bytes()) == initial_hash
    print('EXPORT   clean.csv + quarantine.json + receipt.json (private, atomic)')
    print('VERIFY   source unchanged; artifact SHA256 hashes recorded')
    assert '000042' in (Path(receipt['output_dir']) / 'clean.csv').read_text()
    print('ID       000042 preserved in actual clean CSV bytes')
    source.write_bytes((ROOT / 'demo/orders-worldwide-revision.csv').read_bytes())
    revision = json.loads((ROOT / 'demo/contract-revision.json').read_text())
    drift = app.plan(str(source), revision)
    print('DRIFT    added column: ' + ', '.join(drift['drift']['added_columns']) + '; ENUM delta: +' + str(drift['drift']['issue_delta']['ENUM']))
    source.write_bytes(source.read_bytes() + b'\n')
    try:
        app.export(drift['id'])
        raise AssertionError('stale source was wrongly exported')
    except Refusal as error:
        assert 'STALE' in str(error)
        print('STALE    source changed after review -> export REFUSED')
    reloaded = Engine(work / 'state', [str(inbox)])
    states = [r['state'] for r in reloaded.history()]
    assert states == ['STALE', 'EXPORTED']
    print('RELOAD   SQLite history: STALE, EXPORTED; receipt retained')
    print('RESULT   No rows disappear. No network. No silent repairs.')
    (work / 'demo-report.json').write_text(json.dumps({'first_plan':run, 'receipt':receipt, 'revision_plan':reloaded.get(drift['id']), 'states_after_reload':states}, indent=2) + '\n')
    print('WORKSPACE ' + str(work))


if __name__ == '__main__':
    main()
