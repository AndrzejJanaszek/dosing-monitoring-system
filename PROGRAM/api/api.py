from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json
import time

def create_api(core):
    app = FastAPI()

    # @app.get("/tanks/values")
    # def get_tanks_values():
    #     # return aktualne wartości dla wszystkich zbiorników
    #     pass

    # @app.get("/tanks/{tank_id}/value")
    # def get_tank_value(tank_id: int):
    #     # return aktualna wartość dla jednego zbiornika
    #     pass

    @app.get("/measurements")
    def get_measurements(
        tank_id: Optional[int] = None,
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to")
    ):
        # return pomiary z bazy z filtrami
        pass

    @app.get("/dosages")
    def get_dosages(
        tank_id: Optional[int] = None,
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to"),
        is_collision: Optional[bool] = None
    ):
        # return lista dosages z filtrami
        pass

    @app.get("/batches")
    def get_batches(
        tank_id: Optional[int] = None,
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to")
    ):
        # return lista batchy
        pass

    @app.get("/batches/last")
    def get_last_batch():
        # return ostatnia gruszka
        pass



    @app.get("/tanks/values/stream")
    def stream_tanks_values():
        def event_generator():
            while True:
                data = [{"id": t.id, "name": t.name, "value": t.current_value} for t in core["tanks"]]
                yield f"data: {json.dumps(data)}\n\n"
                time.sleep(1)  # co sekundę lub wg zdarzenia

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    return app
