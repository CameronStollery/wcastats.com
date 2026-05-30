from pydantic import BaseModel
from fastapi import FastAPI, HTTPException

app = FastAPI()

class WCAStatQuery(BaseModel):
    text: str

queries: list[WCAStatQuery] = []
# queries = []

@app.get("/")
def root():
    return {"test": "testval"}

@app.post("/queries")
def create_query(query: WCAStatQuery) -> list[WCAStatQuery]:
    queries.append(query)
    return queries
# @app.post("/queries")
# def create_query(query: str) -> str:
#     queries.append(query)
#     return query

@app.get("/queries/{query_id}", response_model=WCAStatQuery)
def get_query(query_id: int) -> WCAStatQuery:
    if query_id < len(queries):
        return queries[query_id]
    else:
        raise HTTPException(status_code=404, detail="Query not found")


# def main():
#     print("Hello from backend!")


# if __name__ == "__main__":
#     main()
