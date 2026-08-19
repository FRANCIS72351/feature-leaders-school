from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        # Check users table
        result = db.session.execute(text('PRAGMA table_info(users)'))
        columns = [row[1] for row in result.fetchall()]

        if 'home_address' not in columns:
            db.session.execute(text("ALTER TABLE users ADD COLUMN home_address VARCHAR(255)"))
            print('home_address column added successfully')
        else:
            print('home_address column already exists')

        if 'telephone_number' not in columns:
            db.session.execute(text("ALTER TABLE users ADD COLUMN telephone_number VARCHAR(20)"))
            print('telephone_number column added successfully')
        else:
            print('telephone_number column already exists')

        # Check student table
        result = db.session.execute(text('PRAGMA table_info(student)'))
        columns = [row[1] for row in result.fetchall()]

        if 'tuition_cleared' not in columns:
            db.session.execute(text("ALTER TABLE student ADD COLUMN tuition_cleared BOOLEAN DEFAULT 0"))
            print('tuition_cleared column added successfully')
        else:
            print('tuition_cleared column already exists')

        # Check student_payment table
        result = db.session.execute(text('PRAGMA table_info(student_payment)'))
        columns = [row[1] for row in result.fetchall()]

        if 'installment' not in columns:
            db.session.execute(text("ALTER TABLE student_payment ADD COLUMN installment INTEGER"))
            print('installment column added successfully')
        else:
            print('installment column already exists')

        if 'description' not in columns:
            db.session.execute(text("ALTER TABLE student_payment ADD COLUMN description VARCHAR(250)"))
            print('description column added successfully')
        else:
            print('description column already exists')

        db.session.commit()
    except Exception as e:
        print(f'Error: {e}')
