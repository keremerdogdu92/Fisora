FROM postgres:16-alpine

RUN apk add --no-cache age python3 py3-psycopg2

COPY deploy/backup/backup.sh /usr/local/bin/fisora-backup.sh
COPY deploy/backup/verify_restore.sh /usr/local/bin/fisora-verify-restore.sh
COPY deploy/backup/verify_restore.py /usr/local/bin/fisora-verify-corpus.py

