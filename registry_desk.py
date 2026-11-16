"""FLPA Registry Day Book — school-gate till helpers (not the Business Office)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import constants as _constants
from models import RegistryDailyHandover, StudentPayment, db

CURRENCY_USD = getattr(_constants, 'CURRENCY_USD', 'USD')
CURRENCY_LRD = getattr(_constants, 'CURRENCY_LRD', 'LRD')


def normalize_currency(code):
    helper = getattr(_constants, 'normalize_currency', None)
    if helper is not None:
        return helper(code)
    raw = (code or CURRENCY_USD).strip().upper().replace(' ', '')
    if raw in {CURRENCY_LRD, 'LD', 'L$', 'LD$', 'LR'}:
        return CURRENCY_LRD
    return CURRENCY_USD


def format_school_money(amount, currency='USD'):
    helper = getattr(_constants, 'format_school_money', None)
    if helper is not None:
        return helper(amount, currency)
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    symbol = 'L$' if normalize_currency(currency) == CURRENCY_LRD else 'US$'
    return f'{symbol} {value:,.2f}'


def format_dual_money(totals):
    helper = getattr(_constants, 'format_dual_money', None)
    if helper is not None:
        return helper(totals)
    parts = []
    usd = float((totals or {}).get(CURRENCY_USD) or 0)
    lrd = float((totals or {}).get(CURRENCY_LRD) or 0)
    if usd or not lrd:
        parts.append(format_school_money(usd, CURRENCY_USD))
    if lrd:
        parts.append(format_school_money(lrd, CURRENCY_LRD))
    return '  ·  '.join(parts)


def install_money_filters(app=None):
    """Register US$/L$ Jinja filters on the live Flask app (safe if already present)."""
    try:
        from flask import current_app, has_app_context
        target = app
        if target is None and has_app_context():
            target = current_app._get_current_object()
    except Exception:
        return
    if target is None:
        return
    env = getattr(target, 'jinja_env', None)
    if env is None:
        return
    env.filters.setdefault('school_money', lambda amount, currency='USD': format_school_money(amount, currency))
    env.filters.setdefault(
        'dual_money',
        lambda payments, fallback=0: money_label_for_payments(payments, fallback),
    )


try:
    install_money_filters()
except Exception:
    pass

FEE_KIND_CHOICES = getattr(
    _constants,
    'SCHOOL_FEE_KIND_CHOICES',
    (
        ('tuition', 'School fees'),
        ('registration', 'Registration fee'),
        ('re_admission', 'Re-admission fee'),
        ('id_card', 'ID card replacement'),
        ('documents', 'Documents / certificates'),
        ('other', 'Other school charge'),
    ),
)
FEE_KIND_LABELS = dict(FEE_KIND_CHOICES)
SCHOOL_FEE_KINDS = {'tuition', 'school_fees', 'school fee'}
REGISTRATION_KINDS = {'registration', 're_admission'}
OTHER_FEE_KINDS = {'id_card', 'documents', 'other'}
CHARGE_SCHOOL_FEES = 'school_fees'
CHARGE_REGISTRATION = 'registration'
CHARGE_OTHER = 'other'
YEARLY_CHARGE_BUCKETS = {CHARGE_SCHOOL_FEES, CHARGE_REGISTRATION}
INSTALLMENT_FULL = getattr(_constants, 'INSTALLMENT_FULL', 0)
COLLECTION_DESK_REGISTRY = 'registry'
HANDOVER_OPEN = 'open'
HANDOVER_SUBMITTED = 'submitted'
HANDOVER_ACKNOWLEDGED = 'acknowledged'


def school_business_date(when=None):
    """Calendar date for the till (UTC school day, matching StudentPayment.paid_on)."""
    if isinstance(when, datetime):
        stamp = when
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
        return stamp.date()
    if isinstance(when, date):
        return when
    return datetime.now(timezone.utc).date()


def fee_kind_label(kind):
    return FEE_KIND_LABELS.get((kind or '').strip(), 'School charge')


def semester_label(term):
    helper = getattr(_constants, 'semester_label', None)
    if helper:
        return helper(term)
    try:
        return {1: 'First Semester', 2: 'Second Semester'}.get(int(term), 'First Semester')
    except (TypeError, ValueError):
        return 'First Semester'


def installment_label(number):
    helper = getattr(_constants, 'installment_label', None)
    if helper:
        return helper(number)
    try:
        number = int(number)
    except (TypeError, ValueError):
        return ''
    return {0: 'Full year settlement', 1: '1st Installment', 2: '2nd Installment', 3: '3rd Installment'}.get(number, '')


def billing_period_label(term, installment=None):
    helper = getattr(_constants, 'billing_period_label', None)
    if helper:
        return helper(term, installment)
    heading = semester_label(term)
    inst = installment_label(installment)
    return f'{heading} · {inst}' if inst else heading


def is_school_fees_kind(kind):
    return (kind or '').strip().lower() in SCHOOL_FEE_KINDS


def classify_student_payment(payment=None, *, fee_kind=None, description=None):
    """School fees and registration reduce the yearly bill. All other charges do not."""
    kind = (fee_kind if fee_kind is not None else getattr(payment, 'fee_kind', None) or '')
    kind = str(kind).strip().lower()
    desc = description if description is not None else getattr(payment, 'description', None)
    desc = (desc or '').strip().lower()
    if kind in SCHOOL_FEE_KINDS:
        return CHARGE_SCHOOL_FEES
    if kind in REGISTRATION_KINDS:
        return CHARGE_REGISTRATION
    if kind in OTHER_FEE_KINDS:
        return CHARGE_OTHER
    if any(token in desc for token in (
        'uniform', 'graduation', 'id card', 'id-card', 'document', 'certificate',
        'transport', 'lunch', 'book', 'activity', 'pta', 'development',
    )):
        return CHARGE_OTHER
    if 'regist' in desc or 're-ad' in desc or 'readmission' in desc:
        return CHARGE_REGISTRATION
    if 'tuition' in desc or 'school fee' in desc:
        return CHARGE_SCHOOL_FEES
    if not desc:
        return CHARGE_SCHOOL_FEES
    return CHARGE_OTHER


def is_school_fee_payment(payment):
    return classify_student_payment(payment) == CHARGE_SCHOOL_FEES


def counts_toward_yearly_fee(payment=None, *, fee_kind=None, description=None):
    return classify_student_payment(payment, fee_kind=fee_kind, description=description) in YEARLY_CHARGE_BUCKETS


def payment_shows_semester_installment(payment=None, *, fee_kind=None, description=None):
    return classify_student_payment(payment, fee_kind=fee_kind, description=description) == CHARGE_SCHOOL_FEES


def normalize_charge_period(fee_kind, term=None, installment=None, description=None):
    """School fees keep semester/installment. Other charges do not store a billing period."""
    if classify_student_payment(fee_kind=fee_kind, description=description) != CHARGE_SCHOOL_FEES:
        return 1, None
    try:
        term_n = int(term or 1)
    except (TypeError, ValueError):
        term_n = 1
    if term_n not in (1, 2):
        term_n = 1
    try:
        inst_n = int(installment) if installment not in (None, '') else 1
    except (TypeError, ValueError):
        inst_n = 1
    if inst_n not in (0, 1, 2, 3):
        inst_n = 1
    return term_n, inst_n


def present_student_charge(payment):
    """Student-facing ledger line for any institutional receipt."""
    bucket = classify_student_payment(payment)
    show_period = bucket == CHARGE_SCHOOL_FEES
    return {
        'payment': payment,
        'bucket': bucket,
        'kind_label': fee_kind_label(getattr(payment, 'fee_kind', None)),
        'counts_yearly': bucket in YEARLY_CHARGE_BUCKETS,
        'show_period': show_period,
        'period_label': billing_period_label(payment.term, payment.installment) if show_period else '',
        'bucket_label': {
            CHARGE_SCHOOL_FEES: 'School fees',
            CHARGE_REGISTRATION: 'Registration',
            CHARGE_OTHER: 'Other school charge',
        }.get(bucket, 'School charge'),
    }


def _split_three(total):
    amount = Decimal(str(total or 0))
    if amount <= 0:
        return [Decimal('0.00'), Decimal('0.00'), Decimal('0.00')]
    share = (amount / 3).quantize(Decimal('0.01'))
    third = amount - (share * 2)
    return [share, share, third]


def build_school_fee_plan(yearly_fee, payments):
    """Yearly school fee collected in three installments (not three per semester)."""
    yearly = Decimal(str(yearly_fee or 0))
    dues = _split_three(yearly)
    rows = [p for p in (payments or []) if is_school_fee_payment(p)]
    tagged = {1: Decimal('0'), 2: Decimal('0'), 3: Decimal('0')}
    full_extra = Decimal('0')
    for payment in rows:
        amount = Decimal(str(payment.amount_paid or 0))
        try:
            inst = int(payment.installment) if payment.installment is not None else INSTALLMENT_FULL
        except (TypeError, ValueError):
            inst = INSTALLMENT_FULL
        if inst in (1, 2, 3):
            tagged[inst] += amount
        else:
            full_extra += amount
    leftover = full_extra
    installments = []
    year_paid = Decimal('0')
    suggested_installment = 1
    found_open = False
    for index in (1, 2, 3):
        due = dues[index - 1]
        paid = tagged[index]
        need = due - paid if due > paid else Decimal('0')
        take = need if leftover > need else leftover
        if take < 0:
            take = Decimal('0')
        paid += take
        leftover -= take
        year_paid += paid
        if due > 0 and paid >= due:
            status = 'paid'
        elif paid > 0:
            status = 'partial'
        else:
            status = 'open'
        if not found_open and status != 'paid':
            suggested_installment = index
            found_open = True
        installments.append({
            'id': index,
            'label': installment_label(index),
            'due': float(due),
            'paid': float(paid),
            'balance': float(due - paid if due > paid else Decimal('0')),
            'status': status,
        })
    if leftover > 0 and installments:
        installments[-1]['paid'] = float(Decimal(str(installments[-1]['paid'])) + leftover)
        year_paid += leftover
        if yearly and Decimal(str(installments[-1]['paid'])) >= dues[2]:
            installments[-1]['status'] = 'paid'
            installments[-1]['balance'] = 0.0
    suggested_due = Decimal('0')
    for slot in installments:
        if slot['id'] == suggested_installment:
            suggested_due = Decimal(str(slot['balance'] or slot['due'] or 0))
            break
    suggested_term = 2 if suggested_installment == 3 else 1
    year_balance = yearly - year_paid if yearly > year_paid else Decimal('0')
    return {
        'yearly_fee': float(yearly),
        'semester_fee': float(yearly),
        'installment_fee': float(dues[0]),
        'year_paid': float(year_paid),
        'year_balance': float(year_balance),
        'installments': installments,
        'semesters': [{
            'id': 0,
            'label': 'School year',
            'due': float(yearly),
            'paid': float(year_paid),
            'balance': float(year_balance),
            'installments': installments,
        }],
        'suggested_term': suggested_term,
        'suggested_installment': suggested_installment,
        'suggested_amount': float(suggested_due if suggested_due > 0 else dues[0]),
    }


def registry_payment_description(fee_kind, extra=None, receipt_reference=None, term=None, installment=None):
    label = fee_kind_label(fee_kind)
    parts = [f'Registry Day Book — {label}']
    if payment_shows_semester_installment(fee_kind=fee_kind) and term is not None:
        parts.append(billing_period_label(term, installment))
    extra = (extra or '').strip()
    if extra:
        parts.append(extra)
    ref = (receipt_reference or '').strip()
    if ref:
        parts.append(f'(Ref: {ref})')
    return ' '.join(parts)[:250]


def next_registry_receipt_number(business_date=None):
    """REG-YYYY-00001 sequential per calendar year."""
    day = school_business_date(business_date)
    prefix = f'REG-{day.year}-'
    last = (
        StudentPayment.query.filter(StudentPayment.receipt_number.like(f'{prefix}%'))
        .order_by(StudentPayment.id.desc())
        .first()
    )
    serial = 1
    if last and last.receipt_number:
        tail = (last.receipt_number or '').split('-')[-1]
        try:
            serial = int(tail) + 1
        except (TypeError, ValueError):
            serial = 1
    return f'{prefix}{serial:05d}'


def _registry_desk_filter():
    return db.or_(
        StudentPayment.collection_desk == COLLECTION_DESK_REGISTRY,
        StudentPayment.receipt_number.ilike('REG-%'),
        StudentPayment.description.ilike('Registry Day Book%'),
    )


def registry_takings_query(business_date, academic_year_id=None):
    day = school_business_date(business_date)
    start = datetime(day.year, day.month, day.day)
    end = datetime(day.year, day.month, day.day, 23, 59, 59)
    query = StudentPayment.query.filter(
        StudentPayment.paid_on >= start,
        StudentPayment.paid_on <= end,
        _registry_desk_filter(),
    )
    if academic_year_id:
        query = query.filter(StudentPayment.academic_year_id == academic_year_id)
    return query.order_by(StudentPayment.paid_on.asc(), StudentPayment.id.asc())


def totals_by_currency(payments):
    buckets = {CURRENCY_USD: Decimal('0'), CURRENCY_LRD: Decimal('0')}
    for row in payments or []:
        code = normalize_currency(getattr(row, 'currency', None))
        buckets[code] = buckets.get(code, Decimal('0')) + Decimal(str(row.amount_paid or 0))
    return {key: float(value) for key, value in buckets.items()}


def money_label_for_payments(payments, fallback_total=0):
    rows = list(payments or [])
    if rows:
        return format_dual_money(totals_by_currency(rows))
    return format_school_money(fallback_total, CURRENCY_USD)


def summarize_registry_till(business_date=None, academic_year_id=None):
    install_money_filters()
    day = school_business_date(business_date)
    payments = registry_takings_query(day, academic_year_id).all()
    totals = totals_by_currency(payments)
    total = Decimal(str(totals.get(CURRENCY_USD) or 0)) + Decimal(str(totals.get(CURRENCY_LRD) or 0))
    numbers = [row.receipt_number for row in payments if row.receipt_number]
    handover = RegistryDailyHandover.query.filter_by(business_date=day).first()
    status = handover.status if handover else HANDOVER_OPEN
    return {
        'date': day,
        'payments': payments,
        'count': len(payments),
        'total': float(total),
        'totals_by_currency': totals,
        'total_label': format_dual_money(totals),
        'first_receipt_no': numbers[0] if numbers else None,
        'last_receipt_no': numbers[-1] if numbers else None,
        'handover': handover,
        'status': status,
        'can_collect': day == school_business_date() and status not in (HANDOVER_SUBMITTED, HANDOVER_ACKNOWLEDGED),
        'is_draft': status == HANDOVER_OPEN,
        'dispatched': status in (HANDOVER_SUBMITTED, HANDOVER_ACKNOWLEDGED) and bool(payments),
    }


def ensure_open_handover(business_date, academic_year_id, user_id):
    day = school_business_date(business_date)
    row = RegistryDailyHandover.query.filter_by(business_date=day).first()
    if row:
        return row
    row = RegistryDailyHandover(
        business_date=day,
        academic_year_id=academic_year_id,
        opened_by_user_id=user_id,
        status=HANDOVER_OPEN,
    )
    db.session.add(row)
    db.session.flush()
    return row


def refresh_registry_draft(when=None, academic_year_id=None, user_id=None):
    """Keep today's clerk draft up to date. Does not send it to Business."""
    day = school_business_date(when)
    till = summarize_registry_till(day, academic_year_id=None)
    if till['count'] == 0 and not till['handover']:
        return None
    handover = till['handover'] or ensure_open_handover(day, academic_year_id, user_id)
    handover.academic_year_id = academic_year_id or handover.academic_year_id
    if user_id and not handover.opened_by_user_id:
        handover.opened_by_user_id = user_id
    if handover.status in (HANDOVER_SUBMITTED, HANDOVER_ACKNOWLEDGED):
        return handover
    handover.receipt_count = till['count']
    handover.total_amount = till['total']
    handover.first_receipt_no = till['first_receipt_no']
    handover.last_receipt_no = till['last_receipt_no']
    for payment in till['payments']:
        payment.handover_id = handover.id
    db.session.flush()
    return handover


