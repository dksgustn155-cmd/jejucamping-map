import math
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "facilities.db"


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0

    lat1, lon1, lat2, lon2 = map(
        math.radians,
        [lat1, lon1, lat2, lon2]
    )

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return r * c


def find_nearby_facilities(
    lat: float,
    lon: float,
    facility_type: str | None = None,
    radius_km: float = 3.0,
    limit: int = 5,
):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if facility_type:
        rows = cur.execute(
            """
            SELECT *
            FROM facilities
            WHERE lat IS NOT NULL
              AND lon IS NOT NULL
              AND category = ?
            """,
            (facility_type,),
        ).fetchall()
    else:
        rows = cur.execute(
            """
            SELECT *
            FROM facilities
            WHERE lat IS NOT NULL
              AND lon IS NOT NULL
            """
        ).fetchall()

    results = []

    for row in rows:
        dist = haversine_km(lat, lon, row["lat"], row["lon"])

        if dist <= radius_km:
            results.append(
                {
                    "id": row["id"],
                    "category": row["category"],
                    "name": row["name"],
                    "lat": row["lat"],
                    "lon": row["lon"],
                    "road_addr": row["road_addr"],
                    "lotno_addr": row["lotno_addr"],
                    "open_hours": row["open_hours"],
                    "tel": row["tel"],
                    "extra": row["extra"],
                    "distance_km": round(dist, 3),
                }
            )

    con.close()

    results.sort(key=lambda x: x["distance_km"])
    return results[:limit]


if __name__ == "__main__":
    # 제주 예시 좌표
    lat = 33.4996
    lon = 126.5312

    results = find_nearby_facilities(
        lat=lat,
        lon=lon,
        facility_type="restroom",
        radius_km=3,
        limit=5,
    )

    for i, r in enumerate(results, start=1):
        print(f"\n[{i}] {r['name']} / {r['distance_km']}km")
        print(r)