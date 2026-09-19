import pytest

from tests.synth import Synthetic, write_record


@pytest.fixture(scope="session")
def record(tmp_path_factory: pytest.TempPathFactory) -> Synthetic:
    """Одна синтетическая запись на сессию: 10 минут, 12 отведений, известные удары и ошибки прибора."""
    return write_record(tmp_path_factory.mktemp("record"), seconds=600)
