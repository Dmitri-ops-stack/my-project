from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import enum
from datetime import datetime
from config import DB_URL

Base = declarative_base()
engine = create_async_engine(DB_URL, echo=True)
AsyncSessionMaker = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class StatusEnum(enum.Enum):
    pending = "pending"
    approved = "approved"
    completed = "completed"
    canceled = "canceled"

class ClientStatus(enum.Enum):
    active = "active"
    blacklisted = "blacklisted"

class Client(Base):
    __tablename__ = 'clients'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    name = Column(String)
    city = Column(String)
    workplace = Column(String)
    product_type = Column(String)
    serial_number = Column(String)
    phone = Column(String)
    status = Column(Enum(ClientStatus), default=ClientStatus.active)
    rating = Column(Float, default=0.0)
    ratings_count = Column(Integer, default=0)
    appointments = relationship("Appointment", back_populates="client")

class Specialist(Base):
    __tablename__ = 'specialists'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    name = Column(String)
    username = Column(String)
    is_available = Column(Boolean, default=True)
    appointments = relationship("Appointment", back_populates="specialist")

class Appointment(Base):
    __tablename__ = 'appointments'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id'))
    specialist_id = Column(Integer, ForeignKey('specialists.id'))
    date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    status = Column(Enum(StatusEnum), default=StatusEnum.pending)
    description = Column(String)
    client_approved = Column(Boolean)
    specialist_approved = Column(Boolean)
    decline_reason = Column(String)
    client = relationship("Client", back_populates="appointments")
    specialist = relationship("Specialist", back_populates="appointments")

class Blacklist(Base):
    __tablename__ = 'blacklist'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id'))
    until = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

class Rating(Base):
    __tablename__ = 'ratings'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id'))
    specialist_id = Column(Integer, ForeignKey('specialists.id'))
    score = Column(Integer)
    comment = Column(String)
    created_at = Column(DateTime, default=datetime.now)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)