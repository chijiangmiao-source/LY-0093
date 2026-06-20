import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cinema_schedule.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_no TEXT NOT NULL UNIQUE,
            movie_name TEXT NOT NULL,
            hall_no TEXT NOT NULL,
            planned_start TEXT NOT NULL,
            actual_start TEXT,
            deviation_minutes INTEGER DEFAULT 0,
            deviation_reason TEXT,
            affects_next INTEGER DEFAULT 0,
            affected_record_no TEXT,
            adjustment_suggestion TEXT,
            review_alert INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(hall_no, planned_start)
        )
    """)
    conn.commit()
    conn.close()


def generate_record_no() -> str:
    now = datetime.now()
    date_part = now.strftime("%Y%m%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM schedule_records WHERE record_no LIKE ?",
        (f"REC{date_part}%",)
    )
    count = cursor.fetchone()["cnt"] + 1
    conn.close()
    return f"REC{date_part}{count:04d}"


def calculate_deviation(planned_start: str, actual_start: Optional[str]) -> int:
    if not actual_start:
        return 0
    try:
        planned = datetime.fromisoformat(planned_start)
        actual = datetime.fromisoformat(actual_start)
        delta = actual - planned
        return int(delta.total_seconds() / 60)
    except (ValueError, TypeError):
        return 0


def _check_consecutive_delay(conn: sqlite3.Connection, hall_no: str, planned_start: str, deviation: int) -> bool:
    if deviation <= 0:
        return False
    try:
        current_date = datetime.fromisoformat(planned_start).date()
    except (ValueError, TypeError):
        return False
    prev_date = current_date - timedelta(days=1)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM schedule_records
        WHERE hall_no = ?
          AND DATE(planned_start) = ?
          AND deviation_minutes > 0
          AND record_no != COALESCE((
              SELECT record_no FROM schedule_records WHERE hall_no = ? AND planned_start = ?
          ), '')
    """, (hall_no, prev_date.isoformat(), hall_no, planned_start))
    prev_count = cursor.fetchone()["cnt"]
    return prev_count > 0


def validate_record(data: Dict, record_id: Optional[int] = None) -> Tuple[bool, str]:
    required_fields = ["movie_name", "hall_no", "planned_start"]
    for field in required_fields:
        if not data.get(field):
            return False, f"字段 '{field}' 不能为空"

    if data.get("actual_start"):
        try:
            datetime.fromisoformat(data["actual_start"])
        except (ValueError, TypeError):
            return False, "实际开场时间格式不正确"

    try:
        datetime.fromisoformat(data["planned_start"])
    except (ValueError, TypeError):
        return False, "计划开场时间格式不正确"

    deviation = calculate_deviation(data["planned_start"], data.get("actual_start"))
    if deviation <= -15 and not data.get("adjustment_suggestion"):
        return False, "提前15分钟以上时，调整建议不能为空"

    if data.get("affects_next") and not data.get("affected_record_no"):
        return False, "当影响下一场时，必须填写受影响场次编号"

    return True, ""


