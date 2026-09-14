"""Minimal targeted JSONC edits: preserve comments and unrelated bytes.

Only a single top-level object with modules-right array is supported; reject
ambiguous/duplicate keys rather than rewriting arbitrary user configuration.
"""
import json
import re

TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|\s+|[{}\[\],:]|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null', re.S)


def tokens(text):
    result = []
    pos = 0
    for match in TOKEN.finditer(text):
        if match.start() != pos:
            raise ValueError('Invalid JSONC token')
        pos = match.end()
        value = match.group()
        if value.isspace() or value.startswith(('//', '/*')):
            continue
        result.append((value, match.start(), match.end()))
    if pos != len(text):
        raise ValueError('Invalid JSONC ending')
    return result


def strip_jsonc(text):
    parts = tokens(text)
    return ''.join(t[0] for i, t in enumerate(parts)
                   if not (t[0] == ',' and i + 1 < len(parts) and parts[i+1][0] in (']', '}')))


def _unique(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError('Duplicate JSONC key')
        data[key] = value
    return data


def integrate(text, definition):
    config = json.loads(strip_jsonc(text), object_pairs_hook=_unique)
    if not isinstance(config, dict) or not isinstance(config.get('modules-right'), list):
        raise ValueError('Expected one config object with modules-right array')
    ts = tokens(text)
    depth = 0
    fields = {}
    for i, (value, start, end) in enumerate(ts):
        if depth == 1 and value.startswith('"') and ts[i+1][0] == ':':
            first = i + 2
            last = first
            nesting = 0
            while last < len(ts):
                item = ts[last][0]
                if nesting == 0 and item in (',', '}'):
                    break
                if item in ('{', '['):
                    nesting += 1
                elif item in ('}', ']'):
                    nesting -= 1
                last += 1
            fields[json.loads(value)] = (first, last - 1)
        if value in ('{', '['):
            depth += 1
        elif value in ('}', ']'):
            depth -= 1
    edits = []
    if 'custom/mercedes' not in config['modules-right']:
        first, last = fields['modules-right']
        insert = '"custom/mercedes"' + (', ' if config['modules-right'] else '')
        edits.append((ts[first][2], ts[first][2], insert))
    value = json.dumps(definition, ensure_ascii=False, indent=2)
    if 'custom/mercedes' in fields:
        if config['custom/mercedes'] != definition:
            first, last = fields['custom/mercedes']
            edits.append((ts[first][1], ts[last][2], value))
    else:
        if ts[-2][0] != ',':
            edits.append((ts[-2][2], ts[-2][2], ','))
        edits.append((ts[-1][1], ts[-1][1], '\n  "custom/mercedes": ' + value + '\n'))
    # Equal-offset insertions apply in reverse insertion order (comma first
    # in the resulting text, then the new property), independent of content.
    for start, end, value in sorted(reversed(edits), key=lambda edit: edit[0], reverse=True):
        text = text[:start] + value + text[end:]
    json.loads(strip_jsonc(text), object_pairs_hook=_unique)
    return text
