"""Unit tests for error clustering and normalization."""

from datetime import datetime
from logdetective.cluster import (
    ClusterStore,
    compute_fingerprint,
    normalize_message,
)
from logdetective.contract import Event


def test_normalize_tokens():
    msg = "Connection to 192.168.1.100:5432 failed for user admin@example.com with uuid 12345678-1234-5678-1234-567812345678"
    norm = normalize_message(msg)
    assert "<IP>" in norm
    assert "<EMAIL>" in norm
    assert "<ID>" in norm


def test_normalize_planted_patterns():
    # Database timeout
    norm_timeout = normalize_message("Connection to database 10.0.4.12:5432 timed out after 5000ms")
    assert norm_timeout == "Connection to database <IP> timed out after <NUM>ms"

    # Pool usage
    norm_pool = normalize_message("Connection pool usage above threshold: 88%")
    assert norm_pool == "Connection pool usage above threshold: <NUM>%"

    # Retry storm
    norm_retry = normalize_message("Retrying operation after error: 'Connection refused'")
    assert norm_retry == "Retrying operation after error: <STR>"

    # Pool exhausted
    norm_exhaust = normalize_message("Pool exhausted: cannot allocate connection to /var/run/postgresql/.s.PGSQL.5432")
    assert norm_exhaust == "Pool exhausted: cannot allocate connection to <PATH>"


def test_cluster_store_first_seen_and_frequency():
    store = ClusterStore()

    e1 = Event(
        line_no=100,
        ts=datetime(2026, 11, 21, 10, 0, 0),
        level="ERROR",
        message="Connection to database 10.0.1.20:5432 timed out after 5000ms",
    )
    cid1, is_first1 = store.add(e1)
    assert is_first1 is True

    e2 = Event(
        line_no=250,
        ts=datetime(2026, 11, 21, 10, 5, 0),
        level="ERROR",
        message="Connection to database 10.0.2.35:5432 timed out after 3000ms",
    )
    cid2, is_first2 = store.add(e2)
    assert is_first2 is False
    assert cid1 == cid2

    clusters, _, _ = store.build_clusters(e1.ts, e2.ts, num_buckets=10)
    assert len(clusters) == 1
    assert clusters[0].count == 2
    assert clusters[0].first_seen.line_no == 100
    assert clusters[0].last_seen.line_no == 250
    assert clusters[0].template == "Connection to database <IP> timed out after <NUM>ms"
