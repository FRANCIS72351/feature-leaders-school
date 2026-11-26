"""Future Leaders Preparatory Academy — Brevo SMTP mailer.

Reads SMTP_LOGIN / SMTP_PASSWORD from the environment (never from source).
The From address must be a sender Brevo has verified (SENDER_EMAIL).
"""
from __future__ import annotations

import argparse
import html
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SCHOOL_NAME = 'Future Leaders Preparatory Academy'
_PLACEHOLDER_EMAIL_HINTS = (
    'example.com', 'example.org', 'example.net', 'test.com', 'localhost',
    'flpa.local', 'school.local', '.invalid', 'noreply@', 'noemail@',
    'placeholder', 'changeme@', 'n/a', 'na@',
)


def normalize_account_email(value):
    return (value or '').strip().lower()


def account_email_looks_deliverable(value):
    """False for blank, school placeholders, or addresses that cannot receive mail."""
    email = normalize_account_email(value)
    if not email or '@' not in email:
        return False
    local, _, domain = email.partition('@')
    if not local or not domain or '.' not in domain:
        return False
    if any(hint in email for hint in _PLACEHOLDER_EMAIL_HINTS):
        return False
    return True


DEFAULT_SMTP_HOST = 'smtp-relay.brevo.com'
DEFAULT_SMTP_PORT = 587
DEFAULT_SENDER_EMAIL = 'flpaschool.notice@flpa2015.com'
OFFICIAL_SENDER_DOMAIN = 'flpa2015.com'
_CONSUMER_SENDER_DOMAINS = frozenset({
    'gmail.com', 'googlemail.com', 'yahoo.com', 'ymail.com',
    'outlook.com', 'hotmail.com', 'live.com', 'msn.com',
    'icloud.com', 'me.com', 'aol.com', 'protonmail.com',
})
DEFAULT_PUBLIC_SITE = 'https://flpa2015.com'
BRAND_RED = '#c82828'
BRAND_NAVY = '#101820'
SCHOOL_ADDRESS = 'Center Street, South Beach, Monrovia, Liberia'
SCHOOL_PHONES = '0886-612-070 / 0775-313-359'
_LOCAL_LINK_HINTS = (
    'localhost', '127.0.0.1', '0.0.0.0', '::1',
    'devtunnels.ms', 'ngrok', 'trycloudflare.com',
)


def _load_local_env():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _env(name, default=''):
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else default


_SENDER_OVERRIDE_LOGGED = False


def official_sender_email(value=None):
    """Portal From-address must be @flpa2015.com so Brevo can DKIM-sign the school domain."""
    global _SENDER_OVERRIDE_LOGGED
    raw = (value or '').strip()
    addr = _valid_address(value) or DEFAULT_SENDER_EMAIL
    domain = addr.rsplit('@', 1)[-1].lower()
    if domain != OFFICIAL_SENDER_DOMAIN or domain in _CONSUMER_SENDER_DOMAINS:
        if raw and normalize_account_email(raw) != DEFAULT_SENDER_EMAIL and not _SENDER_OVERRIDE_LOGGED:
            logger.info(
                'SENDER_EMAIL=%s is not @%s; notices send as %s',
                raw,
                OFFICIAL_SENDER_DOMAIN,
                DEFAULT_SENDER_EMAIL,
            )
            _SENDER_OVERRIDE_LOGGED = True
        return DEFAULT_SENDER_EMAIL
    return addr


