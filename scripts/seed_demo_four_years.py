"""
Seed four academic years of demo data for system testing.

Usage:
  python scripts/seed_demo_four_years.py           # add demo data (skip if already seeded)
  python scripts/seed_demo_four_years.py --fresh  # remove prior demo data, then re-seed
  python scripts/seed_demo_four_years.py --dry-run

Demo logins (password for all): Demo1234!
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

BASE_DIR = __import__("os").path.abspath(__import__("os").path.join(__import__("os").path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app, db, record_student_payment_with_income  # noqa: E402
from models import (  # noqa: E402
    AcademicYear,
    Announcement,
    BusinessTransaction,
    Class,
    ClassSubject,
    ClassSubjectTeacher,
    Grade,
    SchoolFee,
    Student,
    Teacher,
    User,
)

DEMO_PASSWORD = "Demo1234!"
DEMO_DOMAIN = "@demo.school"
DEMO_STUDENT_PREFIX = "DEMO_"
DEMO_CLASS_PREFIX = "DEMO-"
DEMO_YEAR_PREFIX = "Demo "

YEAR_NAMES = [
    f"{DEMO_YEAR_PREFIX}2022-2023",
    f"{DEMO_YEAR_PREFIX}2023-2024",
    f"{DEMO_YEAR_PREFIX}2024-2025",
    f"{DEMO_YEAR_PREFIX}2025-2026",
]

SUBJECTS = ["Mathematics", "English", "Science", "Social Studies"]
FIRST_NAMES = [
    "Amara", "Blessing", "Emmanuel", "Fatima", "Grace", "James", "Kofi", "Lydia",
    "Marcus", "Naomi", "Peter", "Ruth", "Samuel", "Theresa", "Victor", "Winnie",
    "Yusuf", "Zainab", "Abraham", "Comfort", "Daniel", "Esther", "Francis", "Hannah",
]
LAST_NAMES = [
    "Johnson", "Kamara", "Williams", "Brown", "Cooper", "Davis", "Flomo", "Garrett",
    "Harris", "Jackson", "Konneh", "Lewis", "Moore", "Nelson", "Payne", "Quinn",
]

CLASS_BLUEPRINT = [
    (7, "G7-A"), (7, "G7-B"),
    (8, "G8-A"), (8, "G8-B"),
    (9, "G9-A"),
    (10, "G10-Science"), (10, "G10-Arts"),
    (11, "G11-Science"),
    (12, "G12-Science"),
]

STAFF_BLUEPRINT = [
    ("admin", "Demo Admin", "demo.admin"),
    ("principal", "Demo Principal", "demo.principal"),
    ("registrar", "Demo Registrar", "demo.registrar"),
    ("business", "Demo Business Officer", "demo.business"),
    ("teacher", "Demo Teacher Math", "demo.teacher.math", "Mathematics"),
    ("teacher", "Demo Teacher English", "demo.teacher.english", "English"),
    ("teacher", "Demo Teacher Science", "demo.teacher.science", "Science"),
]


def demo_email(username: str) -> str:
    return f"{username}{DEMO_DOMAIN}"


def is_demo_seeded() -> bool:
    return User.query.filter(User.email.like(f"%{DEMO_DOMAIN}")).first() is not None


def clear_demo_data():
    """Remove demo-tagged rows without touching production accounts."""
    demo_users = User.query.filter(User.email.like(f"%{DEMO_DOMAIN}")).all()
    demo_user_ids = [u.id for u in demo_users]

    demo_students = Student.query.filter(Student.student_id.like(f"{DEMO_STUDENT_PREFIX}%")).all()
    demo_student_ids = [s.id for s in demo_students]

    demo_classes = Class.query.filter(Class.name.like(f"{DEMO_CLASS_PREFIX}%")).all()
    demo_class_ids = [c.id for c in demo_classes]

    demo_years = AcademicYear.query.filter(AcademicYear.name.like(f"{DEMO_YEAR_PREFIX}%")).all()
    demo_year_ids = [y.id for y in demo_years]

    if demo_student_ids:
        Grade.query.filter(Grade.student_id.in_(demo_student_ids)).delete(synchronize_session=False)
        from models import StudentPayment
        StudentPayment.query.filter(StudentPayment.student_id.in_(demo_student_ids)).delete(synchronize_session=False)
        Student.query.filter(Student.id.in_(demo_student_ids)).delete(synchronize_session=False)

    if demo_class_ids:
        ClassSubjectTeacher.query.filter(ClassSubjectTeacher.class_id.in_(demo_class_ids)).delete(synchronize_session=False)
        ClassSubject.query.filter(ClassSubject.class_id.in_(demo_class_ids)).delete(synchronize_session=False)
        Class.query.filter(Class.id.in_(demo_class_ids)).delete(synchronize_session=False)

    if demo_year_ids:
        SchoolFee.query.filter(SchoolFee.academic_year_id.in_(demo_year_ids)).delete(synchronize_session=False)
        for yid in demo_year_ids:
            AcademicYear.query.filter_by(id=yid).delete(synchronize_session=False)

    if demo_user_ids:
        Teacher.query.filter(Teacher.user_id.in_(demo_user_ids)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(demo_user_ids)).delete(synchronize_session=False)

    Announcement.query.filter(Announcement.author.like(f"%{DEMO_DOMAIN}")).delete(synchronize_session=False)
    BusinessTransaction.query.filter(BusinessTransaction.description.like("Demo seed:%")).delete(synchronize_session=False)

    db.session.commit()


def score_for_student(student_idx: int, year_idx: int, subject_idx: int) -> int:
    """Deterministic scores: ~85% pass, some repeat candidates."""
    seed = student_idx * 100 + year_idx * 10 + subject_idx
    rng = random.Random(seed)
    if student_idx % 12 == 0:
        return rng.randint(52, 68)
    if student_idx % 9 == 0:
        return rng.randint(58, 72)
    return rng.randint(72, 96)


def ensure_staff(admin_id: int | None, dry_run: bool) -> dict:
    staff = {}
    if dry_run:
        return {"admin": None, "teachers": []}

    for entry in STAFF_BLUEPRINT:
        role, full_name, username = entry[0], entry[1], entry[2]
        email = demo_email(username)
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, full_name=full_name, role=role, username=username.replace(".", "_"))
            user.set_password(DEMO_PASSWORD)
            db.session.add(user)
            db.session.flush()
        staff[role if role != "teacher" else username] = user

        if role == "teacher":
            subject = entry[3]
            teacher = Teacher.query.filter_by(user_id=user.id).first()
            if not teacher:
                parts = full_name.split()
                teacher = Teacher(
                    user_id=user.id,
                    first_name=parts[1] if len(parts) > 1 else parts[0],
                    last_name=parts[-1],
                    subject=subject,
                )
                db.session.add(teacher)
                db.session.flush()
            staff[f"teacher_{subject.lower()}"] = teacher

    db.session.commit()
    staff["admin"] = User.query.filter_by(email=demo_email("demo.admin")).first()
    return staff


def ensure_years(admin_id: int, dry_run: bool) -> list:
    if dry_run:
        return []
    years = []
    start_pairs = [(2022, 2023), (2023, 2024), (2024, 2025), (2025, 2026)]
    for i, name in enumerate(YEAR_NAMES):
        y1, y2 = start_pairs[i]
        year = AcademicYear.query.filter_by(name=name).first()
        if not year:
            year = AcademicYear(
                name=name,
                start_date=date(y1, 9, 1),
                end_date=date(y2, 6, 30),
                is_active=(i == len(YEAR_NAMES) - 1),
                created_by=admin_id,
            )
            db.session.add(year)
        else:
            year.is_active = i == len(YEAR_NAMES) - 1
        years.append(year)
    AcademicYear.query.filter(~AcademicYear.name.like(f"{DEMO_YEAR_PREFIX}%")).update(
        {AcademicYear.is_active: False}, synchronize_session=False
    )
    db.session.commit()
    return years


def ensure_classes(staff: dict, dry_run: bool) -> list:
    if dry_run:
        return []
    classes = []
    math_teacher = staff.get("teacher_mathematics")
    for grade_level, short_name in CLASS_BLUEPRINT:
        name = f"{DEMO_CLASS_PREFIX}{short_name}"
        klass = Class.query.filter_by(name=name).first()
        yearly = Decimal("450.00") + Decimal(str(grade_level * 25))
        if not klass:
            klass = Class(
                name=name,
                grade_level=grade_level,
                stream="Science" if "Science" in short_name else ("Arts" if "Arts" in short_name else None),
                yearly_fees=yearly,
                teacher_id=math_teacher.id if math_teacher else None,
            )
            db.session.add(klass)
            db.session.flush()
        for subject in SUBJECTS:
            if not ClassSubject.query.filter_by(class_id=klass.id, subject_name=subject).first():
                db.session.add(ClassSubject(class_id=klass.id, subject_name=subject))
            tkey = f"teacher_{subject.lower()}"
            teacher = staff.get(tkey)
            if teacher and not ClassSubjectTeacher.query.filter_by(
                class_id=klass.id, teacher_id=teacher.id, subject_name=subject
            ).first():
                db.session.add(ClassSubjectTeacher(class_id=klass.id, teacher_id=teacher.id, subject_name=subject))
        classes.append(klass)
    db.session.commit()
    return classes


def ensure_fees(years: list, classes: list, dry_run: bool):
    if dry_run:
        return
    for year in years:
        if not SchoolFee.query.filter_by(academic_year_id=year.id, class_id=None, fee_type="tuition").first():
            db.session.add(SchoolFee(academic_year_id=year.id, class_id=None, fee_type="tuition", amount=Decimal("500.00")))
        for klass in classes:
            reg_amt = Decimal("35.00") + Decimal(str(klass.grade_level * 5))
            existing = SchoolFee.query.filter_by(
                academic_year_id=year.id, class_id=klass.id, fee_type="registration"
            ).first()
            if not existing:
                db.session.add(SchoolFee(
                    academic_year_id=year.id,
                    class_id=klass.id,
                    fee_type="registration",
                    amount=reg_amt,
                ))
    db.session.commit()


def seed_students_and_history(years: list, classes: list, staff: dict, dry_run: bool) -> dict:
    stats = {"students": 0, "grades": 0, "payments": 0, "announcements": 0}
    if dry_run:
        stats["students"] = 48
        stats["grades"] = 48 * 4 * 4 * 6
        return stats

    active_year = years[-1]
    admin = staff["admin"]
    students_per_class = 6
    student_counter = 0

    for klass in classes:
        for seat in range(students_per_class):
            student_counter += 1
            sid = f"{DEMO_STUDENT_PREFIX}{student_counter:04d}"
            student = Student.query.filter_by(student_id=sid).first()
            if not student:
                fn = FIRST_NAMES[(student_counter - 1) % len(FIRST_NAMES)]
                ln = LAST_NAMES[(student_counter - 1) % len(LAST_NAMES)]
                student = Student(
                    student_id=sid,
                    first_name=fn,
                    last_name=ln,
                    dob=date(2010 + (12 - klass.grade_level), 3, 15),
                    gender="Female" if student_counter % 2 == 0 else "Male",
                    parent_email=f"parent.{student_counter}{DEMO_DOMAIN}",
                    klass_id=klass.id,
                    academic_year_id=active_year.id,
                    grade_level=klass.grade_level,
                    status="ACTIVE",
                    registration_type="Returning" if student_counter > 20 else "New",
                    tuition_cleared=student_counter % 5 != 0,
                    registration_fees=Decimal("50.00"),
                )
                db.session.add(student)
                db.session.flush()
            stats["students"] += 1

            entry_grade = max(7, klass.grade_level - (len(years) - 1))
            for y_idx, year in enumerate(years):
                current_grade = min(12, entry_grade + y_idx)
                if current_grade > klass.grade_level and year.id == active_year.id:
                    continue
                if year.id != active_year.id and current_grade != klass.grade_level - (len(years) - 1 - y_idx):
                    if y_idx < len(years) - 1:
                        pass

                for s_idx, subject in enumerate(SUBJECTS):
                    existing = Grade.query.filter_by(
                        student_id=student.id,
                        academic_year_id=year.id,
                        subject_name=subject,
                    ).first()
                    if existing:
                        continue
                    p_scores = [
                        score_for_student(student_counter, y_idx, s_idx * 6 + p)
                        for p in range(6)
                    ]
                    avg = sum(p_scores) / len(p_scores)
                    grade = Grade(
                        student_id=student.id,
                        teacher_id=staff.get(f"teacher_{subject.lower()}").id if staff.get(f"teacher_{subject.lower()}") else None,
                        class_id=klass.id,
                        academic_year_id=year.id,
                        subject=subject,
                        subject_name=subject,
                        marking_period=6,
                        period="Period 6",
                        ca_score=round(avg * 0.6, 1),
                        exam_score=round(avg * 0.4, 1),
                        score=round(avg, 1),
                        p1=p_scores[0], p2=p_scores[1], p3=p_scores[2],
                        p4=p_scores[3], p5=p_scores[4], p6=p_scores[5],
                        submitted=True,
                        remarks="Promoted" if avg >= 70 else "Needs improvement",
                    )
                    db.session.add(grade)
                    stats["grades"] += 1

                reg_fee = SchoolFee.query.filter_by(
                    academic_year_id=year.id, class_id=klass.id, fee_type="registration"
                ).first()
                reg_amount = float(reg_fee.amount) if reg_fee else 50.0
                record_student_payment_with_income(
                    student,
                    year.id,
                    term=1,
                    amount_paid=reg_amount,
                    description=f"Demo seed: Registration Fees — {year.name}",
                    paid_on=datetime(year.start_date.year, 9, 15, tzinfo=timezone.utc),
                )
                stats["payments"] += 1

                if student_counter % 3 == 0:
                    record_student_payment_with_income(
                        student,
                        year.id,
                        term=1,
                        amount_paid=150.00,
                        description=f"Demo seed: Tuition — {year.name} Term 1",
                        paid_on=datetime(year.start_date.year, 10, 1, tzinfo=timezone.utc),
                    )
                    stats["payments"] += 1

    db.session.commit()

    for i, year in enumerate(years):
        title = f"Demo: Welcome to {year.name}"
        if not Announcement.query.filter_by(title=title).first():
            db.session.add(Announcement(
                title=title,
                body=f"Automated demo announcement for {year.name}. Registration and classes are in session.",
                audience="all",
                author=demo_email("demo.admin"),
            ))
            stats["announcements"] += 1

    if not BusinessTransaction.query.filter(BusinessTransaction.description.like("Demo seed: Operating expense%")).first():
        db.session.add(BusinessTransaction(
            date=date.today().isoformat(),
            type="expense",
            amount=Decimal("2500.00"),
            description="Demo seed: Operating expense — office supplies",
            category="Supplies",
            academic_year=active_year.name,
        ))

    db.session.commit()
    return stats


def print_summary(stats: dict, dry_run: bool):
    print("\n" + "=" * 70)
    print("DEMO SEED COMPLETE" if not dry_run else "DRY RUN SUMMARY")
    print("=" * 70)
    print(f"Active academic year: {YEAR_NAMES[-1]}")
    print(f"Students:      {stats.get('students', 0)}")
    print(f"Grade records: {stats.get('grades', 0)}")
    print(f"Payments:      {stats.get('payments', 0)}")
    print(f"Announcements: {stats.get('announcements', 0)}")
    print("\nDemo logins (password for all: Demo1234!):")
    for entry in STAFF_BLUEPRINT:
        print(f"  {entry[1]:28} {demo_email(entry[2])}")
    print("\nOpen: http://localhost:3000")
    print("Try: Admin dashboard, Business ledger, Report cards, Academic Rollover preview")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Seed 4 years of demo school data")
    parser.add_argument("--fresh", action="store_true", help="Remove existing demo data first")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without writing")
    args = parser.parse_args()

    with app.app_context():
        if args.fresh and not args.dry_run:
            print("Clearing prior demo data...")
            clear_demo_data()
        elif is_demo_seeded() and not args.fresh and not args.dry_run:
            print("Demo data already exists. Use --fresh to re-seed.")
            print_summary({"students": Student.query.filter(Student.student_id.like(f"{DEMO_STUDENT_PREFIX}%")).count()}, False)
            return

        admin = User.query.filter_by(email=demo_email("demo.admin")).first()
        admin_id = admin.id if admin else None

        staff = ensure_staff(admin_id, args.dry_run)
        if not args.dry_run:
            admin_id = staff["admin"].id

        years = ensure_years(admin_id or 1, args.dry_run)
        classes = ensure_classes(staff, args.dry_run)
        ensure_fees(years, classes, args.dry_run)
        stats = seed_students_and_history(years, classes, staff, args.dry_run)
        print_summary(stats, args.dry_run)


if __name__ == "__main__":
    main()
