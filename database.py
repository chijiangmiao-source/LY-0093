import sqlite3
import os
import json
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
            handling_status TEXT DEFAULT '待处理',
            responsible_person TEXT,
            completion_time TEXT,
            review_conclusion TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(hall_no, planned_start)
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE schedule_records ADD COLUMN handling_status TEXT DEFAULT '待处理'")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE schedule_records ADD COLUMN responsible_person TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE schedule_records ADD COLUMN completion_time TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE schedule_records ADD COLUMN review_conclusion TEXT")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monthly_archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_month TEXT NOT NULL UNIQUE,
            archive_no TEXT NOT NULL UNIQUE,
            total_shows INTEGER DEFAULT 0,
            serious_deviation_count INTEGER DEFAULT 0,
            main_deviation_reason TEXT,
            hall_completion_rates TEXT,
            unclosed_count INTEGER DEFAULT 0,
            deviation_reason_summary TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                adjustment_suggestion, review_alert, handling_status,
                responsible_person, completion_time, review_conclusion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            review_alert,
            data.get("handling_status", "待处理"),
            data.get("responsible_person", ""),
            data.get("completion_time", ""),
            data.get("review_conclusion", ""),
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
                handling_status = ?,
                responsible_person = ?,
                completion_time = ?,
                review_conclusion = ?,
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
            data.get("handling_status", "待处理"),
            data.get("responsible_person", ""),
            data.get("completion_time", ""),
            data.get("review_conclusion", ""),
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


def get_records_with_filters(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    hall_no: Optional[str] = None,
    movie_name: Optional[str] = None,
    handling_status: Optional[str] = None,
    deviation_reason: Optional[str] = None
) -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM schedule_records WHERE 1=1"
    params = []
    
    if start_date:
        query += " AND DATE(planned_start) >= ?"
        params.append(start_date)
    if end_date:
        query += " AND DATE(planned_start) <= ?"
        params.append(end_date)
    if hall_no:
        query += " AND hall_no = ?"
        params.append(hall_no)
    if movie_name:
        query += " AND movie_name LIKE ?"
        params.append(f"%{movie_name}%")
    if handling_status:
        query += " AND handling_status = ?"
        params.append(handling_status)
    if deviation_reason:
        query += " AND deviation_reason LIKE ?"
        params.append(f"%{deviation_reason}%")
    
    query += " ORDER BY planned_start DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_handling_info(
    record_id: int,
    handling_status: str,
    responsible_person: str,
    completion_time: Optional[str],
    review_conclusion: str
) -> Tuple[bool, str]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE schedule_records SET
                handling_status = ?,
                responsible_person = ?,
                completion_time = ?,
                review_conclusion = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (handling_status, responsible_person, completion_time, review_conclusion, record_id))
        conn.commit()
        conn.close()
        return True, "更新成功"
    except Exception as e:
        conn.close()
        return False, f"更新失败: {str(e)}"