def mail_config():
    """Live Brevo/SMTP settings from the process environment."""
    port_raw = _env('SMTP_PORT') or str(DEFAULT_SMTP_PORT)
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = DEFAULT_SMTP_PORT
    sender_email = official_sender_email(_env('SENDER_EMAIL') or DEFAULT_SENDER_EMAIL)
    sender_name = _env('SENDER_NAME') or SCHOOL_NAME
    reply_to = official_sender_email(
        _env('SMTP_REPLY_TO') or _env('REPLY_TO_EMAIL') or sender_email
    )
    return {
        'host': _env('SMTP_SERVER') or DEFAULT_SMTP_HOST,
        'port': port,
        'username': _env('SMTP_LOGIN') or _env('SMTP_USERNAME') or _env('MAIL_USERNAME'),
        'password': _env('SMTP_PASSWORD') or _env('MAIL_PASSWORD'),
        'sender_email': sender_email,
        'sender_name': sender_name,
        'reply_to': reply_to,
        'site_url': (_env('SITE_URL') or _env('PUBLIC_SITE_URL') or DEFAULT_PUBLIC_SITE).rstrip('/'),
        'use_ssl': port == 465 or _env('SMTP_SSL').lower() in ('1', 'true', 'yes'),
    }


def sender_domain(cfg=None):
    cfg = cfg or mail_config()
    email = (cfg.get('sender_email') or DEFAULT_SENDER_EMAIL).strip()
    if '@' in email:
        return email.rsplit('@', 1)[-1].lower()
    return 'flpa2015.com'


def _host_is_local_or_tunnel(host):
    host = (host or '').lower()
    return any(hint in host for hint in _LOCAL_LINK_HINTS)


def public_site_base(cfg=None):
    """HTTPS school origin for links inside mail. Local/tunnel hosts go to spam."""
    cfg = cfg or mail_config()
    raw = (cfg.get('site_url') or DEFAULT_PUBLIC_SITE).strip() or DEFAULT_PUBLIC_SITE
    if '://' not in raw:
        raw = 'https://' + raw
    parsed = urlparse(raw)
    if parsed.scheme != 'https' or _host_is_local_or_tunnel(parsed.hostname):
        return DEFAULT_PUBLIC_SITE
    return raw.rstrip('/')


def public_absolute_url(path_or_url, cfg=None):
    """Turn a portal path (or a Flask absolute URL) into a public https://flpa2015.com link."""
    base = public_site_base(cfg)
    value = (path_or_url or '').strip() or '/'
    if value.startswith('http://') or value.startswith('https://'):
        parsed = urlparse(value)
        path = parsed.path or '/'
        if parsed.query:
            path = f'{path}?{parsed.query}'
        if _host_is_local_or_tunnel(parsed.hostname) or parsed.scheme != 'https':
            return base + path
        return value
    if not value.startswith('/'):
        value = '/' + value
    return base + value


def mailer_configured(cfg=None):
    cfg = cfg or mail_config()
    return bool(cfg['username'] and cfg['password'] and cfg['sender_email'])


def mailer_status():
    """Safe diagnostic dict (never includes the SMTP key)."""
    cfg = mail_config()
    return {
        'configured': mailer_configured(cfg),
        'host': cfg['host'],
        'port': cfg['port'],
        'username': cfg['username'],
        'sender': formataddr((cfg['sender_name'], cfg['sender_email'])) if cfg['sender_email'] else '',
        'sender_domain': sender_domain(cfg),
        'site_url': cfg['site_url'],
        'use_ssl': cfg['use_ssl'],
    }


def _valid_address(value):
    name, addr = parseaddr(value or '')
    addr = (addr or '').strip()
    if '@' not in addr or addr.startswith('@') or addr.endswith('@'):
        return None
    return addr


def _unique_addresses(values):
    seen = set()
    out = []
    for value in values or []:
        addr = _valid_address(value)
        if not addr:
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(addr)
    return out


def _esc(value):
    if value is None or value == '':
        return ''
    return html.escape(str(value), quote=True)


