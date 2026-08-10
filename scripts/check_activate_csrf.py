"""Manual smoke script: verify CSRF token on system-control activate form."""
import re

from app import app, db, get_system_settings, User

app.config['TESTING'] = True

with app.app_context():
    admin = User.query.filter(db.func.lower(User.role) == 'admin').first()
    if not admin:
        raise SystemExit('No admin user in database; run seed_data.py first.')
    admin_id = admin.id
    settings = get_system_settings()
    settings.system_active = False
    db.session.commit()

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True

    page = client.get('/admin/system-control')
    html = page.data.decode('utf-8')
    tokens = re.findall(r'name="csrf_token" value="([^"]+)"', html)
    print('csrf tokens on page:', len(tokens), 'unique:', len(set(tokens)))

    token = tokens[0] if tokens else ''
    resp = client.post(
        '/admin/system-control',
        data={'action': 'activate', 'csrf_token': token},
        follow_redirects=True,
    )
    print('POST status:', resp.status_code)
    print('CSRF error in body:', 'CSRF' in resp.data.decode('utf-8', errors='replace'))

    with app.app_context():
        print('system_active:', get_system_settings().system_active)
