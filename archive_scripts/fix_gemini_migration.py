import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from src.config import settings

async def alter_table():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        print("Clearing existing embeddings to avoid casting error...")
        await conn.execute(text("UPDATE item SET embedding = NULL;"))
        
        print("Altering item embedding to 768 dimensions...")
        await conn.execute(text("ALTER TABLE item ALTER COLUMN embedding TYPE vector(768);"))
    
    # Do knowledge_base in separate transaction just in case
    async with engine.begin() as conn:
        try:
            await conn.execute(text("UPDATE knowledge_base SET embedding = NULL;"))
            await conn.execute(text("ALTER TABLE knowledge_base ALTER COLUMN embedding TYPE vector(768);"))
            print("Altering knowledge_base embedding to 768 dimensions...")
        except Exception as e:
            print("knowledge_base not altered:", e)
            
    print("Done altering database.")
        
asyncio.run(alter_table())