def _branded_html(title, intro, details, footer_note=None, button_url=None, button_label=None):
    rows = ''.join(
        f'<tr><td style="padding:6px 0;color:#6f625a;width:34%;">{_esc(label)}</td>'
        f'<td style="padding:6px 0;color:{BRAND_NAVY};font-weight:600;">{_esc(value)}</td></tr>'
        for label, value in (details or [])
        if value
    )
    button = ''
    if button_url:
        safe_url = _esc(button_url)
        button = (
            f'<p style="margin:28px 0 10px;">'
            f'<a href="{safe_url}" style="background:{BRAND_NAVY};color:#fff;text-decoration:none;'
            f'padding:12px 22px;border-radius:6px;font-weight:700;display:inline-block;">'
            f'{_esc(button_label or "Open FLPA Portal")}</a></p>'
            f'<p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#374151;word-break:break-all;">'
            f'Or paste this school link into your browser:<br>'
            f'<a href="{safe_url}" style="color:{BRAND_NAVY};">{safe_url}</a></p>'
        )
    note = _esc(footer_note) or (
        'This is an official notice from Future Leaders Preparatory Academy. '
        'If you were not expecting it, you may ignore it.'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:Georgia,Times New Roman,serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">
    Official notice from Future Leaders Preparatory Academy, Monrovia.
  </div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f4f5;padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;background:#fff;border:1px solid #d4d4d8;">
        <tr>
          <td style="background:{BRAND_NAVY};color:#fff;padding:20px 28px;font-family:Arial,Helvetica,sans-serif;">
            <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#d4af37;">Official school mail</div>
            <div style="font-size:18px;font-weight:700;margin-top:6px;">{SCHOOL_NAME}</div>
          </td>
        </tr>
        <tr>
          <td style="padding:28px;font-family:Arial,Helvetica,sans-serif;">
            <h1 style="margin:0 0 12px;font-size:18px;color:{BRAND_NAVY};">{_esc(title)}</h1>
            <p style="margin:0 0 18px;line-height:1.6;color:#211715;">{_esc(intro)}</p>
            {'<table role="presentation" width="100%" cellspacing="0" cellpadding="0">' + rows + '</table>' if rows else ''}
            {button}
            <p style="margin:24px 0 0;font-size:13px;color:#52525b;line-height:1.5;">{note}</p>
          </td>
        </tr>
        <tr>
          <td style="background:#fafafa;padding:14px 28px;font-size:12px;color:#52525b;border-top:1px solid #e4e4e7;font-family:Arial,Helvetica,sans-serif;line-height:1.55;">
            {SCHOOL_NAME}<br>
            {SCHOOL_ADDRESS}<br>
            Telephone: {SCHOOL_PHONES}<br>
            Website: {DEFAULT_PUBLIC_SITE}
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_message(
    *,
    to_addrs,
    subject,
    body_text,
    html_body=None,
    reply_to=None,
    cc=None,
    bcc=None,
    cfg=None,
    mail_kind='transactional',
):
    cfg = cfg or mail_config()
    recipients = _unique_addresses(to_addrs if isinstance(to_addrs, (list, tuple, set)) else [to_addrs])
    if not recipients:
        raise ValueError('A valid recipient email is required.')
    if not (subject or '').strip():
        raise ValueError('A subject is required.')

    domain = sender_domain(cfg)
    site = public_site_base(cfg)
    msg = EmailMessage()
    msg['Subject'] = ' '.join((subject or '').split())
    msg['From'] = formataddr((cfg['sender_name'], cfg['sender_email']))
    msg['To'] = ', '.join(recipients)
    cc_addrs = _unique_addresses(cc)
    bcc_addrs = _unique_addresses(bcc)
    if cc_addrs:
        msg['Cc'] = ', '.join(cc_addrs)
    reply = _valid_address(reply_to or cfg['reply_to'] or cfg['sender_email'])
    if reply:
        msg['Reply-To'] = reply
    msg['Date'] = formatdate(usegmt=True)
    msg['Message-ID'] = make_msgid(domain=domain)
    msg['List-Id'] = f'FLPA Portal notices <notices.{domain}>'
    msg['List-Help'] = f'<{site}/contact>'
    msg['Organization'] = SCHOOL_NAME
    msg['X-Auto-Response-Suppress'] = 'All'
    msg['Auto-Submitted'] = 'auto-generated'
    msg['X-Mailin-Tag'] = f'flpa-{mail_kind}'
    msg['X-Mailin-custom'] = mail_kind
    if mail_kind != 'transactional':
        unsub = public_absolute_url('/mail/unsubscribe', cfg)
        msg['List-Unsubscribe'] = f'<{unsub}>, <mailto:{cfg["sender_email"]}?subject=unsubscribe>'
        msg['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'
    msg.set_content(body_text or '')
    if html_body:
        msg.add_alternative(html_body, subtype='html')
    envelope_to = _unique_addresses(recipients + cc_addrs + bcc_addrs)
    return msg, envelope_to


def _smtp_error_text(exc):
    raw = getattr(exc, 'smtp_error', None) or getattr(exc, 'args', (exc,))[0]
    if isinstance(raw, bytes):
        return raw.decode('utf-8', errors='replace')
    return str(raw or exc)


def _send_message(msg, envelope_to, cfg=None):
    cfg = cfg or mail_config()
    if not mailer_configured(cfg):
        logger.warning('School mailer is not configured (SMTP_LOGIN / SMTP_PASSWORD / SENDER_EMAIL).')
        return False
    context = ssl.create_default_context()
    logger.info(
        'Sending school mail via %s:%s to %s',
        cfg['host'],
        cfg['port'],
        ', '.join(envelope_to),
    )
    try:
        if cfg['use_ssl']:
            with smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=20, context=context) as server:
                server.login(cfg['username'], cfg['password'])
                server.send_message(msg, to_addrs=envelope_to)
        else:
            with smtplib.SMTP(cfg['host'], cfg['port'], timeout=20) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(cfg['username'], cfg['password'])
                server.send_message(msg, to_addrs=envelope_to)
    except smtplib.SMTPAuthenticationError as exc:
        detail = _smtp_error_text(exc)
        if 'unauthorized ip' in detail.lower() or '525' in str(exc):
            logger.error(
                'Brevo blocked this computer IP for SMTP (%s). '
                'Authorize it in Brevo: Settings → Security → Authorized IPs.',
                detail,
            )
        else:
            logger.error('SMTP login failed: %s', detail)
        return False
    return True


def send_school_email(
    recipient_email,
    subject,
    body_text,
    html_body=None,
    *,
    cc=None,
    bcc=None,
    reply_to=None,
    mail_kind='transactional',
):
    """Send one notice through Brevo. Returns True on success, False on failure."""
    try:
        msg, envelope_to = build_message(
            to_addrs=recipient_email,
            subject=subject,
            body_text=body_text,
            html_body=html_body,
            reply_to=reply_to,
            cc=cc,
            bcc=bcc,
            mail_kind=mail_kind,
        )
        return _send_message(msg, envelope_to)
    except Exception:
        logger.exception('School mail failed for %s', recipient_email)
        return False


def send_many(addresses, subject, body_text, html_body=None, *, mail_kind='notice'):
    """Send the same notice to many addresses. Returns (sent, failed)."""
    sent = 0
    failed = 0
    for addr in _unique_addresses(addresses):
        if send_school_email(addr, subject, body_text, html_body=html_body, mail_kind=mail_kind):
            sent += 1
        else:
            failed += 1
    return sent, failed


def send_email_verification(email, full_name, verify_url, *, changing=False):
    """Ask the new (or current) inbox to confirm before FLPA notices switch over."""
    name = (full_name or 'Colleague').strip()
    verify_url = public_absolute_url(verify_url)
    if changing:
        subject = f'{SCHOOL_NAME}: confirm this school email'
        intro = (
            f'Dear {name}, the FLPA Portal school office requested that notices for your account '
            'be delivered to this address. Open the school link below only if you asked for that change.'
        )
        note = (
            'Your current portal email stays active until you confirm this address. '
            'After you confirm, the school site opens the sign-in page so you can enter your password. '
            'The link expires in 24 hours.'
        )
        button = 'Confirm this school email'
    else:
        subject = f'{SCHOOL_NAME}: confirm this school email'
        intro = (
            f'Dear {name}, please confirm this address so Future Leaders Preparatory Academy '
            'can send you official portal notices from the school office.'
        )
        note = 'If you did not request this, you may ignore the message. The link expires in 24 hours.'
        button = 'Confirm this school email'
    text = (
        f'{intro}\n\nSchool link (expires in 24 hours):\n{verify_url}\n\n'
        f'{SCHOOL_NAME}\n{SCHOOL_ADDRESS}\n'
    )
    html = _branded_html(
        subject.replace(f'{SCHOOL_NAME} ', ''),
        intro,
        [('Inbox', email)],
        footer_note=note + ' This link expires in 24 hours.',
        button_url=verify_url,
        button_label=button,
    )
    return send_school_email(email, subject, text, html_body=html)


def send_email_verified_notice(email, full_name):
    """Tell the owner that real-time FLPA notices are now active on this inbox."""
    name = (full_name or 'Colleague').strip()
    login_url = public_absolute_url('/login')
    subject = f'{SCHOOL_NAME}: this email is confirmed'
    text = (
        f'Dear {name},\n\n'
        'This inbox is now the verified email for your FLPA Portal account. '
        'You will receive real-time school notices here.\n\n'
        f'{login_url}\n\n{SCHOOL_NAME}\n'
    )
    html = _branded_html(
        'Notices are active here',
        f'Dear {name}, this inbox is verified. Real-time FLPA Portal alerts will arrive here.',
        [('Verified email', email)],
        button_url=login_url,
        button_label='Open FLPA Portal',
    )
    return send_school_email(email, subject, text, html_body=html)


def send_account_ready_email(email, full_name, role, *, login_hint=None):
    """Welcome a new staff or student account. Never includes a password."""
    name = (full_name or 'Colleague').strip()
    role_label = (role or 'portal').replace('_', ' ').title()
    login_url = public_absolute_url('/login')
    subject = f'{SCHOOL_NAME}: your portal account is ready'
    text = (
        f'Dear {name},\n\n'
        f'An FLPA Portal account has been created for you as {role_label}.\n'
        f'Sign in at {login_url}\n'
        + (f'Username / Student ID: {login_hint}\n' if login_hint else '')
        + '\nUse the password given to you by the school office. '
        'Change it after your first sign-in.\n\n'
        f'{SCHOOL_NAME}\n'
    )
    html = _branded_html(
        'Your portal account is ready',
        f'Dear {name}, the school has opened your FLPA Portal account.',
        [
            ('Name', name),
            ('Role', role_label),
            ('Sign-in email', email),
            ('Student ID', login_hint),
        ],
        footer_note='Use the password given by the school office. Change it after your first sign-in.',
        button_url=login_url,
        button_label='Sign in to FLPA Portal',
    )
    return send_school_email(email, subject, text, html_body=html)


def send_password_changed_notice(email, full_name):
    """Tell the account holder that office staff reset their password. No secret in the mail."""
    name = (full_name or 'Colleague').strip()
    login_url = public_absolute_url('/login')
    subject = f'{SCHOOL_NAME}: portal password was changed'
    text = (
        f'Dear {name},\n\n'
        'The school office updated the password on your FLPA Portal account. '
        'Sign in with the password they gave you.\n\n'
        f'{login_url}\n\n{SCHOOL_NAME}\n'
    )
    html = _branded_html(
        'Your portal password was updated',
        f'Dear {name}, the school office changed the password on this account.',
        [('Sign-in email', email)],
        footer_note='If you did not request this, contact the school office immediately.',
        button_url=login_url,
        button_label='Sign in to FLPA Portal',
    )
    return send_school_email(email, subject, text, html_body=html)


def send_class_activity_notice(
    emails,
    *,
    class_name,
    title,
    subject_name,
    period_label,
    teacher_name,
    description=None,
    due_date=None,
):
    """Notify parents/students that a class activity was posted."""
    portal = public_absolute_url('/login')
    due = due_date.strftime('%d %b %Y') if hasattr(due_date, 'strftime') else (due_date or '')
    subject = f'{SCHOOL_NAME}: class activity for {subject_name or class_name}'
    text = (
        f'A new activity was posted for {class_name}.\n\n'
        f'Title: {title}\n'
        f'Subject: {subject_name or "—"}\n'
        f'Period: {period_label or "—"}\n'
        f'Teacher: {teacher_name or "—"}\n'
        + (f'Due: {due}\n' if due else '')
        + (f'\n{description}\n' if description else '')
        + f'\nOpen My Tasks in the student portal: {portal}\n'
    )
    html = _branded_html(
        'New class activity',
        f'A new activity was posted for {class_name}.',
        [
            ('Activity', title),
            ('Subject', subject_name),
            ('Period', period_label),
            ('Teacher', teacher_name),
            ('Due', due),
            ('Notes', description),
        ],
        button_url=portal,
        button_label='Open student portal',
    )
    return send_many(emails, subject, text, html_body=html)


def _format_notice_score(score, max_score=None):
    def _fmt(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value) if value is not None else '—'
        if number.is_integer():
            return str(int(number))
        return f'{number:g}'

    if score is None or score == '':
        shown = '—'
    else:
        shown = _fmt(score)
    if max_score is None or max_score == '':
        return shown
    return f'{shown} / {_fmt(max_score)}'


def _grade_visibility_label(visibility):
    if (visibility or '').strip().lower() == 'published':
        return 'Submitted for academic release'
    return 'Live draft on My Grades'


def compose_student_grade_update(
    *,
    student_name,
    class_name,
    teacher_name,
    items,
    first_name=None,
):
    """Build subject/text/html for a live student grade notice. Does not send mail."""
    given = (first_name or student_name or 'Student').strip().split()[0] or 'Student'
    rows = [item for item in (items or []) if item]
    if not rows:
        raise ValueError('At least one grade line is required.')
    visibilities = {(item.get('visibility') or 'draft').strip().lower() for item in rows}
    all_published = visibilities == {'published'}
    grades_url = public_absolute_url('/student/dashboard?tab=grades')
    if all_published:
        subject = f'{SCHOOL_NAME}: {given}, a score was submitted for academic release'
        title = 'Score submitted for academic release'
        intro = (
            f'Dear {given}, your teacher just submitted a score on the FLPA Portal. '
            'You can open My Grades now to see this standing. The official report card '
            'is issued only after the academic office stamps the period.'
        )
        footer = (
            'This is a live school notice sent the moment the score was saved. '
            'A submitted standing is not the same as a released report card or Official Transcript.'
        )
    else:
        subject = f'{SCHOOL_NAME}: {given}, a live score was posted'
        title = 'Live score posted on My Grades'
        intro = (
            f'Dear {given}, your teacher just recorded a score on the FLPA Portal. '
            'This is a live classroom standing. It is not yet the official report card.'
        )
        footer = (
            'This notice went out as soon as the teacher saved. '
            'If the period is later submitted for academic release, you will receive another notice.'
        )

    details = [
        ('Student', student_name),
        ('Class', class_name),
        ('Teacher', teacher_name),
    ]
    text_lines = [
        intro,
        '',
        f'Student: {student_name or "—"}',
        f'Class: {class_name or "—"}',
        f'Teacher: {teacher_name or "—"}',
        '',
    ]
    for index, item in enumerate(rows, 1):
        prefix = f'{index}. ' if len(rows) > 1 else ''
        work = ' · '.join(
            part for part in (
                item.get('subject'),
                item.get('period_label'),
                item.get('title'),
            ) if part
        ) or 'Score'
        score_text = item.get('score_text') or _format_notice_score(
            item.get('score'), item.get('max_score'),
        )
        status = _grade_visibility_label(item.get('visibility'))
        note = (item.get('note') or '').strip()
        details.append((f'{prefix}{work}', f'{score_text} · {status}'))
        if note:
            details.append(('Teacher note', note))
        text_lines.append(f'{prefix}{work}: {score_text} ({status})')
        if note:
            text_lines.append(f'  Note: {note}')
    text_lines.extend(['', f'Open My Grades: {grades_url}', '', SCHOOL_NAME, SCHOOL_ADDRESS])
    html = _branded_html(
        title,
        intro,
        details,
        footer_note=footer,
        button_url=grades_url,
        button_label='Open My Grades',
    )
    return subject, '\n'.join(text_lines), html


def send_student_grade_update(emails, **kwargs):
    """Email the student (and household inboxes) a live grade notice."""
    subject, text, html = compose_student_grade_update(**kwargs)
    return send_many(emails, subject, text, html_body=html, mail_kind='transactional')


def compose_digital_payment_receipt(
    *,
    student_name,
    student_id=None,
    first_name=None,
    class_name=None,
    receipt_number=None,
    amount_text=None,
    particulars=None,
    fee_label=None,
    academic_year=None,
    paid_on=None,
    collected_at=None,
    received_by=None,
    balance_text=None,
    charge_note=None,
):
    """Build subject/text/html for a live digital payment receipt. Does not send mail."""
    given = (first_name or student_name or 'Family').strip().split()[0] or 'Family'
    receipt_no = (receipt_number or '').strip() or 'Pending office number'
    amount = (amount_text or '').strip() or '—'
    work = (particulars or fee_label or 'School payment').strip()
    portal = public_absolute_url('/student/dashboard?tab=account')
    subject = f'{SCHOOL_NAME}: digital receipt {receipt_no}'
    title = 'Digital receipt'
    intro = (
        f'Dear {given}, the school has recorded a payment on the FLPA account for '
        f'{student_name or "this student"}. This message is your live digital receipt.'
    )
    footer = (
        'Keep this message. It is an official electronic receipt from Future Leaders '
        'Preparatory Academy, Center Street, South Beach, Monrovia. A printed copy '
        'remains available at the office that collected the payment.'
    )
    details = [
        ('Receipt no.', receipt_no),
        ('Amount received', amount),
        ('For', work),
        ('Charge type', fee_label),
        ('Student', student_name),
        ('Student ID', student_id),
        ('Class', class_name),
        ('Academic year', academic_year),
        ('Date recorded', paid_on),
        ('Collected at', collected_at),
        ('Received by', received_by),
        ('School-fee balance', balance_text),
        ('Note', charge_note),
    ]
    text = (
        f'{intro}\n\n'
        f'Receipt no.: {receipt_no}\n'
        f'Amount received: {amount}\n'
        f'For: {work}\n'
        f'Student: {student_name or "—"} ({student_id or "—"})\n'
        f'Class: {class_name or "—"}\n'
        f'Academic year: {academic_year or "—"}\n'
        f'Date recorded: {paid_on or "—"}\n'
        f'Collected at: {collected_at or "—"}\n'
        f'Received by: {received_by or "—"}\n'
        + (f'School-fee balance: {balance_text}\n' if balance_text else '')
        + (f'{charge_note}\n' if charge_note else '')
        + f'\nOpen My Account: {portal}\n\n{SCHOOL_NAME}\n{SCHOOL_ADDRESS}\n'
    )
    html = _branded_html(
        title,
        intro,
        details,
        footer_note=footer,
        button_url=portal,
        button_label='Open My Account',
    )
    return subject, text, html


def send_digital_payment_receipt(emails, **kwargs):
    """Email the household a live digital receipt for a recorded payment."""
    subject, text, html = compose_digital_payment_receipt(**kwargs)
    return send_many(emails, subject, text, html_body=html, mail_kind='transactional')


def compose_proprietor_transaction_notice(
    *,
    kind='income',
    amount_text=None,
    particulars=None,
    party=None,
    receipt_number=None,
    collected_at=None,
    recorded_by=None,
    academic_year=None,
    paid_on=None,
    method=None,
):
    """Build the Proprietor live-till notice. Does not send mail."""
    kind_label = (kind or 'transaction').strip().lower()
    if kind_label in ('expense', 'payout', 'salary'):
        heading = 'Live till · money went out'
        verb = 'An expense was posted on the FLPA Portal.'
    elif kind_label in ('fee', 'payment', 'income'):
        heading = 'Live till · money came in'
        verb = 'A payment was posted on the FLPA Portal.'
    else:
        heading = 'Live till · ledger movement'
        verb = 'A business transaction was posted on the FLPA Portal.'
    amount = (amount_text or '').strip() or '—'
    subject = f'{SCHOOL_NAME}: {heading} · {amount}'
    intro = (
        f'Dear Proprietor, {verb} This is your live oversight copy. '
        'No action is required unless the amount or desk is unexpected.'
    )
    portal = public_absolute_url('/proprietor/dashboard')
    details = [
        ('Movement', heading.replace('Live till · ', '').title()),
        ('Amount', amount),
        ('Particulars', particulars),
        ('Student / party', party),
        ('Receipt / ref', receipt_number),
        ('Method', method),
        ('Desk', collected_at),
        ('Recorded by', recorded_by),
        ('Academic year', academic_year),
        ('When', paid_on),
    ]
    text = (
        f'{intro}\n\n'
        f'Amount: {amount}\n'
        f'Particulars: {particulars or "—"}\n'
        f'Party: {party or "—"}\n'
        f'Receipt: {receipt_number or "—"}\n'
        f'Desk: {collected_at or "—"}\n'
        f'Recorded by: {recorded_by or "—"}\n'
        f'When: {paid_on or "—"}\n'
        f'\nLive school board: {portal}\n\n{SCHOOL_NAME}\n{SCHOOL_ADDRESS}\n'
    )
    html = _branded_html(
        heading,
        intro,
        details,
        footer_note=(
            'This notice is sent the moment the till or ledger is saved. '
            'It is for the School Proprietor only.'
        ),
        button_url=portal,
        button_label='Open live school board',
    )
    return subject, text, html


def send_proprietor_transaction_notice(emails, **kwargs):
    """Email the School Proprietor a live copy of a business transaction."""
    subject, text, html = compose_proprietor_transaction_notice(**kwargs)
    return send_many(emails, subject, text, html_body=html, mail_kind='transactional')


def main(argv=None):
    """python school_mailer.py --to office@example.com"""
    _load_local_env()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description='Send a Brevo test notice from the FLPA Portal.')
    parser.add_argument('--to', default=_env('MAIL_TEST_TO'), help='Recipient (or set MAIL_TEST_TO).')
    args = parser.parse_args(argv)

    status = mailer_status()
    if not status['configured']:
        logger.error(
            'Mailer is not configured. Set SMTP_LOGIN, SMTP_PASSWORD, and SENDER_EMAIL in .env'
        )
        return 2
    logger.info(
        'Brevo ready host=%s port=%s user=%s from=%s',
        status['host'],
        status['port'],
        status['username'],
        status['sender'],
    )
    recipient = args.to
    if not recipient:
        logger.error('Pass --to you@example.com (do not hard-code a personal inbox).')
        return 2
    ok = send_school_email(
        recipient,
        f'{SCHOOL_NAME} mailer test',
        (
            f'This is a test notice from the FLPA Portal through Brevo.\n'
            f'If you received it, SMTP is working.\n'
        ),
        html_body=_branded_html(
            'Mailer test',
            'If you can read this, Brevo SMTP is connected to the FLPA Portal.',
            [('Relay', status['host']), ('From', status['sender'])],
            button_url=status['site_url'] + '/login',
        ),
    )
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())