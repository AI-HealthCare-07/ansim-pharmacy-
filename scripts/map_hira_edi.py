import os
from pathlib import Path
import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv("envs/.local.env")

def find_hira_excel(raw_dir: Path) -> Path:
    candidates = list(raw_dir.glob("*.xlsx")) + list(raw_dir.glob("*.xls"))
    hira = [f for f in candidates if any(k in f.name for k in ["급여", "상한", "약제", "목록", "2026"])]
    target = hira if hira else candidates
    if not target:
        raise FileNotFoundError("data/raw/ 폴더에 엑셀 파일이 없습니다. 브라우저 다운로드 완료 여부를 확인해 주세요.")
    return sorted(target, key=lambda p: p.stat().st_mtime)[-1]

def main():
    excel_path = find_hira_excel(Path("data/raw"))
    print(f"대상 파일 로드 중: {excel_path.name}")

    preview = pd.read_excel(excel_path, nrows=15, header=None, dtype=str)
    header_row = 0
    for idx, row in preview.iterrows():
        row_str = " ".join(row.dropna().astype(str))
        if "제품코드" in row_str and "주성분코드" in row_str:
            header_row = idx
            break

    df = pd.read_excel(excel_path, header=header_row, dtype=str)
    df.columns = [str(c).strip().replace("\n", "") for c in df.columns]

    code_col = next(c for c in df.columns if "제품코드" in c)
    ingr_col = next(c for c in df.columns if "주성분코드" in c)
    name_col = next((c for c in df.columns if "품목명" in c or "제품명" in c), None)

    df = df[[code_col, ingr_col] + ([name_col] if name_col else [])].dropna(subset=[code_col, ingr_col])
    df[code_col] = df[code_col].str.strip()
    df[ingr_col] = df[ingr_col].str.strip()
    df = df.drop_duplicates(subset=[code_col])

    conn = psycopg2.connect(
        host="localhost",
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )
    cur = conn.cursor()

    updated = 0
    for _, row in df.iterrows():
        edi = row[code_col]
        ingr = row[ingr_col]
        group_code = ingr[:4] if len(ingr) >= 4 else ingr
        prod_name = row[name_col].strip() if name_col and pd.notna(row[name_col]) else None

        cur.execute(
            """
            UPDATE medicine_edi_codes
               SET main_ingredient_code = %s,
                   ingredient_group_code = %s,
                   product_name_hira = COALESCE(%s, product_name_hira)
             WHERE edi_code = %s
            """,
            (ingr, group_code, prod_name, edi),
        )
        updated += cur.rowcount

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM medicine_edi_codes WHERE main_ingredient_code IS NOT NULL;")
    total_mapped = cur.fetchone()
    cur.close()
    conn.close()

    print(f"매핑 완료! 업데이트된 행: {updated}건 / 주성분코드 보유 총 건수: {total_mapped}건")

if __name__ == "__main__":
    main()
