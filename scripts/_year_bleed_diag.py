#!/usr/bin/env python3
"""Diagnose academic year roster bleed-through."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (
    app,
    db,
    get_active_academic_year,
    _students_for_display_year,
    _principal_build_class_portfolios,
    students_for_academic_year,
)
from models import AcademicYear, Student, Class


def main():
    with app.app_context():
        active = get_active_academic_year()
        years = AcademicYear.query.order_by(AcademicYear.name.desc()).all()
        print("Active year:", active.name if active else None, active.id if active else None)
        for y in years[:8]:
            cnt = students_for_academic_year(y.id).count()
            hist = _students_for_display_year(y, history_mode=True).count()
            live = _students_for_display_year(y, history_mode=False).count()
            print(
                f"  {y.name} (active={y.is_active}): "
                f"strict={cnt}, hist_mode={hist}, live_mode={live}"
            )

        if not active:
            return

        portfolios = _principal_build_class_portfolios(active, viewing_archived=False)
        nonzero = [p for p in portfolios if p["student_count"] > 0]
        print(f"Active year portfolios with students: {len(nonzero)}")
        for p in nonzero[:12]:
            k = p["klass"]
            strict = Student.query.filter_by(
                klass_id=k.id, academic_year_id=active.id
            ).count()
            klass_only = Student.query.filter_by(klass_id=k.id).count()
            sc = p["student_count"]
            print(f"  {k.name}: portfolio={sc}, strict={strict}, klass_only={klass_only}")

        bleed = Student.query.filter(
            Student.klass_id.isnot(None),
            Student.academic_year_id != active.id,
            Student.status == "ACTIVE",
        ).count()
        print(f"ACTIVE students with klass but NOT active year_id: {bleed}")

        wrong = (
            Student.query.filter(
                Student.klass_id.isnot(None),
                Student.academic_year_id != active.id,
            )
            .limit(8)
            .all()
        )
        for s in wrong:
            y = db.session.get(AcademicYear, s.academic_year_id)
            c = db.session.get(Class, s.klass_id)
            print(
                f"  bleed: {s.first_name} {s.last_name} "
                f"year={y.name if y else None} "
                f"class={c.name if c else None} status={s.status}"
            )


if __name__ == "__main__":
    main()
