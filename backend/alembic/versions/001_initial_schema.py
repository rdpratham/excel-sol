"""Initial schema — all tables

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── Enums ─────────────────────────────────────────────────────────────────
    op.execute("CREATE TYPE userrole AS ENUM ('admin', 'editor', 'viewer')")
    op.execute("CREATE TYPE filestatus AS ENUM ('uploading', 'processing', 'ready', 'failed')")
    op.execute("CREATE TYPE chatrole AS ENUM ('user', 'assistant')")

    # ── users ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE users (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email       CITEXT UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            full_name   VARCHAR(255) NOT NULL,
            role        userrole NOT NULL DEFAULT 'editor',
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            last_login_at TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_users_email ON users (email)")

    # ── sessions ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE sessions (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            refresh_token_hash  VARCHAR(64) NOT NULL,
            expires_at          TIMESTAMPTZ NOT NULL,
            revoked_at          TIMESTAMPTZ,
            ip                  VARCHAR(45),
            user_agent          VARCHAR(500),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_sessions_user_id ON sessions (user_id)")
    op.execute("CREATE INDEX ix_sessions_refresh_token_hash ON sessions (refresh_token_hash)")

    # ── files ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE files (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            original_filename VARCHAR(500) NOT NULL,
            display_name      VARCHAR(500) NOT NULL,
            storage_key       VARCHAR(1000) NOT NULL DEFAULT '',
            size_bytes        INTEGER NOT NULL DEFAULT 0,
            mime_type         VARCHAR(255) NOT NULL DEFAULT '',
            status            filestatus NOT NULL DEFAULT 'uploading',
            error_message     TEXT,
            sheet_count       INTEGER NOT NULL DEFAULT 0,
            total_rows        INTEGER NOT NULL DEFAULT 0,
            deleted_at        TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_files_owner_id ON files (owner_id)")
    op.execute("CREATE INDEX ix_files_status ON files (status)")
    op.execute("CREATE INDEX ix_files_deleted_at ON files (deleted_at) WHERE deleted_at IS NULL")

    # ── sheets ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE sheets (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            file_id      UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            name         VARCHAR(255) NOT NULL,
            sheet_index  INTEGER NOT NULL,
            row_count    INTEGER NOT NULL DEFAULT 0,
            col_count    INTEGER NOT NULL DEFAULT 0,
            columns      JSONB,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_sheet_file_name UNIQUE (file_id, name)
        )
    """)
    op.execute("CREATE INDEX ix_sheets_file_id ON sheets (file_id)")

    # ── sheet_rows ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE sheet_rows (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sheet_id    UUID NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
            row_index   INTEGER NOT NULL,
            data        JSONB NOT NULL DEFAULT '{}',
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by  UUID REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    op.execute("CREATE INDEX ix_sheet_rows_sheet_row ON sheet_rows (sheet_id, row_index)")
    op.execute("CREATE INDEX ix_sheet_rows_data_gin ON sheet_rows USING gin (data)")

    # ── cell_edits ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cell_edits (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sheet_id    UUID NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
            row_index   INTEGER NOT NULL,
            col_key     VARCHAR(255) NOT NULL,
            old_value   JSONB,
            new_value   JSONB,
            user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_cell_edits_sheet_id ON cell_edits (sheet_id)")
    op.execute("CREATE INDEX ix_cell_edits_user_id ON cell_edits (user_id)")

    # ── chat_messages ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE chat_messages (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            file_id         UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            sheet_id        UUID REFERENCES sheets(id) ON DELETE SET NULL,
            role            chatrole NOT NULL,
            content         TEXT NOT NULL,
            sql_executed    TEXT,
            result_preview  JSONB,
            tokens_used     INTEGER NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_chat_messages_user_file ON chat_messages (user_id, file_id)")
    op.execute("CREATE INDEX ix_chat_messages_created_at ON chat_messages (created_at)")

    # ── audit_logs ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE audit_logs (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
            action       VARCHAR(100) NOT NULL,
            entity_type  VARCHAR(100),
            entity_id    VARCHAR(100),
            ip           VARCHAR(45),
            user_agent   VARCHAR(500),
            metadata     JSONB,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id)")
    op.execute("CREATE INDEX ix_audit_logs_action ON audit_logs (action)")
    op.execute("CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS chat_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS cell_edits CASCADE")
    op.execute("DROP TABLE IF EXISTS sheet_rows CASCADE")
    op.execute("DROP TABLE IF EXISTS sheets CASCADE")
    op.execute("DROP TABLE IF EXISTS files CASCADE")
    op.execute("DROP TABLE IF EXISTS sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
    op.execute("DROP TYPE IF EXISTS chatrole")
    op.execute("DROP TYPE IF EXISTS filestatus")
    op.execute("DROP TYPE IF EXISTS userrole")
