import pytest
from sqlalchemy import inspect
from app.models.conversation import Folder, Conversation


def test_folder_model_has_expected_columns():
    mapper = inspect(Folder)
    cols = {c.key for c in mapper.columns}
    assert cols == {"id", "name", "created_at"}


def test_conversation_has_folder_id_column():
    mapper = inspect(Conversation)
    cols = {c.key for c in mapper.columns}
    assert "folder_id" in cols


def test_folder_id_is_nullable():
    mapper = inspect(Conversation)
    col = mapper.columns["folder_id"]
    assert col.nullable is True
