#!/usr/bin/env python3
"""Build and validate the public token aggregate from benchmark captures."""
from __future__ import annotations
import json
from importlib.metadata import version
from pathlib import Path
from token_measurement import ENCODING, tokens

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'benchmarks/results/matched-token-samples.json'

def checked(sample):
    assert tokens(sample['request_text']) == sample['request_tokens'], sample
    assert tokens(sample['response_text']) == sample['response_tokens'], sample
    assert sample['request_tokens']+sample['response_tokens'] == sample['total_tokens'], sample
    return sample

def rows(runs, token_at):
    assert len(runs) == 5
    assert all(run["status"] == "pass" and len(run["steps"]) == 6 for run in runs)
    out=[]
    for run in runs:
        steps=[]
        for step in run['steps']:
            token=checked(token_at(step)); steps.append({'operation':step.get('tool',step.get('operation',step.get('command'))),'request_tokens':token['request_tokens'],'response_tokens':token['response_tokens'],'total_tokens':token['total_tokens'],'raw':token})
        out.append({'run':run['run'],'status':run['status'],'verifier_outcome':'pass','total_tokens':sum(x['total_tokens'] for x in steps),'steps':steps})
    return out

def main():
    sleeper=json.load(open(ROOT/'benchmarks/results/sleeper-matched-results.json'))
    opencli=json.load(open(ROOT/'benchmarks/results/opencli-matched-results.json'))
    playwright=json.load(open(ROOT/'benchmarks/results/playwright-mcp-token-results.json'))
    assert sleeper['status']==opencli['status']==playwright['status']=='pass'
    data={'schema':'matched-browser-token-summary/v1','encoding':ENCODING,'note':'Deterministic encoding estimates, not model billing. Raw samples are already canonicalized before counting.',
      'sleeper_cli':{'status':'pass','runs':rows(sleeper['runs'],lambda s:s['token_sample'])},
      'opencli_cli':{'status':'pass','runs':rows(opencli['runs'],lambda s:s['token_sample'])},
      'sleeper_mcp':{'status':'pass','cold_discovery':sleeper['mcp']['cold_discovery'],'runs':rows(sleeper['mcp']['runs'],lambda s:s['token_sample']['model_payload']),'wire_runs':rows(sleeper['mcp']['runs'],lambda s:s['token_sample']['wire'])},
      'playwright_mcp':{'status':'pass','version':playwright['version'],'cold_discovery':playwright['cold_discovery'],'runs':rows(playwright['runs'],lambda s:s['tokens']['model_payload']),'wire_runs':rows(playwright['runs'],lambda s:s['tokens']['wire'])}}
    data['tokenizer_version'] = version('tiktoken')
    data['source_metadata'] = {
        'sleeper_cli': sleeper['token_method'],
        'opencli_cli': opencli['token_method'],
        'playwright_mcp': {key: playwright[key] for key in ('version', 'launch_argv', 'primitive_mapping', 'artifact_policy')},
    }
    OUT.write_text(json.dumps(data,indent=2)+'\n')
if __name__=='__main__': main()
