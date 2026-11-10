from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "data-refresh.yml"


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_gatilhos_e_permissoes_minimas(workflow):
    triggers = workflow[True]  # PyYAML lê a chave "on" como booleano
    assert triggers["schedule"][0]["cron"].startswith("47 */")
    assert "workflow_dispatch" in triggers
    assert workflow["permissions"] == {"contents": "write", "issues": "write"}


def test_concorrencia_e_limite_de_tempo(workflow):
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["jobs"]["refresh"]["timeout-minutes"] <= 60


def test_manifesto_e_publicado_depois_do_pacote_e_issue_sem_duplicar(workflow):
    steps = {step.get("name"): step for step in workflow["jobs"]["refresh"]["steps"]}
    publish = steps["Publicar no Release"]["run"]
    assert publish.index("nba-full.tar.gz") < publish.index("manifest.json")
    assert "--clobber" in publish
    failure = steps["Abrir ou atualizar a issue de falha"]["run"]
    assert "gh issue list" in failure and "gh issue comment" in failure
    assert "gh issue close" in steps["Fechar a issue de falha quando voltar ao normal"]["run"]


def test_nenhum_segredo_alem_do_token_do_proprio_workflow():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("secrets.") == text.count("secrets.GITHUB_TOKEN")