def get_hall_completion_rate() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT hall_no,
               COUNT(*) as total_count,
               SUM(CASE WHEN handling_status = '已完成' THEN 1 ELSE 0 END) as completed_count,
               ROUND(
                   SUM(CASE WHEN handling_status = '已完成' THEN 1 ELSE 0 END) * 100.0 / 
                   NULLIF(COUNT(*), 0), 2
               ) as completion_rate
        FROM schedule_records
        GROUP BY hall_no
        ORDER BY hall_no
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_reason_handling_time() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            COALESCE(NULLIF(deviation_reason, ''), '未填写') as deviation_reason,
            COUNT(*) as count,
            ROUND(AVG(
                CASE 
                    WHEN completion_time IS NOT NULL AND completion_time != '' 
                         AND actual_start IS NOT NULL AND actual_start != '' THEN
                        CAST((julianday(completion_time) - julianday(actual_start)) * 24 * 60 AS INTEGER)
                    ELSE NULL 
                END
            ), 2) as avg_handling_minutes
        FROM schedule_records
        WHERE handling_status = '已完成'
        GROUP BY deviation_reason
        ORDER BY count DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_incomplete_records() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM schedule_records
        WHERE handling_status IN ('待处理', '处理中')
           OR handling_status IS NULL
        ORDER BY planned_start DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_handling_trend() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            DATE(COALESCE(completion_time, updated_at)) as date,
            COUNT(*) as total_handled,
            SUM(CASE WHEN handling_status = '已完成' THEN 1 ELSE 0 END) as completed_count,
            SUM(CASE WHEN handling_status = '处理中' THEN 1 ELSE 0 END) as processing_count,
            SUM(CASE WHEN handling_status = '待处理' THEN 1 ELSE 0 END) as pending_count
        FROM schedule_records
        GROUP BY DATE(COALESCE(completion_time, updated_at))
        ORDER BY date DESC
        LIMIT 30
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_handling_statistics() -> Dict:
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM schedule_records")
    total = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as pending FROM schedule_records WHERE handling_status = '待处理' OR handling_status IS NULL")
    pending = cursor.fetchone()["pending"]
    
    cursor.execute("SELECT COUNT(*) as processing FROM schedule_records WHERE handling_status = '处理中'")
    processing = cursor.fetchone()["processing"]
    
    cursor.execute("SELECT COUNT(*) as completed FROM schedule_records WHERE handling_status = '已完成'")
    completed = cursor.fetchone()["completed"]
    
    cursor.execute("""
        SELECT ROUND(AVG(
            CASE 
                WHEN completion_time IS NOT NULL AND completion_time != '' 
                     AND actual_start IS NOT NULL AND actual_start != '' THEN
                    CAST((julianday(completion_time) - julianday(actual_start)) * 24 * 60 AS INTEGER)
                ELSE NULL 
            END
        ), 2) as avg_handling_time
        FROM schedule_records
        WHERE handling_status = '已完成'
    """)
    avg_handling_time = cursor.fetchone()["avg_handling_time"]
    
    conn.close()
    
    completion_rate = round(completed * 100.0 / total, 2) if total > 0 else 0
    
    return {
        "total": total,
        "pending": pending,
        "processing": processing,
        "completed": completed,
        "completion_rate": completion_rate,
        "avg_handling_time": avg_handling_time or 0
    }


def generate_archive_no() -> str:
    now = datetime.now()
    date_part = now.strftime("%Y%m")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM monthly_archives WHERE archive_no LIKE ?",
        (f"ARCH{date_part}%",)
    )
    count = cursor.fetchone()["cnt"] + 1
    conn.close()
    return f"ARCH{date_part}{count:03d}"