def submit_registry_daily_report(when=None, academic_year_id=None, user_id=None, notes=None):
    """Clerk has checked the draft; send the bound sheet to the Business Manager."""
    handover = refresh_registry_draft(when, academic_year_id, user_id)
    till = summarize_registry_till(when)
    if not handover or till['count'] == 0:
        return None, False
    if handover.status != HANDOVER_OPEN:
        return handover, False
    handover.status = HANDOVER_SUBMITTED
    handover.closed_by_user_id = user_id
    handover.receipt_count = till['count']
    handover.total_amount = till['total']
    handover.first_receipt_no = till['first_receipt_no']
    handover.last_receipt_no = till['last_receipt_no']
    if notes is not None:
        handover.notes = (notes or '').strip() or None
    handover.submitted_at = datetime.now(timezone.utc)
    for payment in till['payments']:
        payment.handover_id = handover.id
    db.session.flush()
    return handover, True


def publish_registry_daily_report(when=None, academic_year_id=None, user_id=None, notes=None):
    """Back-compat alias: refresh the clerk draft without sending."""
    return refresh_registry_draft(when, academic_year_id, user_id)


def close_registry_day(business_date, academic_year_id, user_id, notes=None):
    return submit_registry_daily_report(business_date, academic_year_id, user_id, notes=notes)


def pending_registry_handovers():
    return (
        RegistryDailyHandover.query.filter(
            RegistryDailyHandover.status.in_((HANDOVER_SUBMITTED, HANDOVER_ACKNOWLEDGED)),
        )
        .order_by(RegistryDailyHandover.business_date.desc(), RegistryDailyHandover.id.desc())
        .all()
    )


def recent_registry_daily_reports(limit=14):
    return (
        RegistryDailyHandover.query.filter(RegistryDailyHandover.receipt_count > 0)
        .order_by(RegistryDailyHandover.business_date.desc(), RegistryDailyHandover.id.desc())
        .limit(limit)
        .all()
    )
