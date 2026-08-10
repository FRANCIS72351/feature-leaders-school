"""Development seed data aligned with current models. Run: python seed_data.py"""
from datetime import date, datetime, timezone

from werkzeug.security import generate_password_hash

from app import app, db
from models import (
    AcademicYear,
    Announcement,
    Class,
    Grade,
    Sponsor,
    Student,
    StudentPayment,
    Teacher,
    User,
)


def seed():
    with app.app_context():
        db.drop_all()
        db.create_all()

        admin = User(
            email='admin@example.com',
            role='admin',
            password_hash=generate_password_hash('adminpass'),
            full_name='Admin User',
            username='admin',
        )
        teacher_user = User(
            email='teacher@example.com',
            role='teacher',
            password_hash=generate_password_hash('teacherpass'),
            full_name='Alice Teacher',
            username='teacher',
        )
        student_user = User(
            email='student@example.com',
            role='student',
            password_hash=generate_password_hash('studentpass'),
            full_name='Bob Student',
            username='student',
        )
        parent = User(
            email='parent@example.com',
            role='parent',
            password_hash=generate_password_hash('parentpass'),
            full_name='Parent User',
            username='parent',
        )
        sponsor_user = User(
            email='sponsor@example.com',
            role='sponsor',
            password_hash=generate_password_hash('sponsorpass'),
            full_name='Sponsor User',
            username='sponsor',
        )
        db.session.add_all([admin, teacher_user, student_user, parent, sponsor_user])
        db.session.commit()

        year = AcademicYear(
            name='2025-2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            is_active=True,
        )
        db.session.add(year)
        db.session.commit()

        teacher = Teacher(
            user_id=teacher_user.id,
            first_name='Alice',
            last_name='Teacher',
            subject='Mathematics',
        )
        db.session.add(teacher)
        db.session.commit()

        klass = Class(
            name='Grade 10 - Science',
            grade_level=10,
            stream='Science',
            teacher_id=teacher.id,
            yearly_fees=500.00,
        )
        db.session.add(klass)
        db.session.commit()

        student = Student(
            user_id=student_user.id,
            student_id='S1001',
            first_name='Bob',
            last_name='Student',
            dob=date(2007, 5, 10),
            gender='Male',
            parent_email='parent@example.com',
            klass_id=klass.id,
            academic_year_id=year.id,
            tuition_cleared=True,
        )
        db.session.add(student)
        db.session.commit()

        grade = Grade(
            student_id=student.id,
            teacher_id=teacher.id,
            class_id=klass.id,
            academic_year_id=year.id,
            subject='Mathematics',
            subject_name='Mathematics',
            marking_period=1,
            period='Period 1',
            ca_score=36,
            exam_score=32,
            score=68,
            remarks='Satisfactory',
            submitted=True,
        )
        payment = StudentPayment(
            student_id=student.id,
            academic_year_id=year.id,
            term=1,
            amount_paid=150.00,
            description='Tuition term 1',
            paid_on=datetime.now(timezone.utc),
        )
        sponsorship = Sponsor(
            user_id=sponsor_user.id,
            student_id=student.id,
            amount=200.00,
        )
        announcement = Announcement(
            title='Welcome',
            body='Welcome to the new term',
            audience='all',
            author='admin@example.com',
        )
        db.session.add_all([grade, payment, sponsorship, announcement])
        db.session.commit()

        print('Seeded development data.')
        print('Admin:   admin@example.com / adminpass')
        print('Teacher: teacher@example.com / teacherpass')
        print('Student: student@example.com / studentpass')


if __name__ == '__main__':
    seed()
