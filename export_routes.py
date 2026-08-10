from flask import Response, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from io import StringIO, BytesIO
import csv
from datetime import datetime, timedelta
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import qrcode
from PIL import Image
import os
from models import Student, Grade, Attendance, StudentPayment, Sponsor, BusinessTransaction, AcademicYear, Class, Teacher, ClassSubjectTeacher
from constants import ROLE_ADMIN, ROLE_REGISTRAR, ROLE_TEACHER, ROLE_BUSINESS


def _export_role_allowed(*roles):
    return (current_user.role or '').strip().lower() in {r.lower() for r in roles}


def _parse_date_str(value):
    """Try to parse various date string formats into a date object.

    Returns a date or None.
    """
    if not value:
        return None
    if isinstance(value, (datetime,)):
        return value.date()
    s = str(value).strip()
    # Try ISO first
    try:
        dt = datetime.fromisoformat(s)
        return dt.date()
    except Exception:
        pass
    # Common formats
    fmts = ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y']
    for f in fmts:
        try:
            return datetime.strptime(s, f).date()
        except Exception:
            continue
    return None


def _resolve_export_academic_year():
    """Resolve academic year from query params; default to active year."""
    year_id = request.args.get('academic_year_id', type=int)
    year_name = (request.args.get('year') or '').strip()
    if year_id:
        year = AcademicYear.query.get(year_id)
        if year:
            return year
    if year_name:
        year = AcademicYear.query.filter_by(name=year_name).first()
        if year:
            return year
    return AcademicYear.query.filter_by(is_active=True).first()


