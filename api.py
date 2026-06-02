from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Portfolio Management System API Running"}

@app.get("/portfolio")
def portfolio():
    return {
        "portfolio_value": 16241568.58,
        "assets": 15,
        "sectors": 7
    }