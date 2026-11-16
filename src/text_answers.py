import json
import math
import unicodedata
from targeting import parse_target, MIN_CONFIDENCE


def decode_answer(raw):
    raw = raw.strip()
    # Accept a single fenced JSON document, never extract arbitrary embedded objects.
    lines = raw.splitlines()
    if len(lines) >= 3 and lines[0].strip().lower() in ('```json', '```') and lines[-1].strip() == '```':
        raw = '\n'.join(lines[1:-1]).strip()
    return json.loads(raw)


def parse_answer(raw):
    value = decode_answer(raw)
    if not isinstance(value, dict) or value.get('status') != 'ok':
        raise ValueError('No unambiguous answer')
    if value.get('mode', 'choice') == 'choice':
        return parse_target(json.dumps(value))
    if value.get('mode') in ('dropdown', 'menu'):
        from dropdown_support import parse_dropdown
        return parse_dropdown(value)
    if value.get('mode') == 'multiple':
        choices = value.get('choices')
        if not isinstance(choices, list) or not 1 <= len(choices) <= 20:
            raise ValueError('Invalid numeric target')
        checked = []
        for choice in choices:
            if not isinstance(choice, dict):
                raise ValueError('Invalid numeric target')
            checked.append(parse_target(json.dumps(dict(status='ok', x=choice.get('x'),
                y=choice.get('y'), confidence=value.get('confidence')))))
        if len({(v['x'],v['y']) for v in checked}) != len(checked):
            raise ValueError('Invalid numeric target')
        value['choices'] = sorted(checked, key=lambda v: (v['y'], v['x']))
        return value
    if value.get('mode') != 'text':
        raise ValueError('Unsupported answer type')
    confidence = value.get('confidence')
    if isinstance(confidence, bool) or not isinstance(confidence,(int,float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError('Invalid numeric target')
    if confidence < MIN_CONFIDENCE:
        raise ValueError('Low confidence')
    answer = value.get('answer')
    if not isinstance(answer,str) or not answer.strip() or len(answer)>300 or any(ord(ch)<32 or 127<=ord(ch)<=159 or unicodedata.category(ch)=='Cs' for ch in answer):
        raise ValueError('Invalid text answer')
    field = value.get('field')
    if not isinstance(field,dict):
        raise ValueError('Invalid numeric target')
    for key in ('left','top','right','bottom'):
        n=field.get(key)
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not 0<=n<=1:
            raise ValueError('Invalid numeric target')
    if not field['left'] < field['right'] or not field['top'] < field['bottom']:
        raise ValueError('Invalid numeric target')
    if (field['right']-field['left'])*(field['bottom']-field['top']) > .55:
        raise ValueError('Invalid numeric target')
    return value


def field_box(field, width, height):
    return (int(field['left']*width),int(field['top']*height),
            min(width,math.ceil(field['right']*width)),min(height,math.ceil(field['bottom']*height)))


def contains(box,x,y):
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def same_question(before, after, field=None):
    from PIL import ImageDraw, ImageChops
    if before.size != after.size:
        return False
    if field is not None:
        before,after=before.copy(),after.copy()
        l,t,r,b=field_box(field,*before.size)
        mask=(max(0,l-3),max(0,t-3),min(before.width-1,r+3),min(before.height-1,b+3))
        ImageDraw.Draw(before).rectangle(mask,fill='white')
        ImageDraw.Draw(after).rectangle(mask,fill='white')
    return ImageChops.difference(before,after).getbbox() is None
