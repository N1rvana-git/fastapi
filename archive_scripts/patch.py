from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import sys

def add_exception_handler(app):
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        print("🔥 VALIDATION ERROR:", exc.errors(), file=sys.stderr, flush=True)
        try:
            body = await request.body()
            print("📦 BODY:", body.decode(), file=sys.stderr, flush=True)
        except:
            pass
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
