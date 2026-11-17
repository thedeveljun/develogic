from typing import Literal
from pydantic import BaseModel, Field
class Event(BaseModel):
    date:str
    type:Literal['receipt','cost','equity_in','equity_out','draw','repay']
    amount:float=Field(ge=0)
    loan_id:str|None=None
class Loan(BaseModel):
    id:str
    limit:float=Field(ge=0)
    annual_rate:float=Field(ge=0)
    day_basis:Literal[360,365,366]=365
    payment_day:int=Field(default=0,ge=0,le=31)
class Project(BaseModel):
    project_type:Literal['general_housing','station_area_renewal']
    start:str
    end:str
    opening_cash:float=Field(default=0,ge=0)
    minimum_cash:float=Field(default=0,ge=0)
    loans:list[Loan]=[]
    events:list[Event]=[]
