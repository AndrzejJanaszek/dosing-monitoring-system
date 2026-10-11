from typing import Optional
from fastapi import FastAPI, Query
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
        return core["db"].get_measurements(tank_id, from_date, to_date)

    @app.get("/dosages")
    def get_dosages(
        tank_id: Optional[int] = None,
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to"),
        is_collision: Optional[bool] = None
    ):
        # return lista dosages z filtrami
        return core["db"].get_dosages(tank_id, from_date, to_date, is_collision)

    @app.get("/batches")
    def get_batches(
        tank_id: Optional[int] = None,
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to")
    ):
        # return lista batchy
        return core["db"].get_batches(tank_id, from_date, to_date)

    
    @app.get("/batches/last/stream")
    def stream_last_batch():
        def event_generator():
            event = core["db"].batch_update_event
            while True:
                event.wait()
                event.clear()

                last_batch = core["db"].get_last_batch()
                yield f"data: {json.dumps(last_batch)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")



    @app.get("/tanks/values/stream")
    def stream_tanks_values():
        def event_generator():
            event = core["serial"].tank_data_update_event
            while True:
                # czekamy aż pojawi się nowa wartość
                event.wait()
                event.clear()

                data = [
                    {"id": t.id, "name": t.name, "value": core["serial"].get_tank_data(t.port)}
                    for t in core["tanks"]
                ]
                yield f"data: {json.dumps(data)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    # 
    # ----------------------------------------------
    # 
    return app
