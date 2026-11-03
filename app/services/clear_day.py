"""Clear only the intake view; production and source records are durable."""
from app.core import work_dates
from app.services import pre_gpt_pipeline as intake


def clear_today(bridge=None, day=None):
    """Hide the Task Center view of the day currently selected in Task Center (not the calendar 'today')."""
    day = day or work_dates.active()
    con=intake.init_db()
    try:
        con.execute("INSERT OR REPLACE INTO intake_view_state(day,hidden) VALUES(?,1)", (day,))
        con.commit()
    finally:
        con.close()
    intake.log.info("[SAFE_CLEAR] date=%s intake view hidden; production records unchanged", day)
    return dict(tasks=0, groups=0, assets=0, studio_videos=0, segments=0, date=day)
