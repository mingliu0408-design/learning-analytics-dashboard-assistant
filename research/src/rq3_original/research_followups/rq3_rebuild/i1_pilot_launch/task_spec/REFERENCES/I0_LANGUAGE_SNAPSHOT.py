"""Small exposed grammar. Unsupported syntax is raw, never a guessed constraint."""
import re

VERSION = 'I0_EXPLICIT_SPAN_GRAMMAR_V1'
NUMBERS = {'one': 1, 'two': 2, 'five': 5, 'ten': 10, 'fifteen': 15,
           'twenty': 20, 'thirty': 30, 'forty-five': 45, 'sixty': 60}


def intent(query, explicit=None):
    if explicit is not None:
        if explicit not in ('ORDINARY_ACTION_ADVICE', 'EXPLICIT_SCHEDULE'):
            raise ValueError('Unknown visible task control')
        return dict(mode=explicit, basis='EXPLICIT_TASK_REQUEST_FIELD', source_quote=query)
    q = query.casefold().strip()
    # Negated/mixed requests are deliberately not general language inference.
    no_dates = bool(re.search(r'without (?:dates|scheduling dates)|no dates|不要排期|无需排期', q))
    schedule = bool(re.search(r'\b(?:schedule (?:these|my|the) tasks|make (?:me )?a timetable|put .+ on (?:my|the) calendar)\b|安排时间表|为.+排期', q))
    if re.search(r"\b(?:not|never|don't|do not|maybe)\b", q) and schedule:
        mode = 'UNKNOWN'
    elif schedule and not no_dates:
        mode = 'EXPLICIT_SCHEDULE'
    elif re.search(r'\b(?:summari[sz]e|summary|advice|suggest|next steps|remind|continue|resume|help)\b|总结|建议|继续|回顾', q) or no_dates:
        mode = 'ORDINARY_ACTION_ADVICE'
    else:
        mode = 'UNKNOWN'
    # P1 accepts a caller's explicit field. I0 records this grammar separately.
    return dict(mode=mode, basis='EXPLICIT_TASK_REQUEST_FIELD' if mode != 'UNKNOWN' else 'UNKNOWN', source_quote=query)


def purpose(query, explicit=None):
    allowed = ('GOAL_RECALL', 'PLAN_CONTINUATION', 'COMPLETION_RECALL')
    if explicit is not None:
        if explicit not in allowed:
            raise ValueError('Unsupported runtime purpose')
        return dict(value=explicit, basis='VISIBLE_CONTROL', version=VERSION)
    q = query.casefold()
    matches = []
    for value, pattern in [
        ('GOAL_RECALL', r'\b(?:remind|recall).*(?:goal|wanted to achieve)|回顾.*目标'),
        ('PLAN_CONTINUATION', r'\b(?:continue|resume).*(?:plan|where)|继续.*计划'),
        ('COMPLETION_RECALL', r'\b(?:what (?:have|had|did) i|remind me).*(?:finish|complet)|回顾.*完成')]:
        if re.search(pattern, q):
            matches.append(value)
    return dict(value=matches[0] if len(matches) == 1 else 'UNKNOWN',
                basis='QUERY_SPAN_GRAMMAR' if len(matches) == 1 else 'UNKNOWN', version=VERSION)


def numeric_constraint(text, source_id):
    """Recognise entire explicit available-duration sentences, never their fragments.

    No negation, date, hours-to-minutes conversion, session/day generalisation,
    approximation or bare number. Exact word variants are enumerated above.
    """
    number = r'(?:[1-9][0-9]{0,2}|' + '|'.join(NUMBERS) + ')'
    pattern = rf'I have (?:only )?({number}) minutes(?: available)?(?: for (?:this session|study))?\.?'
    m = re.fullmatch(pattern, text, flags=re.I)
    quarter = re.fullmatch(r'I have (?:only )?a quarter of an hour(?: for this session)?\.?', text, flags=re.I)
    cn = re.fullmatch(r'我(?:只有|有)([1-9][0-9]{0,2})分钟(?:可用于本次学习)?[。.]?', text)
    value = None
    syntax = 'UNSUPPORTED'
    if m:
        token = m.group(1).casefold()
        value = int(token) if token.isdigit() else NUMBERS[token]
        syntax = 'EXPLICIT_AVAILABLE_MINUTES_WHOLE_SENTENCE'
    elif quarter:
        value, syntax = 15, 'EXPLICIT_QUARTER_HOUR_WHOLE_SENTENCE'
    elif cn:
        value, syntax = int(cn.group(1)), 'EXPLICIT_ZH_AVAILABLE_MINUTES_WHOLE_SENTENCE'
    return dict(source_id=source_id, source_span=dict(text=text, start=0, end=len(text)),
                parsed_value=value, unit='minutes' if value is not None else None,
                uncertainty='EXPLICIT_DECLARATION_NOT_MEASURED' if value is not None else 'UNKNOWN',
                status='PARSED_SUPPORTED_SYNTAX' if value is not None else 'NOT_CHECKABLE',
                supported_syntax=syntax, grammar_version=VERSION)