def get_monthly_summary_data(archive_month: str) -> Dict:
    conn = get_connection()
    cursor = conn.cursor()
    
    start_date = f"{archive_month}-01"
    if archive_month.endswith("-12"):
        next_year = int(archive_month[:4]) + 1
        end_date = f"{next_year}-01-01"
    else:
        year = int(archive_month[:4])
        month = int(archive_month[5:7]) + 1
        end_date = f"{year:04d}-{month:02d}-01"
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total_shows,
            SUM(CASE WHEN ABS(deviation_minutes) > 15 THEN 1 ELSE 0 END) as serious_deviation_count
        FROM schedule_records
        WHERE DATE(planned_start) >= ? AND DATE(planned_start) < ?
    """, (start_date, end_date))
    summary = dict(cursor.fetchone())
    
    cursor.execute("""
        SELECT deviation_reason, COUNT(*) as cnt
        FROM schedule_records
        WHERE DATE(planned_start) >= ? AND DATE(planned_start) < ?
          AND deviation_reason IS NOT NULL AND deviation_reason != ''
        GROUP BY deviation_reason
        ORDER BY cnt DESC
    """, (start_date, end_date))
    reason_rows = cursor.fetchall()
    reason_summary = [dict(r) for r in reason_rows]
    main_reason = reason_summary[0]["deviation_reason"] if reason_summary else "无"
    
    cursor.execute("""
        SELECT hall_no,
               COUNT(*) as total_count,
               SUM(CASE WHEN handling_status = '已完成' THEN 1 ELSE 0 END) as completed_count,
               ROUND(
                   SUM(CASE WHEN handling_status = '已完成' THEN 1 ELSE 0 END) * 100.0 / 
                   NULLIF(COUNT(*), 0), 2
               ) as completion_rate
        FROM schedule_records
        WHERE DATE(planned_start) >= ? AND DATE(planned_start) < ?
        GROUP BY hall_no
        ORDER BY hall_no
    """, (start_date, end_date))
    hall_rows = cursor.fetchall()
    hall_completion = [dict(r) for r in hall_rows]
    
    cursor.execute("""
        SELECT COUNT(*) as unclosed_count
        FROM schedule_records
        WHERE DATE(planned_start) >= ? AND DATE(planned_start) < ?
          AND (handling_status IN ('待处理', '处理中') OR handling_status IS NULL)
    """, (start_date, end_date))
    unclosed_count = cursor.fetchone()["unclosed_count"] or 0
    
    conn.close()
    
    return {
        "archive_month": archive_month,
        "total_shows": summary["total_shows"] or 0,
        "serious_deviation_count": summary["serious_deviation_count"] or 0,
        "main_deviation_reason": main_reason,
        "hall_completion_rates": hall_completion,
        "unclosed_count": unclosed_count,
        "deviation_reason_summary": reason_summary
    }


def create_monthly_archive(archive_month: str) -> Tuple[bool, str, Optional[Dict]]:
    summary = get_monthly_summary_data(archive_month)
    
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM monthly_archives WHERE archive_month = ?", (archive_month,))
        if cursor.fetchone():
            conn.close()
            return False, f"{archive_month} 已存在归档记录", None
        
        archive_no = generate_archive_no()
        
        cursor.execute("""
            INSERT INTO monthly_archives (
                archive_month, archive_no, total_shows, serious_deviation_count,
                main_deviation_reason, hall_completion_rates, unclosed_count,
                deviation_reason_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            archive_month,
            archive_no,
            summary["total_shows"],
            summary["serious_deviation_count"],
            summary["main_deviation_reason"],
            json.dumps(summary["hall_completion_rates"], ensure_ascii=False),
            summary["unclosed_count"],
            json.dumps(summary["deviation_reason_summary"], ensure_ascii=False)
        ))
        conn.commit()
        archive_id = cursor.lastrowid
        
        cursor.execute("SELECT * FROM monthly_archives WHERE id = ?", (archive_id,))
        row = cursor.fetchone()
        conn.close()
        
        result = dict(row) if row else None
        if result:
            result["hall_completion_rates"] = json.loads(result["hall_completion_rates"]) if result["hall_completion_rates"] else []
            result["deviation_reason_summary"] = json.loads(result["deviation_reason_summary"]) if result["deviation_reason_summary"] else []
        return True, "归档创建成功", result
    except Exception as e:
        conn.close()
        return False, f"归档创建失败: {str(e)}", None


def get_all_archives() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM monthly_archives ORDER BY archive_month DESC")
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        r = dict(row)
        r["hall_completion_rates"] = json.loads(r["hall_completion_rates"]) if r["hall_completion_rates"] else []
        r["deviation_reason_summary"] = json.loads(r["deviation_reason_summary"]) if r["deviation_reason_summary"] else []
        results.append(r)
    return results


def get_archive_by_id(archive_id: int) -> Optional[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM monthly_archives WHERE id = ?", (archive_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        r = dict(row)
        r["hall_completion_rates"] = json.loads(r["hall_completion_rates"]) if r["hall_completion_rates"] else []
        r["deviation_reason_summary"] = json.loads(r["deviation_reason_summary"]) if r["deviation_reason_summary"] else []
        return r
    return None


def get_archive_by_month(archive_month: str) -> Optional[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM monthly_archives WHERE archive_month = ?", (archive_month,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        r = dict(row)
        r["hall_completion_rates"] = json.loads(r["hall_completion_rates"]) if r["hall_completion_rates"] else []
        r["deviation_reason_summary"] = json.loads(r["deviation_reason_summary"]) if r["deviation_reason_summary"] else []
        return r
    return None


def delete_archive(archive_id: int) -> Tuple[bool, str]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM monthly_archives WHERE id = ?", (archive_id,))
        conn.commit()
        conn.close()
        return True, "归档删除成功"
    except Exception as e:
        conn.close()
        return False, f"归档删除失败: {str(e)}"
