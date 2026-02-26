try:
    from src.posts.utils import get_password_hash
    print(f"Hash: {get_password_hash('test1234')}")
except Exception as e:
    import traceback
    traceback.print_exc()
