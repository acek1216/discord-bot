# bot.py (最小テスト用コード)
import contextlib
from fastapi import FastAPI

# --- ファイルが実行されたことを示すログ ---
print("--- [STEP 1] bot.py ファイルの読み込みが開始されました ---")

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # --- lifespanが実行されたことを示すログ ---
    print("--- [STEP 2] FastAPIのlifespanが正常に開始しました ---")
    yield
    print("--- [STEP 4] FastAPIのlifespanが終了します ---")

# --- FastAPIアプリが作成されたことを示すログ ---
app = FastAPI(lifespan=lifespan)
print("--- [STEP 3] FastAPIのappオブジェクトが作成されました ---")

@app.get("/")
def health_check():
    return {"status": "ok"}
