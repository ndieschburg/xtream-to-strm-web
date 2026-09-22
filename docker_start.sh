#!/bin/bash
set -e

# Run database migrations
echo "🔄 Running database migrations..."
python3 /app/migrations/apply_migrations.py

# Start Redis server in the background
redis-server --dir /app --dbfilename dump.rdb --daemonize yes --pidfile /app/redis.pid --logfile /app/redis.log

# Wait for Redis to be ready
sleep 2

# Keep app.log bounded. Three processes append to it forever, so without this
# the file grows until the volume is full.
#
# The file is trimmed IN PLACE (cat > app.log keeps the same inode) instead of
# being renamed: `tee -a` keeps appending at the new end, and the `tail -f` that
# backs /api/v1/logs/stream recovers instead of following a deleted inode.
LOG_MAX_BYTES=${LOG_MAX_BYTES:-52428800}   # trim once the file passes 50 MB
LOG_KEEP_BYTES=${LOG_KEEP_BYTES:-10485760} # keep the last 10 MB
rotate_app_log() {
    while true; do
        sleep 300
        if [ -f app.log ]; then
            size=$(stat -c %s app.log 2>/dev/null || echo 0)
            if [ "$size" -gt "$LOG_MAX_BYTES" ]; then
                tail -c "$LOG_KEEP_BYTES" app.log > app.log.trim 2>/dev/null \
                    && cat app.log.trim > app.log \
                    && rm -f app.log.trim
            fi
        fi
    done
}
rotate_app_log &

# Start Celery worker in the background
celery -A app.core.celery_app worker --loglevel=info 2>&1 | tee -a app.log &

# Start Celery Beat in the background
celery -A app.core.celery_app beat --loglevel=info 2>&1 | tee -a app.log &

# Start the FastAPI application
uvicorn app.main:app --host 0.0.0.0 --port 8000 2>&1 | tee -a app.log
