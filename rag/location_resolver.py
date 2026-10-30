import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "facilities.db"


def resolve_location(keyword: str) -> dict | None:
    """
    장소명으로 facilities.db에서 좌표를 찾는다.
    예: 함덕해수욕장, 제주올레캠핑, 제주시청
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    rows = cur.execute(
        """
        SELECT id, category, name, lat, lon, road_addr, lotno_addr
        FROM facilities
        WHERE name LIKE ?
          AND lat IS NOT NULL
          AND lon IS NOT NULL
        LIMIT 10
        """,
        (f"%{keyword}%",),
    ).fetchall()

    con.close()

    if not rows:
        return None

    row = rows[0]

    return {
        "id": row["id"],
        "category": row["category"],
        "name": row["name"],
        "lat": row["lat"],
        "lon": row["lon"],
        "road_addr": row["road_addr"],
        "lotno_addr": row["lotno_addr"],
    }


if __name__ == "__main__":
    tests = [
        "함덕",
        "함덕해수욕장",
        "제주",
        "제주올레캠핑",
    ]

    for t in tests:
        print("\n검색어:", t)
        print(resolve_location(t))