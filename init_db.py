from app import app, db
from sqlalchemy import text, exc

# Schema patches for legacy SQLite databases (table names match models.py)
SCHEMA_UPDATES = (
    {"table": "users", "description": "Add photo column", "sql": "ALTER TABLE users ADD COLUMN photo VARCHAR(255);"},
    {"table": "users", "description": "Add totp_secret column", "sql": "ALTER TABLE users ADD COLUMN totp_secret VARCHAR(32);"},
    {"table": "users", "description": "Add username column", "sql": "ALTER TABLE users ADD COLUMN username VARCHAR(80);"},

    {"table": "grades", "description": "Add period column", "sql": "ALTER TABLE grades ADD COLUMN period VARCHAR(50);"},
    {"table": "grades", "description": "Add activity_type column", "sql": "ALTER TABLE grades ADD COLUMN activity_type VARCHAR(50);"},
    {"table": "grades", "description": "Add ca_score column", "sql": "ALTER TABLE grades ADD COLUMN ca_score FLOAT;"},
    {"table": "grades", "description": "Add exam_score column", "sql": "ALTER TABLE grades ADD COLUMN exam_score FLOAT;"},
    {"table": "grades", "description": "Add marking_period column", "sql": "ALTER TABLE grades ADD COLUMN marking_period INTEGER;"},

    {"table": "classes", "description": "Add yearly_fees column", "sql": "ALTER TABLE classes ADD COLUMN yearly_fees NUMERIC(10,2) DEFAULT 0.0;"},
    {"table": "classes", "description": "Add grading_scheme column", "sql": "ALTER TABLE classes ADD COLUMN grading_scheme TEXT;"},

    {"table": "students", "description": "Add status column", "sql": "ALTER TABLE students ADD COLUMN status VARCHAR(20) DEFAULT 'ACTIVE';"},
    {"table": "students", "description": "Add grade_level column", "sql": "ALTER TABLE students ADD COLUMN grade_level INTEGER;"},
    {"table": "students", "description": "Add level column", "sql": "ALTER TABLE students ADD COLUMN level VARCHAR(50);"},
    {"table": "students", "description": "Add student_id_code column", "sql": "ALTER TABLE students ADD COLUMN student_id_code VARCHAR(50);"},
    {"table": "students", "description": "Add klass_id column", "sql": "ALTER TABLE students ADD COLUMN klass_id INTEGER REFERENCES classes(id);"},
    {"table": "students", "description": "Add academic_year_id column", "sql": "ALTER TABLE students ADD COLUMN academic_year_id INTEGER REFERENCES academic_years(id);"},
    {"table": "students", "description": "Add registration_type column", "sql": "ALTER TABLE students ADD COLUMN registration_type VARCHAR(20) DEFAULT 'New';"},
    {"table": "students", "description": "Add created_at column", "sql": "ALTER TABLE students ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP;"},
    {"table": "students", "description": "Add tuition_cleared column", "sql": "ALTER TABLE students ADD COLUMN tuition_cleared BOOLEAN DEFAULT 0;"},
    {"table": "students", "description": "Add registrar column", "sql": "ALTER TABLE students ADD COLUMN registrar VARCHAR(100);"},
    {"table": "students", "description": "Add registration_fees column", "sql": "ALTER TABLE students ADD COLUMN registration_fees NUMERIC(10,2) DEFAULT 0.0;"},
    {"table": "students", "description": "Add is_promoted column", "sql": "ALTER TABLE students ADD COLUMN is_promoted BOOLEAN DEFAULT 0;"},
    {"table": "students", "description": "Add is_registered column", "sql": "ALTER TABLE students ADD COLUMN is_registered BOOLEAN DEFAULT 1;"},

    {"table": "business_transactions", "description": "Add academic_year column", "sql": "ALTER TABLE business_transactions ADD COLUMN academic_year VARCHAR(32);"},
    {"table": "business_transactions", "description": "Add is_deleted column", "sql": "ALTER TABLE business_transactions ADD COLUMN is_deleted BOOLEAN DEFAULT 0;"},
    {"table": "business_transactions", "description": "Add deleted_at column", "sql": "ALTER TABLE business_transactions ADD COLUMN deleted_at DATETIME;"},
    {"table": "business_transactions", "description": "Add deleted_by_id column", "sql": "ALTER TABLE business_transactions ADD COLUMN deleted_by_id INTEGER;"},

    {"table": "school_fees", "description": "Add class_id column", "sql": "ALTER TABLE school_fees ADD COLUMN class_id INTEGER REFERENCES classes(id);"},
    {"table": "school_fees", "description": "Add fee_type column", "sql": "ALTER TABLE school_fees ADD COLUMN fee_type VARCHAR(30) DEFAULT 'tuition';"},
)

if __name__ == "__main__":
    with app.app_context():
        print("Ensuring all tables exist...")
        db.create_all()

        print("Applying schema updates for existing tables...")
        for update in SCHEMA_UPDATES:
            try:
                db.session.execute(text(update["sql"]))
                db.session.commit()
                print(f"Applied: {update['description']} on '{update['table']}'")
            except exc.OperationalError as e:
                db.session.rollback()
                if "duplicate column name" in str(e).lower():
                    print(f"Skipped: {update['description']} (column already exists)")
                else:
                    print(f"Error applying '{update['description']}': {e}")
            except Exception as e:
                db.session.rollback()
                print(f"Error applying '{update['description']}': {e}")

        print("\nDatabase synchronization complete.")
