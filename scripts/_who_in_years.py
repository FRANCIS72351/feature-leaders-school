#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app, db, get_active_academic_year
from models import AcademicYear, Student

with app.app_context():
    active = get_active_academic_year()
    for y in AcademicYear.query.all():
        studs = Student.query.filter_by(academic_year_id=y.id).all()
        if studs:
            print(f"\n{y.name} (id={y.id}, is_active={y.is_active}): {len(studs)}")
            for s in studs[:10]:
                print(f"  {s.full_name} status={s.status} klass={s.klass_id} grade={s.grade_level}")
