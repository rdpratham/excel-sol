import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.models.file import File
    from app.models.user import User


class Sheet(UUIDPrimaryKey, Base):
    __tablename__ = "sheets"
    __table_args__ = (UniqueConstraint("file_id", "name", name="uq_sheet_file_name"),)

    file_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sheet_index: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    col_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # columns JSON: [{name, dtype, index, width, format?, align?}, ...]
    # format: "general" | "number" | "currency" | "percent"; align: "left" | "center" | "right"
    columns: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    # Sparse per-cell style overrides, keyed "{row_index}:{col_key}" ->
    # {bold?, italic?, font_color?, bg_color?, align?}. Column-level format/align
    # above covers whole-column formatting cheaply; this covers individual cells.
    cell_styles: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    file: Mapped["File"] = relationship("File", back_populates="sheets")
    rows: Mapped[List["SheetRow"]] = relationship("SheetRow", back_populates="sheet", cascade="all, delete-orphan")
    cell_edits: Mapped[List["CellEdit"]] = relationship("CellEdit", back_populates="sheet", cascade="all, delete-orphan")


class SheetRow(UUIDPrimaryKey, Base):
    """One row per record. data JSONB holds {col_key: value, ...}.

    Trade-off: row-per-record is simpler to query with SQL JOINs and maps
    naturally to spreadsheet semantics. The JSONB column with a GIN index
    keeps full-text search fast. Columnar/Parquet storage would win on
    analytical workloads (GROUP BY, wide aggregations) but requires an
    extra translation layer and complicates row-level edits. Given that
    SheetSense is an interactive editor first and analytics engine second,
    row-per-record is the right default.
    """

    __tablename__ = "sheet_rows"
    __table_args__ = (
        sa.Index("ix_sheet_rows_sheet_row", "sheet_id", "row_index"),
        sa.Index("ix_sheet_rows_data_gin", "data", postgresql_using="gin"),
    )

    sheet_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        ForeignKey("sheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    sheet: Mapped["Sheet"] = relationship("Sheet", back_populates="rows")


class CellEdit(UUIDPrimaryKey, Base):
    """Immutable audit trail + undo stack for individual cell changes."""

    __tablename__ = "cell_edits"

    sheet_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        ForeignKey("sheets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    col_key: Mapped[str] = mapped_column(String(255), nullable=False)
    old_value: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    sheet: Mapped["Sheet"] = relationship("Sheet", back_populates="cell_edits")
