# schemas.py
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime

class NewsCard(BaseModel):
    id: str
    name: str
    image_url: str
    catchy_title: Optional[str] = None
    summary: Optional[str] = None
    link: str
    published_at: Optional[str] = None  # input can be string

class PersonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    image_url: str

class ArticleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    summary: str
    link: str
    source_name: Optional[str] = None
    published_at: Optional[datetime] = None  

class PersonNewsCard(BaseModel):
    id: int
    name: str
    image_url: str
    articles: List[ArticleResponse]
