import sys
import os

sys.path.append(os.getcwd())

try:
    from src.posts import schemas
    print(f"Schemas loaded: {schemas}")
    print(f"Has Tag: {hasattr(schemas, 'Tag')}")
    print(f"Dir: {dir(schemas)}")
except Exception as e:
    print(f"Error importing schemas: {e}")
