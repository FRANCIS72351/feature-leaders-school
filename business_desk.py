"""Business Manager command desk — money, procurement, ledger, support staff."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from flask import flash, redirect, url_for
from flask_login import current_user

from constants import format_dual_money, format_school_money, normalize_currency
from models import (
    BusinessTransaction,
    NonTeachingStaff,
    SchoolExpense,
    StaffAttendanceLog,
    StudentPayment,
    SupplyInventory,
    db,
)

PAYMENT_METHODS = (
    ('cash', 'Cash'),
    ('mobile_money', 'Mobile Money'),
    ('bank', 'Bank'),
)
EXPENSE_CATEGORIES = (
    'Supplies',
    'Maintenance',
    'Utilities',
    'Equipment',
    'Salary',
    'Other',
)
STAFF_TITLES = (
    'Security',
    'Janitor',
    'Driver',
    'Clerk',
    'Cook',
    'Gardener',
    'Maintenance',
    'Other',
)
ATTENDANCE_STATUSES = ('Present', 'Absent', 'Excused')


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _money(value):
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal('0')


def month_prefix(when=None):
    stamp = when or datetime.now(timezone.utc)
    return stamp.strftime('%Y-%m')


def collect_kpis(display_year, classes_list, fee_income_total, total_revenue, total_expenses):
    outstanding = sum(float(row.get('balance') or 0) for row in (classes_list or []))
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    month = month_prefix()
    year_name = display_year.name if display_year else None

    def _sum_tx(tx_type, date_prefix=None):
        buckets = {'USD': 0.0, 'LRD': 0.0}
        query = BusinessTransaction.query.filter_by(is_deleted=False, type=tx_type)
        if year_name:
            query = query.filter(BusinessTransaction.academic_year == year_name)
        for row in query.all():
            if date_prefix and not str(row.date or '').startswith(date_prefix):
                continue
            code = normalize_currency(getattr(row, 'currency', None))
            buckets[code] = buckets.get(code, 0.0) + float(row.amount or 0)
        return buckets

    income_all = _sum_tx('income')
    expense_all = _sum_tx('expense')
    expense_month = _sum_tx('expense', month)
    expense_today = _sum_tx('expense', today)
    net = {
        'USD': income_all.get('USD', 0) - expense_all.get('USD', 0),
        'LRD': income_all.get('LRD', 0) - expense_all.get('LRD', 0),
    }
    staff_count = NonTeachingStaff.query.filter_by(status='active').count()
    low_stock = SupplyInventory.query.filter(
        SupplyInventory.quantity_in_stock <= SupplyInventory.reorder_level
    ).count()
    return {
        'fee_collected_label': format_school_money(fee_income_total or 0),
        'outstanding': outstanding,
        'outstanding_label': format_school_money(outstanding),
        'monthly_expense_label': format_dual_money(expense_month),
        'today_expense_label': format_dual_money(expense_today),
        'net_cash_label': format_dual_money(net),
        'income_label': format_dual_money(income_all),
        'expense_label': format_dual_money(expense_all),
        'support_staff_count': staff_count,
        'low_stock_count': low_stock,
        'debtor_classes': sorted(
            [row for row in (classes_list or []) if float(row.get('balance') or 0) > 0.5],
            key=lambda row: float(row.get('balance') or 0),
            reverse=True,
        )[:12],
    }


def desk_lists():
    inventory = SupplyInventory.query.order_by(SupplyInventory.item_name.asc()).all()
    expenses = SchoolExpense.query.order_by(SchoolExpense.created_at.desc()).limit(20).all()
    staff = NonTeachingStaff.query.order_by(NonTeachingStaff.full_name.asc()).all()
    today = date.today()
    attendance = (
        StaffAttendanceLog.query.filter_by(work_date=today)
        .order_by(StaffAttendanceLog.id.desc())
        .all()
    )
    return {
        'inventory_items': inventory,
        'school_expenses': expenses,
        'support_staff': staff,
        'today_attendance': attendance,
        'attendance_today': today,
        'payment_methods': PAYMENT_METHODS,
        'expense_categories': EXPENSE_CATEGORIES,
        'staff_titles': STAFF_TITLES,
        'attendance_statuses': ATTENDANCE_STATUSES,
    }


def handle_desk_post(form, *, display_year):
    """Handle command-desk POSTs. Returns a redirect or None to fall through."""
    action = (form.get('desk_action') or '').strip()
    if not action:
        return None
    year_id = display_year.id if display_year else None
    year_name = display_year.name if display_year else None

    if action == 'log_expense':
        return _log_expense(form, year_id, year_name)
    if action == 'adjust_stock':
        return _adjust_stock(form)
    if action == 'add_staff':
        return _add_staff(form)
    if action == 'log_attendance':
        return _log_attendance(form)
    if action == 'pay_salary':
        return _pay_salary(form, year_name)
    return None


def _log_expense(form, year_id, year_name):
    item_name = (form.get('item_name') or '').strip()
    category = (form.get('category') or 'Supplies').strip() or 'Supplies'
    if category not in EXPENSE_CATEGORIES:
        category = 'Other'
    if not item_name:
        flash('Enter the supply or expense item.', 'danger')
        return redirect(url_for('business_dashboard', tab='procurement'))
    qty = max(1, _int(form.get('quantity'), 1))
    unit_cost = _money(form.get('unit_cost'))
    total = qty * unit_cost
    if total <= 0:
        flash('Enter a unit cost greater than zero.', 'danger')
        return redirect(url_for('business_dashboard', tab='procurement'))
    currency = normalize_currency(form.get('currency'))
    vendor = (form.get('vendor_name') or '').strip() or None
    receipt_ref = (form.get('receipt_ref') or '').strip() or None
    notes = (form.get('notes') or '').strip() or None

    last_tx = (
        BusinessTransaction.query.filter_by(is_deleted=False)
        .order_by(BusinessTransaction.id.desc())
        .first()
    )
    prev = _money(last_tx.balance_after if last_tx else 0)
    ledger = BusinessTransaction(
        date=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        type='expense',
        amount=total,
        currency=currency,
        description=f"{item_name}" + (f" · {vendor}" if vendor else ''),
        category=category,
        balance_after=prev - total,
        academic_year=year_name,
    )
    db.session.add(ledger)
    db.session.flush()

    inventory = None
    if form.get('update_stock') == '1':
        inventory = SupplyInventory.query.filter(
            db.func.lower(SupplyInventory.item_name) == item_name.lower()
        ).first()
        if not inventory:
            inventory = SupplyInventory(
                item_name=item_name,
                category=category,
                quantity_in_stock=0,
                reorder_level=_int(form.get('reorder_level'), 5) or 5,
            )
            db.session.add(inventory)
            db.session.flush()
        inventory.quantity_in_stock = int(inventory.quantity_in_stock or 0) + qty
        inventory.last_updated_by_id = current_user.id
        inventory.updated_at = datetime.now(timezone.utc)

    expense = SchoolExpense(
        category=category,
        item_name=item_name,
        quantity=qty,
        unit_cost=unit_cost,
        total_amount=total,
        currency=currency,
        vendor_name=vendor,
        receipt_ref=receipt_ref,
        notes=notes,
        academic_year_id=year_id,
        ledger_transaction_id=ledger.id,
        inventory_id=inventory.id if inventory else None,
        recorded_by_id=current_user.id,
    )
    db.session.add(expense)
    db.session.commit()
    flash(
        f'Logged {format_school_money(total, currency)} for {item_name}.',
        'success',
    )
    return redirect(url_for('business_dashboard', tab='procurement'))


def _adjust_stock(form):
    item_id = _int(form.get('inventory_id'))
    item = db.session.get(SupplyInventory, item_id) if item_id else None
    if not item:
        flash('Choose a stock item to update.', 'danger')
        return redirect(url_for('business_dashboard', tab='procurement'))
    qty = _int(form.get('quantity_in_stock'), item.quantity_in_stock)
    reorder = _int(form.get('reorder_level'), item.reorder_level)
    item.quantity_in_stock = max(0, qty)
    item.reorder_level = max(0, reorder)
    item.last_updated_by_id = current_user.id
    item.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    flash(f'Stock updated for {item.item_name}.', 'success')
    return redirect(url_for('business_dashboard', tab='procurement'))


def _add_staff(form):
    name = (form.get('full_name') or '').strip()
    title = (form.get('job_title') or 'Clerk').strip() or 'Clerk'
    if not name:
        flash('Enter the staff member’s name.', 'danger')
        return redirect(url_for('business_dashboard', tab='staff'))
    hired = None
    raw_hired = (form.get('hired_date') or '').strip()
    if raw_hired:
        try:
            hired = datetime.strptime(raw_hired, '%Y-%m-%d').date()
        except ValueError:
            hired = None
    salary_raw = (form.get('base_salary') or '').strip()
    salary = _money(salary_raw) if salary_raw else None
    staff = NonTeachingStaff(
        full_name=name,
        job_title=title,
        phone=(form.get('phone') or '').strip() or None,
        department=(form.get('department') or '').strip() or None,
        shift_notes=(form.get('shift_notes') or '').strip() or None,
        base_salary=salary,
        currency=normalize_currency(form.get('currency')),
        status='active',
        hired_date=hired,
    )
    db.session.add(staff)
    db.session.commit()
    flash(f'{name} added to the support-staff roster.', 'success')
    return redirect(url_for('business_dashboard', tab='staff'))


def _log_attendance(form):
    staff_id = _int(form.get('staff_id'))
    staff = db.session.get(NonTeachingStaff, staff_id) if staff_id else None
    if not staff:
        flash('Choose a staff member.', 'danger')
        return redirect(url_for('business_dashboard', tab='staff'))
    status = (form.get('status') or 'Present').strip()
    if status not in ATTENDANCE_STATUSES:
        status = 'Present'
    work_date = date.today()
    raw = (form.get('work_date') or '').strip()
    if raw:
        try:
            work_date = datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            pass
    existing = StaffAttendanceLog.query.filter_by(staff_id=staff.id, work_date=work_date).first()
    if existing:
        existing.status = status
        existing.notes = (form.get('notes') or '').strip() or None
        existing.logged_by_id = current_user.id
    else:
        db.session.add(StaffAttendanceLog(
            staff_id=staff.id,
            work_date=work_date,
            status=status,
            notes=(form.get('notes') or '').strip() or None,
            logged_by_id=current_user.id,
        ))
    db.session.commit()
    flash(f'{staff.full_name} marked {status} for {work_date.strftime("%d %b %Y")}.', 'success')
    return redirect(url_for('business_dashboard', tab='staff'))


def _pay_salary(form, year_name):
    staff_id = _int(form.get('staff_id'))
    staff = db.session.get(NonTeachingStaff, staff_id) if staff_id else None
    if not staff:
        flash('Choose a staff member for the payout.', 'danger')
        return redirect(url_for('business_dashboard', tab='staff'))
    amount = _money(form.get('amount') or staff.base_salary)
    if amount <= 0:
        flash('Enter a salary amount.', 'danger')
        return redirect(url_for('business_dashboard', tab='staff'))
    currency = normalize_currency(form.get('currency') or staff.currency)
    last_tx = (
        BusinessTransaction.query.filter_by(is_deleted=False)
        .order_by(BusinessTransaction.id.desc())
        .first()
    )
    prev = _money(last_tx.balance_after if last_tx else 0)
    db.session.add(BusinessTransaction(
        date=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        type='expense',
        amount=amount,
        currency=currency,
        description=f'Salary / allowance — {staff.full_name} ({staff.job_title})',
        category='Salary',
        balance_after=prev - amount,
        academic_year=year_name,
    ))
    db.session.commit()
    flash(
        f'Paid {format_school_money(amount, currency)} to {staff.full_name}.',
        'success',
    )
    return redirect(url_for('business_dashboard', tab='staff'))
