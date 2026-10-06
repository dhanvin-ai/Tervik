"""Validate canonical structure and relationships without requiring arrival order."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'schemas/events-v2.schema.json').read_text())
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def validate_records(records):
    identities = {}
    messages = {}
    spans = {}
    for record in records:
        VALIDATOR.validate(record)
        scope = (record['organization_id'], record['project_id'])
        identity = (*scope, record['event_id'])
        if identity in identities:
            raise ValueError('Duplicate canonical record identity')
        identities[identity] = record
        if record['record_kind'] == 'message':
            messages[(*scope, record['payload']['id'])] = record
        if record['record_kind'] == 'span':
            spans[(*scope, record['trace_id'], record['payload']['id'])] = record
    for record in records:
        scope = (record['organization_id'], record['project_id'])
        payload = record['payload']
        if record['record_kind'] == 'span':
            if payload['message_id'] is not None:
                message = messages.get((*scope, payload['message_id']))
                if not message or message['conversation_id'] != record['conversation_id']:
                    raise ValueError('Span references an unknown or mismatched message')
            visited = set()
            current = record
            while current:
                span_id = current['payload']['id']
                if span_id in visited:
                    raise ValueError('Cyclic span parentage')
                visited.add(span_id)
                parent_id = current['payload']['parent_span_id']
                current = spans.get((*scope, record['trace_id'], parent_id)) if parent_id else None
        if record['record_kind'] == 'finding':
            for ref in payload['evidence']:
                target = identities.get((*scope, ref['event_id']))
                if not target or target['record_kind'] != ref['record_kind'] or target['conversation_id'] != record['conversation_id']:
                    raise ValueError('Finding has unresolved or mismatched evidence')
    return records
