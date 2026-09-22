from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from app.db.session import get_db
from app.models.sync_state import SyncState
from app.models.schedule_execution import ScheduleExecution, ExecutionStatus
from app.schemas import SyncStatusResponse, SyncTriggerResponse
from app.tasks.sync import sync_movies_task, sync_series_task

router = APIRouter()

@router.get("/status", response_model=List[SyncStatusResponse])
def get_sync_status(db: Session = Depends(get_db)):
    states = db.query(SyncState).all()
    return [
        SyncStatusResponse(
            id=state.id,
            subscription_id=state.subscription_id,
            type=state.type,
            status=state.status,
            last_sync=state.last_sync,
            items_added=state.items_added,
            items_deleted=state.items_deleted,
            files_written=state.files_written or 0,
            error_message=state.error_message
        ) for state in states
    ]


@router.post("/movies/{subscription_id}", response_model=SyncTriggerResponse)
def trigger_movie_sync(subscription_id: int, db: Session = Depends(get_db)):
    task = sync_movies_task.delay(subscription_id)
    # Save task_id to sync_state
    sync_state = db.query(SyncState).filter(
        SyncState.subscription_id == subscription_id,
        SyncState.type == "movies"
    ).first()
    
    if not sync_state:
        sync_state = SyncState(subscription_id=subscription_id, type="movies")
        db.add(sync_state)
        db.commit()
        db.refresh(sync_state)
        
    sync_state.task_id = task.id
    db.commit()
    return SyncTriggerResponse(message="Movie sync started", task_id=task.id)

@router.post("/series/{subscription_id}", response_model=SyncTriggerResponse)
def trigger_series_sync(subscription_id: int, db: Session = Depends(get_db)):
    task = sync_series_task.delay(subscription_id)
    # Save task_id to sync_state
    sync_state = db.query(SyncState).filter(
        SyncState.subscription_id == subscription_id,
        SyncState.type == "series"
    ).first()
    
    if not sync_state:
        sync_state = SyncState(subscription_id=subscription_id, type="series")
        db.add(sync_state)
        db.commit()
        db.refresh(sync_state)

    sync_state.task_id = task.id
    db.commit()
    return SyncTriggerResponse(message="Series sync started", task_id=task.id)

@router.post("/stop/{subscription_id}/{sync_type}")
def stop_sync(subscription_id: int, sync_type: str, db: Session = Depends(get_db)):
    """Stop a running sync task"""
    from app.core.celery_app import celery_app

    sync_state = db.query(SyncState).filter(
        SyncState.subscription_id == subscription_id,
        SyncState.type == sync_type
    ).first()

    if not sync_state or not sync_state.task_id:
        return {"message": "No running task found"}

    # Revoke the task
    celery_app.control.revoke(sync_state.task_id, terminate=True)

    # Update sync_state status
    sync_state.status = "idle"
    sync_state.task_id = None

    # Update any running execution records to cancelled
    running_executions = db.query(ScheduleExecution).filter(
        ScheduleExecution.subscription_id == subscription_id,
        ScheduleExecution.sync_type == sync_type,
        ScheduleExecution.status == ExecutionStatus.RUNNING
    ).all()

    for execution in running_executions:
        execution.status = ExecutionStatus.CANCELLED
        execution.completed_at = datetime.utcnow()

    db.commit()

    return {"message": f"{sync_type.capitalize()} sync stopped successfully"}
