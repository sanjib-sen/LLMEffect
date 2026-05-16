# Safe rewrite of the text-to-SQL agent. Expect zero violations.
from llmeffect_runtime import (
    safe_llm_call, Trusted, Internal, Tainted, DatabaseCall,
)


def ask_database(client, user_question, user_db):
    schema = user_db.get_schema()
    result = safe_llm_call(
        client,
        model="gpt-4",
        instructions=Trusted("Generate a SQL query."),
        context=[Internal(schema), Tainted(user_question)],
    )
    validated = result.validate(
        DatabaseCall(
            allowed_operations=["SELECT"],
            allowed_tables=["products"],
            allowed_columns=["name", "price"],
        )
    )
    if validated:
        return user_db.execute(validated.value)
    return None
