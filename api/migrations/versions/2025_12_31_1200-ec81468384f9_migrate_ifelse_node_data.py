"""migrate ifelse node data

Revision ID: ec81468384f9
Revises: 03ea244985ce
Create Date: 2025-12-31 12:00:00.000000

"""
import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = 'ec81468384f9'
down_revision = '03ea244985ce'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Select id, graph from workflows where graph like '%if-else%'
    # Using text() for raw SQL
    stmt = text("SELECT id, graph FROM workflows WHERE graph LIKE :pattern")
    result = conn.execute(stmt, {"pattern": '%"type": "if-else"%'}).fetchall()

    for row in result:
        workflow_id = row[0]
        graph_json = row[1]
        if not graph_json:
            continue

        try:
            graph = json.loads(graph_json)
        except json.JSONDecodeError:
            continue

        nodes = graph.get("nodes", [])
        modified = False
        for node in nodes:
            if node.get("data", {}).get("type") == "if-else":
                data = node["data"]
                # Check if migration is needed
                # If cases is missing/empty and conditions/logical_operator exist
                if not data.get("cases") and "conditions" in data:
                    # Old structure found
                    # Create a single case with id "true"
                    cases = [{
                        "case_id": "true",
                        "logical_operator": data.get("logical_operator", "and"),
                        "conditions": data.get("conditions", [])
                    }]
                    data["cases"] = cases
                    # Remove old fields
                    data.pop("conditions", None)
                    data.pop("logical_operator", None)
                    modified = True

        if modified:
            new_graph_json = json.dumps(graph)
            # Update the row
            update_stmt = text("UPDATE workflows SET graph = :graph WHERE id = :id")
            conn.execute(update_stmt, {"graph": new_graph_json, "id": workflow_id})

def downgrade():
    # Downgrade logic: Revert cases back to conditions if there is only one case with case_id="true"
    conn = op.get_bind()
    stmt = text("SELECT id, graph FROM workflows WHERE graph LIKE :pattern")
    result = conn.execute(stmt, {"pattern": '%"type": "if-else"%'}).fetchall()

    for row in result:
        workflow_id = row[0]
        graph_json = row[1]
        if not graph_json:
            continue

        try:
            graph = json.loads(graph_json)
        except json.JSONDecodeError:
            continue

        nodes = graph.get("nodes", [])
        modified = False
        for node in nodes:
            if node.get("data", {}).get("type") == "if-else":
                data = node["data"]
                if data.get("cases"):
                    cases = data["cases"]
                    # If we have exactly one case which is "true", we can revert to old structure safely-ish
                    if len(cases) == 1 and cases[0].get("case_id") == "true":
                        case = cases[0]
                        data["logical_operator"] = case.get("logical_operator", "and")
                        data["conditions"] = case.get("conditions", [])
                        data.pop("cases", None)
                        modified = True
                    # If there are multiple cases or different IDs, we can't easily revert to old structure without loss.
                    # We skip those.

        if modified:
            new_graph_json = json.dumps(graph)
            update_stmt = text("UPDATE workflows SET graph = :graph WHERE id = :id")
            conn.execute(update_stmt, {"graph": new_graph_json, "id": workflow_id})
