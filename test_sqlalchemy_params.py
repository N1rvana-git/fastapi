from sqlalchemy import select, Column, Integer, String, Float, Boolean
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class ItemModel(Base):
    __tablename__ = "item"
    id = Column(Integer, primary_key=True)

query1 = select(ItemModel).where(ItemModel.id == 28)
query2 = select(ItemModel).where(ItemModel.id == '28')

print("query1 parameters:", query1.compile().compile_state.construct_params())
print("query2 parameters:", query2.compile().compile_state.construct_params())
