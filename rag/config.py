from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_RAW_DIR = BASE_DIR / "data" / "raw"

VECTORSTORE_DIR = BASE_DIR / "rag" / "vectorstore"
FAISS_INDEX_PATH = VECTORSTORE_DIR / "faiss.index"
METADATA_PATH = VECTORSTORE_DIR / "metadata.pkl"

EMBEDDING_MODEL_NAME = "jhgan/ko-sroberta-multitask"

SOURCE_FILES = [
    "camping.jsonl",
    "festival.jsonl",
    "city_tour.jsonl",
    "theme_park.jsonl",
    "hanok_stay.jsonl",
    #"camping_rules.jsonl", 필요없는 데이터같아서 일단 주석처리해두고 나중에 필요하면 다시살릴예정
    "regulations.jsonl",
    "ordinances.jsonl",
    "notices_api.jsonl",
]