def create_record(data: Dict) -> Tuple[bool, str, Optional[Dict]]:
    valid, msg = validate_record(data)
    if not valid:
        return False, msg, None

    record_no = data.get("record_no") or generate_record_no()
    deviation = calculate_deviation(data["planned_start"], data.get("actual_start"))

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM schedule_records WHERE hall_no = ? AND planned_start = ?
        """, (data["hall_no"], data["planned_start"]))
        if cursor.fetchone():
            conn.close()
            return False, "同一影厅同一计划开场时间已存在记录", None

        review_alert = 1 if _check_consecutive_delay(conn, data["hall_no"], data["planned_start"], deviation) else 0

        cursor.execute("""
            INSERT INTO schedule_records (
                record_no, movie_name, hall_no, planned_start, actual_start,
                deviation_minutes, deviation_reason, affects_next, affected_record_no,
                adjustment_suggestion, review_alert
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record_no,
            data["movie_name"],
            data["hall_no"],
            data["planned_start"],
            data.get("actual_start"),
            deviation,
            data.get("deviation_reason", ""),
            1 if data.get("affects_next") else 0,
            data.get("affected_record_no", ""),
            data.get("adjustment_suggestion", ""),
            review_alert
        ))
        conn.commit()
        record_id = cursor.lastrowid

        _refresh_review_alerts(conn)

        cursor.execute("SELECT * FROM schedule_records WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        conn.close()
        return True, "创建成功", dict(row) if row else None
    except sqlite3.IntegrityError as e:
        conn.close()
        return False, f"数据冲突: {str(e)}", None
    except Exception as e:
        conn.close()
        return False, f"创建失败: {str(e)}", None


def update_record(record_id: int, data: Dict) -> Tuple[bool, str, Optional[Dict]]:
    valid, msg = validate_record(data, record_id)
    if not valid:
        return False, msg, None

    deviation = calculate_deviation(data["planned_start"], data.get("actual_start"))

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM schedule_records
            WHERE hall_no = ? AND planned_start = ? AND id != ?
        """, (data["hall_no"], data["planned_start"], record_id))
        if cursor.fetchone():
            conn.close()
            return False, "同一影厅同一计划开场时间已存在其他记录", None

        review_alert = 1 if _check_consecutive_delay(conn, data["hall_no"], data["planned_start"], deviation) else 0

        cursor.execute("""
            UPDATE schedule_records SET
                movie_name = ?,
                hall_no = ?,
                planned_start = ?,
                actual_start = ?,
                deviation_minutes = ?,
                deviation_reason = ?,
                affects_next = ?,
                affected_record_no = ?,
                adjustment_suggestion = ?,
                review_alert = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            data["movie_name"],
            data["hall_no"],
            data["planned_start"],
            data.get("actual_start"),
            deviation,
            data.get("deviation_reason", ""),
            1 if data.get("affects_next") else 0,
            data.get("affected_record_no", ""),
            data.get("adjustment_suggestion", ""),
            review_alert,
            record_id
        ))
        conn.commit()

        _refresh_review_alerts(conn)

        cursor.execute("SELECT * FROM schedule_records WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        conn.close()
        return True, "更新成功", dict(row) if row else None
    except Exception as e:
        conn.close()
        return False, f"更新失败: {str(e)}", None


def delete_record(record_id: int) -> Tuple[bool, str]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM schedule_records WHERE id = ?", (record_id,))
        conn.commit()
        _refresh_review_alerts(conn)
        conn.close()
        return True, "删除成功"
    except Exception as e:
        conn.close()
        return False, f"删除失败: {str(e)}"


def _refresh_review_alerts(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("SELECT id, hall_no, planned_start, deviation_minutes FROM schedule_records")
    all_records = cursor.fetchall()
    for rec in all_records:
        alert = 1 if _check_consecutive_delay(conn, rec["hall_no"], rec["planned_start"], rec["deviation_minutes"]) else 0
        cursor.execute("UPDATE schedule_records SET review_alert = ? WHERE id = ?", (alert, rec["id"]))
    conn.commit()


def get_all_records() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM schedule_records ORDER BY planned_start DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_record_by_id(record_id: int) -> Optional[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM schedule_records WHERE id = ?", (record_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_records_by_hall(hall_no: str) -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM schedule_records WHERE hall_no = ? ORDER BY planned_start DESC", (hall_no,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_halls() -> List[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT hall_no FROM schedule_records ORDER BY hall_no")
    rows = cursor.fetchall()
    conn.close()
    return [row["hall_no"] for row in rows]


def get_reason_statistics() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT deviation_reason,
               COUNT(*) as count,
               AVG(ABS(deviation_minutes)) as avg_deviation,
               SUM(CASE WHEN ABS(deviation_minutes) > 15 THEN 1 ELSE 0 END) as serious_count
        FROM schedule_records
        WHERE deviation_reason IS NOT NULL AND deviation_reason != ''
        GROUP BY deviation_reason
        ORDER BY count DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_time_slot_statistics() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            CASE
                WHEN CAST(strftime('%H', planned_start) AS INTEGER) < 12 THEN '上午'
                WHEN CAST(strftime('%H', planned_start) AS INTEGER) < 18 THEN '下午'
                ELSE '晚上'
            END as time_slot,
            COUNT(*) as count,
            AVG(ABS(deviation_minutes)) as avg_deviation,
            SUM(CASE WHEN deviation_minutes > 0 THEN 1 ELSE 0 END) as delayed_count
        FROM schedule_records
        GROUP BY time_slot
        ORDER BY time_slot
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_daily_deviation_trend() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATE(planned_start) as date,
               COUNT(*) as count,
               AVG(ABS(deviation_minutes)) as avg_deviation
        FROM schedule_records
        GROUP BY DATE(planned_start)
        ORDER BY date DESC
        LIMIT 30
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_review_alerts() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM schedule_records
        WHERE review_alert = 1
        ORDER BY planned_start DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