def init_export_routes(app):
    @app.route('/export/students')
    @login_required
    def export_students():
        # allow admins, registrars and business
        if not _export_role_allowed(ROLE_ADMIN, ROLE_REGISTRAR, ROLE_BUSINESS):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        from sqlalchemy.orm import joinedload
        display_year = _resolve_export_academic_year()
        class_id = request.args.get('class_id', type=int)
        query = Student.query.options(
            joinedload(Student.assigned_class),
            joinedload(Student.academic_year),
        )
        if display_year:
            query = query.filter(Student.academic_year_id == display_year.id)
        if class_id:
            query = query.filter(Student.klass_id == class_id)
        students = query.order_by(Student.last_name, Student.first_name).all()

        # Stream CSV to avoid large memory usage
        def generate():
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(['Student ID', 'First Name', 'Last Name', 'Class', 'Gender', 'Parent Email', 'Year'])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

            for student in students:
                writer.writerow([
                    student.student_id,
                    student.first_name,
                    student.last_name,
                    getattr(student.klass, 'name', '') if student.klass else '',
                    student.gender,
                    student.parent_email or '',
                    getattr(student.academic_year, 'name', '') if getattr(student, 'academic_year', None) else ''
                ])
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)

        return Response(
            generate(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=students.csv'}
        )

    @app.route('/export/grades')
    @login_required
    def export_grades():
        if not _export_role_allowed(ROLE_ADMIN, ROLE_TEACHER):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        grades_query = Grade.query
        display_year = _resolve_export_academic_year()
        if display_year:
            grades_query = grades_query.filter_by(academic_year_id=display_year.id)
        elif request.args.get('year'):
            year = request.args.get('year')
            grades_query = grades_query.join(Student).join(AcademicYear).filter(AcademicYear.name == year)
        if _export_role_allowed(ROLE_TEACHER) and not _export_role_allowed(ROLE_ADMIN):
            teacher = Teacher.query.filter_by(user_id=current_user.id).first()
            class_ids = set()
            if teacher:
                for klass in Class.query.filter_by(teacher_id=teacher.id).all():
                    class_ids.add(klass.id)
                for alloc in ClassSubjectTeacher.query.filter_by(teacher_id=teacher.id).all():
                    class_ids.add(alloc.class_id)
            if class_ids:
                grades_query = grades_query.filter(Grade.class_id.in_(class_ids))
            else:
                grades_query = grades_query.filter(Grade.id == -1)
        grades = grades_query.all()
        def generate():
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(['Student ID', 'Subject', 'Score', 'Remarks'])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            for grade in grades:
                writer.writerow([
                    grade.student_id,
                    grade.subject,
                    grade.score,
                    grade.remarks or ''
                ])
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)
        return Response(generate(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=grades.csv'})

    @app.route('/export/attendance')
    @login_required
    def export_attendance():
        if not _export_role_allowed(ROLE_ADMIN, ROLE_TEACHER, 'principal', ROLE_REGISTRAR):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        attendance_query = Attendance.query
        display_year = _resolve_export_academic_year()
        if display_year:
            year_student_ids = [
                s.id for s in Student.query.filter(
                    Student.academic_year_id == display_year.id
                ).all()
            ]
            if year_student_ids:
                attendance_query = attendance_query.filter(
                    Attendance.student_id.in_(year_student_ids)
                )
            else:
                attendance_query = attendance_query.filter(Attendance.id == -1)
        elif request.args.get('year'):
            year = request.args.get('year')
            attendance_query = (
                attendance_query.join(Student)
                .join(AcademicYear)
                .filter(AcademicYear.name == year)
            )
        if _export_role_allowed(ROLE_TEACHER) and not _export_role_allowed(ROLE_ADMIN):
            teacher = Teacher.query.filter_by(user_id=current_user.id).first()
            class_ids = set()
            if teacher:
                for klass in Class.query.filter_by(teacher_id=teacher.id).all():
                    class_ids.add(klass.id)
                for alloc in ClassSubjectTeacher.query.filter_by(teacher_id=teacher.id).all():
                    class_ids.add(alloc.class_id)
            if class_ids:
                student_ids_query = Student.query.filter(Student.klass_id.in_(class_ids))
                if display_year:
                    student_ids_query = student_ids_query.filter(
                        Student.academic_year_id == display_year.id
                    )
                student_ids = [s.id for s in student_ids_query.all()]
                if student_ids:
                    attendance_query = attendance_query.filter(Attendance.student_id.in_(student_ids))
                else:
                    attendance_query = attendance_query.filter(Attendance.id == -1)
            else:
                attendance_query = attendance_query.filter(Attendance.id == -1)
        attendance = attendance_query.all()
        def generate():
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(['Student ID', 'Date', 'Status', 'Notes'])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            for record in attendance:
                writer.writerow([
                    record.student_id,
                    record.date,
                    record.status,
                    record.notes or ''
                ])
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)
        return Response(generate(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=attendance.csv'})

    @app.route('/export/payments')
    @login_required
    def export_payments():
        if not _export_role_allowed(ROLE_ADMIN, ROLE_BUSINESS, ROLE_REGISTRAR):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        from sqlalchemy.orm import joinedload
        display_year = _resolve_export_academic_year()
        # optional date range filtering (YYYY-MM-DD)
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        payments_query = StudentPayment.query.options(
            joinedload(StudentPayment.student).joinedload(Student.assigned_class),
            joinedload(StudentPayment.academic_year),
        )
        if display_year:
            payments_query = payments_query.filter_by(academic_year_id=display_year.id)
        elif request.args.get('year'):
            year = request.args.get('year')
            payments_query = payments_query.join(AcademicYear).filter(AcademicYear.name == year)

        # apply datetime filters when provided
        try:
            if start_date:
                sd = datetime.strptime(start_date, '%Y-%m-%d')
                payments_query = payments_query.filter(StudentPayment.paid_on >= sd)
            if end_date:
                ed = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                payments_query = payments_query.filter(StudentPayment.paid_on < ed)
        except Exception:
            # ignore parse errors and return unfiltered results
            pass

        payments = payments_query.order_by(StudentPayment.paid_on.asc()).all()

        def generate():
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                'Student ID', 'Student Name', 'Class', 'Academic Year',
                'Term', 'Installment', 'Amount Paid', 'Paid On', 'Description'
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            for payment in payments:
                student = payment.student
                writer.writerow([
                    student.student_id if student else payment.student_id,
                    f"{student.last_name}, {student.first_name}" if student else '',
                    getattr(student.klass, 'name', '') if student and student.klass else '',
                    getattr(payment.academic_year, 'name', '') if payment.academic_year else '',
                    payment.term,
                    payment.installment or '',
                    f"{payment.amount_paid:.2f}",
                    payment.paid_on.strftime('%Y-%m-%d') if payment.paid_on else '',
                    payment.description or '',
                ])
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)
        return Response(
            generate(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=payments.csv'}
        )

    @app.route('/export/sponsors')
    @login_required
    def export_sponsors():
        if not _export_role_allowed(ROLE_ADMIN, ROLE_REGISTRAR):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        # Get all classes that have sponsors (teachers)
        sponsored_classes = Class.query.filter(Class.sponsor_id.isnot(None)).all()

        def generate():
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(['Class Name', 'Teacher Sponsor', 'Grade Level', 'Stream'])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            for klass in sponsored_classes:
                sponsor_name = klass.sponsor.full_name if klass.sponsor else 'Unknown'
                writer.writerow([
                    klass.name,
                    sponsor_name,
                    klass.grade_level or '',
                    klass.stream or '',
                ])
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)
        return Response(generate(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=class_sponsors.csv'})

    @app.route('/export/business')
    @login_required
    def export_business():
        if not _export_role_allowed(ROLE_ADMIN, ROLE_BUSINESS):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        year = request.args.get('year')
        query = BusinessTransaction.query.order_by(BusinessTransaction.date.desc())
        if year:
            query = query.filter(BusinessTransaction.date.startswith(year))
        transactions = query.all()

        # optional start/end date filtering (YYYY-MM-DD) — transactions store date as string
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        if start_date or end_date:
            try:
                sd = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
                ed = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
                filtered = []
                for txn in transactions:
                    try:
                        tdate = _parse_date_str(txn.date)
                        if tdate is None:
                            continue
                    except Exception:
                        continue
                    if sd and tdate < sd:
                        continue
                    if ed and tdate > ed:
                        continue
                    filtered.append(txn)
                transactions = filtered
            except Exception:
                pass

        def generate():
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(['Date', 'Type', 'Amount', 'Category', 'Description'])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            for txn in transactions:
                writer.writerow([
                    txn.date,
                    txn.type,
                    txn.amount,
                    txn.category or '',
                    txn.description or ''
                ])
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)
        # include date range in filename when present
        range_suffix = ''
        if request.args.get('start_date') or request.args.get('end_date'):
            s = request.args.get('start_date') or ''
            e = request.args.get('end_date') or ''
            range_suffix = f"_{s}_{e}".strip('_')
        filename = f"business_transactions_{year or 'all'}{range_suffix}.csv"
        return Response(
            generate(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )

    @app.route('/report/business/pdf')
    @login_required
    def report_business_pdf():
        if not _export_role_allowed(ROLE_ADMIN, ROLE_BUSINESS):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        year = request.args.get('year')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        query = BusinessTransaction.query.order_by(BusinessTransaction.date.asc())
        if year:
            query = query.filter(BusinessTransaction.date.startswith(year))
        transactions = query.all()

        if start_date or end_date:
            try:
                sd = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
                ed = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
                filtered = []
                for txn in transactions:
                    try:
                        tdate = _parse_date_str(txn.date)
                        if tdate is None:
                            continue
                    except Exception:
                        continue
                    if sd and tdate < sd:
                        continue
                    if ed and tdate > ed:
                        continue
                    filtered.append(txn)
                transactions = filtered
            except Exception:
                pass

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.setFont('Helvetica-Bold', 16)
        pdf.drawString(50, 800, 'Business Transactions Report')
        pdf.setFont('Helvetica', 12)
        title_suffix = f" - {year}" if year else ''
        pdf.drawString(50, 780, f"Academic Year: {year if year else 'All'}{title_suffix}")

        y = 750
        pdf.setFont('Helvetica', 11)
        if not transactions:
            pdf.drawString(50, y, 'No transactions found for the selected period.')
        else:
            for txn in transactions:
                if y < 60:
                    pdf.showPage()
                    y = 800
                    pdf.setFont('Helvetica', 11)
                pdf.drawString(50, y, f"Date: {txn.date} | Type: {txn.type.capitalize()} | Amount: ${txn.amount:.2f}")
                y -= 16
                if txn.category or txn.description:
                    details = []
                    if txn.category:
                        details.append(f"Category: {txn.category}")
                    if txn.description:
                        details.append(f"Description: {txn.description}")
                    pdf.drawString(70, y, ' | '.join(details))
                    y -= 16
                y -= 8

        pdf.showPage()
        pdf.save()
        buffer.seek(0)
        filename = f"business_report_{year or 'all'}.pdf"
        return Response(
            buffer,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )

    @app.route('/report-students/pdf')
    @login_required
    def report_students_pdf():
        # Small students listing PDF for admins/registrars and authorized teachers
        class_id = request.args.get('class_id', type=int)
        # allow admin/registrar always
        if not _export_role_allowed(ROLE_ADMIN, ROLE_REGISTRAR, ROLE_TEACHER):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        # If teacher role, ensure they are assigned to the requested class (if any)
        if (current_user.role or '').strip().lower() == (ROLE_TEACHER or '').lower():
            if class_id:
                teacher = Teacher.query.filter_by(user_id=current_user.id).first()
                allowed = False
                if teacher:
                    klass = Class.query.get(class_id)
                    if klass and (klass.teacher_id == teacher.id):
                        allowed = True
                    else:
                        # check explicit allocations
                        alloc = ClassSubjectTeacher.query.filter_by(class_id=class_id, teacher_id=teacher.id).first()
                        if alloc:
                            allowed = True
                if not allowed:
                    flash('Access denied for this class.', 'danger')
                    return redirect(url_for('teacher_dashboard'))

        from sqlalchemy.orm import joinedload
        display_year = _resolve_export_academic_year()
        query = Student.query.options(joinedload(Student.academic_year))
        if display_year:
            query = query.filter(Student.academic_year_id == display_year.id)
        students = query.order_by(Student.last_name, Student.first_name).all()
        year_label = display_year.name if display_year else ''

        buffer = BytesIO()
        p = canvas.Canvas(buffer)
        p.setFont('Helvetica-Bold', 14)
        p.drawString(50, 800, f"Students List{(' - ' + year_label) if year_label else ''}")
        y = 780
        p.setFont('Helvetica', 11)
        for s in students:
            if y < 50:
                p.showPage()
                y = 800
                p.setFont('Helvetica', 11)
            p.drawString(50, y, f"{s.student_id} - {s.last_name}, {s.first_name} ({s.klass or ''})")
            y -= 16

        p.showPage()
        p.save()
        buffer.seek(0)
        return Response(buffer, mimetype='application/pdf', headers={
            'Content-Disposition': f'attachment; filename=students_{year_label or "all"}.pdf'
        })

    @app.route('/report/payment/<int:student_id>/pdf')
    @login_required
    def payment_report_pdf(student_id):
        """Download a student's payment history as PDF."""
        from app import build_student_financials, get_active_academic_year, normalize_role

        student = Student.query.get_or_404(student_id)
        role = normalize_role(current_user)
        if role == 'student':
            linked = Student.query.filter_by(user_id=current_user.id).first()
            if not linked or linked.id != student.id:
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard'))
        elif not _export_role_allowed(
            ROLE_ADMIN, ROLE_REGISTRAR, ROLE_BUSINESS, 'principal', 'vpi'
        ):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        display_year = _resolve_export_academic_year() or get_active_academic_year()
        financials = build_student_financials(student, display_year)
        payments = StudentPayment.query.filter_by(student_id=student.id)
        if display_year:
            payments = payments.filter_by(academic_year_id=display_year.id)
        # optional single-payment export
        payment_id = request.args.get('payment_id', type=int)
        if payment_id:
            payments = payments.filter_by(id=payment_id)
        payments = payments.order_by(StudentPayment.paid_on.asc()).all()

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.setFont('Helvetica-Bold', 14)
        pdf.drawString(50, 800, f"Payment Report — {student.full_name}")
        pdf.setFont('Helvetica', 11)
        y = 780
        pdf.drawString(50, y, f"Student ID: {student.student_id or student.id}")
        y -= 16
        if display_year:
            pdf.drawString(50, y, f"Academic Year: {display_year.name}")
            y -= 16
        pdf.drawString(50, y, f"Total Fee: ${financials.get('yearly_fee', 0)}")
        y -= 16
        pdf.drawString(50, y, f"Total Paid: ${financials.get('total_paid', 0)}")
        y -= 16
        pdf.drawString(50, y, f"Balance: ${financials.get('tuition_balance', 0)}")
        y -= 24
        for payment in payments:
            if y < 60:
                pdf.showPage()
                y = 800
                pdf.setFont('Helvetica', 11)
            paid_on = payment.paid_on.strftime('%Y-%m-%d') if payment.paid_on else '—'
            pdf.drawString(
                50,
                y,
                f"Term {payment.term or '—'} | ${payment.amount_paid:.2f} | {paid_on} | {payment.description or ''}",
            )
            y -= 16

        pdf.showPage()
        pdf.save()
        buffer.seek(0)
        filename = f"payments_{student.student_id or student.id}.pdf"
        return Response(
            buffer,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename={filename}'},
        )

    @app.route('/export/payment/<int:student_id>')
    @login_required
    def export_payment_csv(student_id):
        """Export a single student's payment history as CSV."""
        from app import get_active_academic_year, normalize_role

        student = Student.query.get_or_404(student_id)
        role = normalize_role(current_user)
        if role == 'student':
            linked = Student.query.filter_by(user_id=current_user.id).first()
            if not linked or linked.id != student.id:
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard'))
        elif not _export_role_allowed(
            ROLE_ADMIN, ROLE_REGISTRAR, ROLE_BUSINESS, 'principal', 'vpi'
        ):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        display_year = _resolve_export_academic_year() or get_active_academic_year()
        payments = StudentPayment.query.filter_by(student_id=student.id)
        if display_year:
            payments = payments.filter_by(academic_year_id=display_year.id)
        payments = payments.order_by(StudentPayment.paid_on.asc()).all()

        def generate():
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(['Term', 'Installment', 'Amount Paid', 'Paid On', 'Description', 'Academic Year'])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            for p in payments:
                writer.writerow([
                    p.term or '',
                    p.installment or '',
                    f"{p.amount_paid:.2f}",
                    p.paid_on.strftime('%Y-%m-%d') if p.paid_on else '',
                    p.description or '',
                    getattr(p.academic_year, 'name', '') if getattr(p, 'academic_year', None) else ''
                ])
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)

        filename = f"payments_{student.student_id or student.id}.csv"
        return Response(generate(), mimetype='text/csv', headers={
            'Content-Disposition': f'attachment; filename={filename}'
        })

    @app.route('/report/payment/receipt/<int:payment_id>/pdf')
    @login_required
    def payment_receipt_pdf(payment_id):
        """Generate a printable receipt PDF for a single StudentPayment."""
        from app import normalize_role

        payment = StudentPayment.query.get_or_404(payment_id)
        student = payment.student
        if not student:
            flash('Payment has no linked student.', 'danger')
            return redirect(url_for('dashboard'))

        role = normalize_role(current_user)
        if role == 'student':
            linked = Student.query.filter_by(user_id=current_user.id).first()
            if not linked or linked.id != student.id:
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard'))
        elif not _export_role_allowed(ROLE_ADMIN, ROLE_REGISTRAR, ROLE_BUSINESS, 'principal', 'vpi'):
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))

        buffer = BytesIO()
        # Use a compact receipt size (points)
        page_w, page_h = 360, 540
        pdf = canvas.Canvas(buffer, pagesize=(page_w, page_h))

        # Header: logo (if present) and school name
        logo_path = os.path.join(os.path.dirname(__file__), 'static', 'images', 'school_logo.png')
        if not os.path.exists(logo_path):
            logo_path = os.path.join(os.path.dirname(__file__), 'static', 'images', 'logo.png')
        if os.path.exists(logo_path):
            try:
                img = Image.open(logo_path)
                img_reader = ImageReader(img)
                logo_w = 72
                logo_h = int(logo_w * img.size[1] / max(1, img.size[0]))
                pdf.drawImage(img_reader, page_w - logo_w - 20, page_h - logo_h - 14, width=logo_w, height=logo_h, preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        school_name = getattr(current_app, 'config', {}).get('SCHOOL_NAME') or current_app.config.get('SCHOOL_NAME') if hasattr(current_app, 'config') else 'School'
        pdf.setFont('Helvetica-Bold', 14)
        pdf.drawString(20, page_h - 40, f"{school_name}")
        pdf.setFont('Helvetica', 10)
        pdf.drawString(20, page_h - 56, 'Official Receipt')

        # Body: receipt fields
        y = page_h - 90
        line_h = 14
        pdf.setFont('Helvetica', 10)
        pdf.drawString(20, y, f"Receipt #: {payment.id}")
        y -= line_h
        pdf.drawString(20, y, f"Student: {student.full_name}")
        y -= line_h
        pdf.drawString(20, y, f"Student ID: {student.student_id or student.id}")
        y -= line_h
        pdf.drawString(20, y, f"Academic Year: {getattr(payment.academic_year,'name','')}")
        y -= line_h
        pdf.drawString(20, y, f"Term: {payment.term}")
        y -= line_h
        pdf.drawString(20, y, f"Installment: {payment.installment or ''}")
        y -= line_h

        # Amount and totals (formatted)
        pdf.setFont('Helvetica-Bold', 11)
        pdf.drawString(20, y, 'Amount Paid:')
        pdf.drawString(140, y, f"₱{float(payment.amount_paid):,.2f}")
        y -= line_h
        pdf.setFont('Helvetica', 10)

        paid_on = payment.paid_on.strftime('%Y-%m-%d %H:%M') if payment.paid_on else ''
        pdf.drawString(20, y, f"Paid On: {paid_on}")
        y -= line_h
        if payment.description:
            pdf.drawString(20, y, f"Notes: {payment.description}")
            y -= line_h

        # QR Code with a short verification URL or payment data
        try:
            verify_url = url_for('payment_receipt_pdf', payment_id=payment.id, _external=True)
        except Exception:
            verify_url = f"receipt:{payment.id}"
        try:
            qr = qrcode.QRCode(box_size=2, border=1)
            qr.add_data(verify_url)
            qr.make(fit=True)
            img_q = qr.make_image(fill_color='black', back_color='white').convert('RGB')
            qbuf = BytesIO()
            img_q.save(qbuf, format='PNG')
            qbuf.seek(0)
            qr_reader = ImageReader(qbuf)
            qr_size = 100
            pdf.drawImage(qr_reader, page_w - qr_size - 20, 40, width=qr_size, height=qr_size)
        except Exception:
            pass

        # Footer note
        pdf.setFont('Helvetica-Oblique', 8)
        pdf.drawString(20, 30, 'This is a system-generated receipt. Retain for your records.')

        pdf.showPage()
        pdf.save()
        buffer.seek(0)
        filename = f"receipt_{payment.id}.pdf"
        return Response(buffer, mimetype='application/pdf', headers={
            'Content-Disposition': f'attachment; filename={filename}'
        })

    return app