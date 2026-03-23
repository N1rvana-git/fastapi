from sqlalchemy import select, Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class ItemModel(Base):
    __tablename__ = "item"
    id = Column(Integer, primary_key=True)

query1 = select(ItemModel).where(ItemModel.id == 28)
query2 = select(ItemModel).where(ItemModel.id == '28')

print(query1.compile().params)
print(query2.compile().params)
