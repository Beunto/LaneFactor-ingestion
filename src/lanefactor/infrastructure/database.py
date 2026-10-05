import os
import sqlalchemy
from sqlalchemy import create_engine

URL = sqlalchemy.URL.create(
    drivername="postgresql+psycopg",
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT"),
    database=os.getenv("POSTGRES_DB"),
    username=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD")
)

engine = create_engine(URL)