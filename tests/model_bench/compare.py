#!/usr/bin/env python3
"""Summarise every recorded bench run into one table.

    python3 compare.py [--results DIR]

Reads results/<label>/summary.json, which bench.py writes.
"""
import argparse
import json
import pathlib
import sys


def real_cost(label, totals, models_json, model_id=None):
    """Recompute cost from the provider's own rates.

    The SDK reports total_cost_usd at ANTHROPIC prices no matter which model is
    behind the gateway, because it believes it is talking to Claude. On a
    deepseek run it said $7.48 where the provider dashboard said $0.21 -- a 37x
    overstatement, and enough to invert the conclusion of a comparison.
    """
    entry = (models_json.get('models') or {}).get(label) or {}
    pr = entry.get('pricing_per_mtok')
    if not pr and model_id:
        # Bench labels are free-form; fall back to the model id the run recorded.
        pr = (models_json.get('pricing_by_model_id') or {}).get(model_id)
    if not pr:
        return None
    m = 1e-6
    return (totals.get('input_tokens', 0) * pr['in'] * m
            + totals.get('output_tokens', 0) * pr['out'] * m
            + totals.get('cache_read_input_tokens', 0) * pr.get('cache_read', 0) * m
            + totals.get('cache_creation_input_tokens', 0) * pr.get('cache_write', 0) * m)


def load(results_dir):
    runs = []
    for summary in sorted(results_dir.glob('*/summary.json')):  # one dir per run, never reused
        try:
            runs.append(json.loads(summary.read_text()))
        except ValueError as e:
            print('skipping %s: %s' % (summary, e), file=sys.stderr)
    return runs


def row(run):
    t = run.get('totals', {})
    turns = run.get('turns', [])
    done = [x for x in turns if x.get('ok')]
    # Cache reads are input too; counting only input_tokens makes a model with
    # good caching look like it read almost nothing.
    total_in = (t.get('input_tokens', 0) + t.get('cache_read_input_tokens', 0)
                + t.get('cache_creation_input_tokens', 0))
    return {
        'label': run.get('label', '?'),
        'run_id': run.get('run_id', ''),
        'model': (turns[0].get('usage', {}) or {}).get('model', '?') if turns else '?',
        'turns_ok': '%d/%d' % (len(done), len(turns)),
        'seconds': sum(x.get('seconds', 0) for x in turns),
        'shots': run.get('screenshots', 0),
        'out': t.get('output_tokens', 0),
        'in_raw': t.get('input_tokens', 0),
        'cache_r': t.get('cache_read_input_tokens', 0),
        'cache_w': t.get('cache_creation_input_tokens', 0),
        'in_total': total_in,
        'sdk_cost': t.get('total_cost_usd', 0.0),
        # A blind model pays a second provider to look at every screenshot.
        'vision_cost': t.get('vision_cost_usd', 0.0),
        'vision_calls': t.get('vision_calls', 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--results', default=str(pathlib.Path(__file__).parent / 'results'))
    args = ap.parse_args()

    runs = load(pathlib.Path(args.results))
    if not runs:
        print('no runs in %s -- run bench.py first' % args.results)
        return 1

    models_json = json.loads((pathlib.Path(__file__).parent / 'models.json').read_text())
    rows = []
    for r in runs:
        d = row(r)
        main = real_cost(d['label'], r.get('totals', {}), models_json, d.get('model'))
        # The describer is part of what the run cost, not a footnote.
        d['cost'] = None if main is None else main + (d['vision_cost'] or 0.0)
        rows.append(d)
    head = ('label', 'model', 'turns', 'secs', 'shots', 'output',
            'uncached in', 'cache rd', 'real $', 'sdk $')
    fmt = '%-12s %-22s %-6s %6s %6s %9s %12s %10s %8s %8s'
    print(fmt % head)
    print('-' * 118)
    for r in rows:
        real = '%.3f' % r['cost'] if r['cost'] is not None else '  ?'
        print(fmt % (r['label'], r['model'], r['turns_ok'], r['seconds'], r['shots'],
                     r['out'], r['in_raw'], r['cache_r'], real, '%.2f' % r['sdk_cost']))
    print()
    print('real $ = provider rates (models.json) PLUS the vision describer, which a')
    print('         model without its own vision pays on every screenshot.')
    print('sdk  $ = what the SDK reported, always at Anthropic prices. Ignore it for')
    print('         anything not actually served by Anthropic.')

    # What actually decides cost is the share of input served from cache.
    #
    # Do NOT read cache_creation=0 as "no caching": providers with implicit
    # caching (Moonshot, for one) never bill a cache write and always report
    # zero there, while still serving most of the conversation from cache. The
    # honest signal is uncached input as a fraction of total input.
    print()
    for r in rows:
        if r['vision_calls']:
            print('%-12s describer: %s calls, $%.4f' % (r['label'], r['vision_calls'], r['vision_cost']))
    for r in rows:
        if not r['in_total']:
            continue
        hit = 100.0 * r['cache_r'] / r['in_total']
        note = ''
        if hit < 50:
            note = '  <- most input is being re-sent uncached every turn'
        print('%-12s cache hit %5.1f%%  (%s cached / %s total input)%s'
              % (r['label'], hit, r['cache_r'], r['in_total'], note))
    return 0


if __name__ == '__main__':
    sys.exit(main())
