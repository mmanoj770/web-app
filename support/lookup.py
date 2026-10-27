"""Look up FAQs and error codes for the help center API and the shopping assistant."""
import difflib
import re

from .models import FAQ, ErrorCode

WORD_RE = re.compile(r'[a-z0-9]+')
ERROR_CODE_RE = re.compile(r'\b(PAY|ORD|WEB|AI|TKT)[\s-]?(\d{3})\b', re.IGNORECASE)
# A bare HTTP status ("error 404", "got a 503", "429 too many requests"), but not "laptop under 500".
HTTP_STATUS_RE = re.compile(
    r'(?:\b(?:error|code|status|http|got|getting|seeing|shows?|showing)\b\D{0,12}\b([45]\d\d)\b'
    r'|\b([45]\d\d)\b\s*(?:error|code|status|page|bad request|unauthori[sz]ed|forbidden|not found'
    r'|too many|internal|service unavailable)|^\s*([45]\d\d)\s*\??\s*$)',
    re.IGNORECASE,
)
IGNORE = {
    'the', 'and', 'but', 'for', 'you', 'your', 'are', 'was', 'can', 'what', 'how', 'does', 'did', 'have', 'has',
    'with', 'this', 'that', 'its', 'will', 'there', 'any', 'get', 'got', 'please', 'tell', 'about', 'mean',
    'means', 'meaning', 'which', 'when', 'why', 'who', 'our', 'from', 'yet', 'still', 'just', 'want', 'need',
    # Too common in shop questions to tell FAQs apart.
    'take', 'order', 'orders', 'available', 'know', 'like', 'there',
}


def _stem(word):
    for suffix in ('ing', 'ed', 'es', 's'):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[:-len(suffix)]
    return word


def terms(text):
    return {_stem(w) for w in WORD_RE.findall(text.lower()) if len(w) > 2 and w not in IGNORE}


def _score(faq, wanted):
    question, keywords = terms(faq.question), terms(faq.keywords)
    hits = wanted & (question | keywords)
    score = 2 * len(wanted & question) + 1.5 * len(wanted & keywords) + 0.3 * len(wanted & terms(faq.answer))
    return score, len(hits), len(hits) / max(len(wanted), 1)


def search_faqs(query, limit=5, category=''):
    """Published FAQs ranked by how well they match `query` (all of them, in order, without a query)."""
    faqs = FAQ.objects.filter(is_published=True)
    if category:
        faqs = faqs.filter(category=category)
    if not query.strip():
        return list(faqs[:limit] if limit else faqs)
    wanted = terms(query)
    scored = [(_score(faq, wanted)[0], faq) for faq in faqs]
    ranked = [faq for score, faq in sorted(scored, key=lambda pair: -pair[0]) if score > 0]
    return ranked[:limit] if limit else ranked


def best_faq(message, strict=True):
    """The FAQ that answers `message`, or None.

    strict: the message must closely match one question (used before other intents);
    otherwise a looser match is accepted (used as a last resort).
    """
    wanted = terms(message)
    if not wanted:
        return None
    best, best_key = None, None
    for faq in FAQ.objects.filter(is_published=True):
        score, hits, coverage = _score(faq, wanted)
        similarity = difflib.SequenceMatcher(None, message.lower().strip(' ?!.'), faq.question.lower()).ratio()
        if strict:
            ok = similarity >= 0.75 or (hits >= 2 and coverage >= 0.6)
        else:
            ok = similarity >= 0.6 or (hits >= 2 and coverage >= 0.5) or (hits >= 1 and coverage == 1)
        key = (similarity >= 0.75, score)
        if ok and (best_key is None or key > best_key):
            best, best_key = faq, key
    return best


def find_error_code(text):
    """Return (code_text, ErrorCode or None) for the first error code in `text`, or (None, None).

    Understands store codes like PAY-001 and bare HTTP statuses like "error 404" (mapped to WEB-404).
    """
    match = ERROR_CODE_RE.search(text)
    if match:
        code = f'{match.group(1).upper()}-{match.group(2)}'
        return code, ErrorCode.objects.filter(code=code).first()
    match = HTTP_STATUS_RE.search(text)
    if not match:
        return None, None
    status = int(next(group for group in match.groups() if group))
    error = (ErrorCode.objects.filter(http_status=status, code__startswith='WEB-').first()
             or ErrorCode.objects.filter(http_status=status).order_by('code').first())
    return (error.code if error else str(status)), error


def faq_data(faq):
    return {
        'id': faq.pk, 'category': faq.category, 'category_label': faq.get_category_display(),
        'question': faq.question, 'answer': faq.answer, 'ticket_category': faq.ticket_category,
    }


def error_code_data(error):
    return {
        'code': error.code, 'title': error.title, 'area': error.area, 'area_label': error.get_area_display(),
        'http_status': error.http_status, 'meaning': error.meaning, 'resolution': error.resolution,
        'ticket_category': error.ticket_category,
    }
