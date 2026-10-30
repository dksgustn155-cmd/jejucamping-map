"""
BigQuery 적재 + GIS 전처리 스크립트
- facilities.db(SQLite) → BigQuery 테이블 (GEOGRAPHY 컬럼)
- BigQuery GIS로 시설간 근접도 전처리 (해변↔화장실↔주차장 300m 내 카운트)
- 모드1(대화형 추천)이 이 BQ 테이블을 질의

전제:
  pip install google-cloud-bigquery
  gcloud auth application-default login   (또는 서비스계정 credentials.json)
실행: python data_pipeline/load_bigquery.py

⚠️ 지오코딩(geocode_restroom.py)을 먼저 돌려서 화장실 좌표를 채운 뒤 실행하세요.
"""
import os
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"

PROJECT = os.environ.get("GCP_PROJECT", "mlops-quicklab-500907")
DATASET = "camping_map"
TABLE = "facilities"
LOCATION = "asia-northeast3"  # 서울 (BigQuery 위치)


def read_sqlite_rows():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    for r in con.execute(
        "SELECT id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra "
        "FROM facilities WHERE lat IS NOT NULL"
    ):
        d = dict(r)
        # BQ는 JSON 문자열 그대로 STRING 컬럼에 저장
        yield d
    con.close()


def main():
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJECT, location=LOCATION)

    # 1) 데이터셋 생성 (없으면)
    ds_ref = bigquery.Dataset(f"{PROJECT}.{DATASET}")
    ds_ref.location = LOCATION
    client.create_dataset(ds_ref, exists_ok=True)
    print(f"데이터셋 준비: {PROJECT}.{DATASET}")

    # 2) 테이블 스키마 (좌표는 lat/lon + GEOGRAPHY는 이후 SQL로 생성)
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"
    schema = [
        bigquery.SchemaField("id", "STRING"),
        bigquery.SchemaField("category", "STRING"),
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("lat", "FLOAT"),
        bigquery.SchemaField("lon", "FLOAT"),
        bigquery.SchemaField("road_addr", "STRING"),
        bigquery.SchemaField("lotno_addr", "STRING"),
        bigquery.SchemaField("open_hours", "STRING"),
        bigquery.SchemaField("tel", "STRING"),
        bigquery.SchemaField("extra", "STRING"),
    ]
    table = bigquery.Table(table_id, schema=schema)
    client.delete_table(table_id, not_found_ok=True)
    client.create_table(table)

    rows = list(read_sqlite_rows())
    print(f"적재 대상: {len(rows):,}건 (좌표 있는 시설만)")
    # load job 사용: 6만 건 규모에선 streaming insert(행수/크기 제한·비용)보다 안정적
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_json(rows, table_id, job_config=job_config)
    job.result()  # 완료 대기
    print(f"적재 완료: {table_id} ({client.get_table(table_id).num_rows:,} rows)")

    # 3) GEOGRAPHY 뷰 생성 (ST_GEOGPOINT)
    geo_view = f"{PROJECT}.{DATASET}.facilities_geo"
    client.query(f"""
        CREATE OR REPLACE VIEW `{geo_view}` AS
        SELECT *, ST_GEOGPOINT(lon, lat) AS geo
        FROM `{table_id}`
    """).result()
    print(f"GEOGRAPHY 뷰 생성: {geo_view}")

    # 4) GIS 전처리 예시 — 해수욕장 반경 300m 내 화장실/주차장 카운트
    proximity = f"{PROJECT}.{DATASET}.beach_proximity"
    client.query(f"""
        CREATE OR REPLACE TABLE `{proximity}` AS
        SELECT
          b.id, b.name, b.lat, b.lon,
          (SELECT COUNT(*) FROM `{geo_view}` r
             WHERE r.category='restroom' AND ST_DWITHIN(b.geo, r.geo, 300)) AS restrooms_300m,
          (SELECT COUNT(*) FROM `{geo_view}` p
             WHERE p.category='parking' AND ST_DWITHIN(b.geo, p.geo, 300)) AS parking_300m
        FROM `{geo_view}` b
        WHERE b.category='beach'
    """).result()
    print(f"GIS 전처리 완료: {proximity} (해변별 300m 내 화장실·주차장 수)")


if __name__ == "__main__":
    main()
