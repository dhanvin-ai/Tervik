import copy
import json
import sys
from pathlib import Path
import pytest
from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from schema_contract import validate_records


@pytest.fixture
def records():
    return json.loads((ROOT / 'tests/fixtures/phase-1-gate.json').read_text())['records']


def test_phase_one_gate(records):
    validate_records(records)
    messages = [r for r in records if r['record_kind'] == 'message']
    assert [m['payload']['role'] for m in sorted(messages, key=lambda r: r['source_timestamp'])] == ['user', 'assistant', 'user', 'assistant']
    delayed = next(r for r in records if r['event_id'] == 'question-2')
    assert delayed['source_timestamp'] < next(r for r in records if r['event_id'] == 'answer-2')['source_timestamp']
    assert delayed['ingested_at'] > next(r for r in records if r['event_id'] == 'answer-2')['ingested_at']
    operations = [r for r in records if r['record_kind'] == 'span']
    assert len(operations) == 4 and {r['payload']['message_id'] for r in operations} == {'answer-1'}
    assert operations[0]['payload']['parent_span_id'] == 'lookup'
    assert next(r for r in operations if r['payload']['id'] == 'lookup')['payload']['parent_span_id'] == 'turn'
    assert len(next(r for r in records if r['record_kind'] == 'finding')['payload']['evidence']) == 2


@pytest.mark.parametrize('field', ['event_id', 'organization_id', 'project_id', 'source_timestamp', 'ingested_at', 'schema_version'])
def test_required_event_identity_and_timestamps(records, field):
    del records[0][field]
    with pytest.raises(ValidationError):
        validate_records(records)


def test_cannot_cite_evidence_from_another_organization(records):
    records[0]['organization_id'] = 'other-org'
    finding = next(r for r in records if r['record_kind'] == 'finding')
    finding['payload']['evidence'][0]['event_id'] = records[0]['event_id']
    finding['payload']['evidence'][0]['record_kind'] = 'message'
    with pytest.raises(ValueError, match='evidence'):
        validate_records(records)


def test_no_cycles_or_duplicate_records(records):
    with pytest.raises(ValueError, match='Duplicate'):
        validate_records(records + [copy.deepcopy(records[0])])
    next(r for r in records if r['event_id'] == 'span:trace-a:turn')['payload']['parent_span_id'] = 'database'
    with pytest.raises(ValueError, match='Cyclic'):
        validate_records(records)


def test_missing_parent_can_arrive_later(records):
    # An unresolved technical parent does not invalidate a child's own telemetry.
    without_parent = [r for r in records if r['event_id'] != 'span:trace-a:lookup']
    validate_records(without_parent)
