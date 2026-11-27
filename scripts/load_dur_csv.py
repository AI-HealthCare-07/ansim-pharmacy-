import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv("envs/.local.env")

TYPE_MAP = {
    "병용금기": "CONCOMITANT",
    "임부금기": "PREGNANCY",
    "특정연령대금기": "AGE",
    "연령금기": "AGE",
    "용량주의": "DOSAGE",
    "투여기간주의": "DURATION",
    "노인주의": "ELDERLY",
    "노인주의_해열진통소염제": "ELDERLY",
    "효능군중복": "DUPLICATE_CLASS",
    "서방정분할주의": "SPLIT_CAUTION",
}

def clean(val):
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s if s and s.lower() != "nan" else None

def main():
    csv_path = "data/raw/의약품안전사용서비스(DUR)_통합_성분단위 2026.6.csv"
    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")

    rows = []
    for _, r in df.iterrows():
        raw_type = clean(r.get("금기유형")) or "OTHER"
        dur_type = TYPE_MAP.get(raw_type, raw_type)

        age_val = clean(r.get("특정연령"))
        age_unit = clean(r.get("특정연령단위"))
        age_cond = clean(r.get("연령처리조건"))
        age_limit = " ".join([x for x in [age_val, age_unit, age_cond] if x]) or None

        rows.append((
            dur_type,
            clean(r.get("성분코드")),
            clean(r.get("성분명")),
            clean(r.get("병용성분코드")),
            clean(r.get("병용성분명")),
            clean(r.get("금기등급")),
            age_limit,
            clean(r.get("상세정보")),
            clean(r.get("비고")),
        ))

    conn = psycopg2.connect(
        host="localhost",
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE dur_rules RESTART IDENTITY;")

    sql = """
        INSERT INTO dur_rules (
            dur_type, ingr_code_a, ingr_name_a,
            ingr_code_b, ingr_name_b, grade,
            age_limit, prohibition_content, remark
        ) VALUES %s
    """
    execute_values(cur, sql, rows, page_size=5000)
    conn.commit()

    cur.execute("SELECT dur_type, COUNT(*) FROM dur_rules GROUP BY dur_type ORDER BY COUNT(*) DESC;")
    summary = cur.fetchall()
    cur.close()
    conn.close()

    print("DUR 적재 완료! 유형별 건수:")
    for dtype, cnt in summary:
        print(f" - {dtype}: {cnt:,}건")

if __name__ == "__main__":
    main()
