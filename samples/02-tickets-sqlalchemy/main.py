import os

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

engine = create_engine(os.environ["DATABASE_URL"])
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
app = FastAPI(title="Tickets")


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    seats_left = Column(Integer, nullable=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/events/{event_id}/book")
def book(event_id: int, seats: int = 1, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if event is None:
        raise HTTPException(404, "no such event")
    if event.seats_left < seats:
        raise HTTPException(409, "sold out")
    event.seats_left = event.seats_left - seats
    db.commit()
    return {"seats_left": event.seats_left}
