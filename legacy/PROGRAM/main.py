import uvicorn
from api.api import create_api
from core.core import create_core

def main():
    core = create_core()

    app = create_api(core)

    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
