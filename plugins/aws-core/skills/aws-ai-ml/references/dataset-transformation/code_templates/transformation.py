# Dataset Transformation Template
# Cell structure for a dataset transformation notebook.
# The transformation function (Cell 2) is generated dynamically based on the user's
# source and target formats. All other cells follow this skeleton.

# Cell 0 [markdown]: Dataset Transformation
# Description of the transformation (source format → target format)

# Cell 1: Configuration

INPUT_LOCATION = "[INPUT_LOCATION]"  # S3 URI or local path to input dataset
OUTPUT_LOCATION = "[OUTPUT_LOCATION]"  # S3 URI or local path for output

# Cell 2: Transformation Function
# This cell is generated dynamically based on the user's source → target format.
# In notebook mode, it uses %%writefile to save the function to transform_fn.py.
# In script mode, the function is written to disk directly.
# It must define:
#
#   def transform_dataset(df: pd.DataFrame) -> pd.DataFrame:
#       ...
#
# The function should ONLY transform the DataFrame schema. No I/O, no side effects.

# Cell 3: Load Dataset

import pandas as pd
from transform_fn import transform_dataset

df = pd.read_json(INPUT_LOCATION, lines=True)
print(f"Loaded {len(df)} records")
print(f"Columns: {list(df.columns)}")
df.head(2)

# Cell 4: Transform

df_transformed = transform_dataset(df)
print(f"Transformed {len(df_transformed)} records")
print(f"Columns: {list(df_transformed.columns)}")
df_transformed.head(2)

# Cell 5: Save Output

df_transformed.to_json(OUTPUT_LOCATION, orient="records", lines=True)
print(f"Saved {len(df_transformed)} records to {OUTPUT_LOCATION}")
