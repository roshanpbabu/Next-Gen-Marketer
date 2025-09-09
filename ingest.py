# ingest.py
from pathlib import Path
from typing import Optional
from utils.data_loader import load_csv
from utils.rag_utils import upsert_dataframe_as_docs

DATA_DIR = Path("data")

def dynamic_ingest(
    csv_path: str,
    namespace: str,
    id_cols: Optional[list] = None,
    id_prefix: str = "dyn-",
    auto_text_only: bool = False
):
    """
    Ingest a CSV to Chroma dynamically:
      - uses all columns as text & metadata by default,
      - optionally uses only text columns (auto_text_only=True),
      - can accept id_cols to form stable IDs.
    """
    print(f"\n📂 Ingesting {csv_path} -> namespace '{namespace}'")
    df = load_csv(csv_path)

    if df is None or df.shape[0] == 0:
        print(f"⚠️  No data found in {csv_path}")
        return

    print(f"   Rows loaded: {len(df)} | Columns: {list(df.columns)}")

    upsert_dataframe_as_docs(
        df,
        namespace=namespace,
        text_cols=None,        # None = auto-select inside rag_utils
        meta_cols=None,        # None = all columns
        id_cols=id_cols,       # optional stable id columns
        id_prefix=id_prefix,
        batch_size=64,
        max_chars_per_doc=1500,
        auto_text_only=auto_text_only
    )

    print(f"✅ Completed ingestion for '{namespace}' ({len(df)} rows)")

if __name__ == "__main__":
    dynamic_ingest("data/sentiment_data.csv", "sentiment", id_cols=None, id_prefix="s-", auto_text_only=False)
    dynamic_ingest("data/purchase_data.csv", "purchase", id_cols=None, id_prefix="p-", auto_text_only=False)
    dynamic_ingest("data/campaign_data.csv", "campaign", id_cols=None, id_prefix="c-", auto_text_only=False)
    print("\n🎉 Dynamic ingestion complete for all datasets")
