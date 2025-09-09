# utils/data_loader.py
import pandas as pd

def load_csv(path: str, **kwargs) -> pd.DataFrame:
    """
    Load a CSV into a pandas DataFrame.
    Defaults to utf-8 encoding and handles common parsing options.
    """
    try:
        return pd.read_csv(path, encoding="utf-8", **kwargs)
    except UnicodeDecodeError:
        # Fallback for messy CSVs
        return pd.read_csv(path, encoding="latin-1", **kwargs)
