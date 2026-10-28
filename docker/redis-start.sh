#!/bin/sh
set -eu

# Convert legacy RDB before enabling AOF. The temporary server is not reachable
# by application containers and does not satisfy the normal port 6379 healthcheck.
if [ -e /data/.crm-aof-converting ] || { [ -s /data/dump.rdb ] && [ ! -s /data/appendonlydir/appendonly.aof.manifest ] && [ ! -s /data/appendonly.aof ]; }; then
    [ -s /data/dump.rdb ] || { echo 'CRM Redis: conversion snapshot missing' >&2; exit 1; }
    touch /data/.crm-aof-converting
    echo 'CRM Redis: converting existing snapshot to AOF'
    docker-entrypoint.sh redis-server --dir /data --bind 127.0.0.1 --port 6380 --save '' --appendonly no &
    conversion_pid=$!
    trap 'kill -TERM "$conversion_pid" 2>/dev/null || true; wait "$conversion_pid" || true' EXIT
    trap 'exit 143' TERM INT
    ready=0
    for attempt in $(seq 1 300); do
        kill -0 "$conversion_pid"
        if redis-cli -p 6380 ping 2>/dev/null | grep -q PONG; then ready=1; break; fi
        sleep 1
    done
    [ "$ready" = 1 ] || { echo 'CRM Redis: snapshot load timed out' >&2; exit 1; }
    redis-cli -p 6380 CONFIG SET appendonly yes | grep -q '^OK'
    complete=0
    for attempt in $(seq 1 300); do
        kill -0 "$conversion_pid"
        info=$(redis-cli -p 6380 INFO persistence | tr -d '\r')
        if echo "$info" | grep -q '^aof_rewrite_in_progress:0$' &&
           echo "$info" | grep -q '^aof_rewrite_scheduled:0$' &&
           echo "$info" | grep -q '^aof_last_bgrewrite_status:ok$' &&
           [ -s /data/appendonlydir/appendonly.aof.manifest ]; then
            complete=1; break
        fi
        sleep 1
    done
    [ "$complete" = 1 ] || { echo 'CRM Redis: AOF conversion failed; startup stopped' >&2; exit 1; }
    redis-cli -p 6380 SHUTDOWN SAVE
    wait "$conversion_pid"
    rm /data/.crm-aof-converting
    trap - EXIT TERM INT
fi

exec docker-entrypoint.sh redis-server --dir /data --appendonly yes --appendfsync everysec
