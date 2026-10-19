"""Lookup helpers for provider-specific voice runtime bindings."""


def resolve_voice_binding(db, voice_pool_id: str, kind: str, config_id: str) -> dict | None:
    """Return the internal binding for one exact voice/runtime/config tuple."""
    row = db.execute(
        "SELECT * FROM voice_runtime_bindings "
        "WHERE voice_pool_id = ? AND runtime_kind = ? AND runtime_config_id = ?",
        (voice_pool_id, kind, config_id),
    ).fetchone()
    return dict(row) if row else None


def list_voice_bindings(db, voice_pool_id: str) -> list[dict]:
    """Return administrative binding summaries without provider voice IDs."""
    rows = db.execute(
        """
        SELECT b.id, b.voice_pool_id, b.runtime_kind, b.runtime_config_id,
               rc.name AS runtime_config_name, rc.model AS runtime_config_model,
               b.created_at
        FROM voice_runtime_bindings b
        JOIN realtime_configs rc ON rc.id = b.runtime_config_id
        WHERE b.voice_pool_id = ? AND b.runtime_kind = 'realtime'
        UNION ALL
        SELECT b.id, b.voice_pool_id, b.runtime_kind, b.runtime_config_id,
               tc.name AS runtime_config_name, tc.model AS runtime_config_model,
               b.created_at
        FROM voice_runtime_bindings b
        JOIN tts_configs tc ON tc.id = b.runtime_config_id
        WHERE b.voice_pool_id = ? AND b.runtime_kind = 'tts'
        """,
        (voice_pool_id, voice_pool_id),
    ).fetchall()
    return [dict(row) for row in rows]
